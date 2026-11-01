import { expect, mock, test } from 'claude-code/testing'

import { formatRemaining, remainingOf } from '../hooks/agents'
import { estimateKey, progressOf, waitLabel } from '../hooks/waiting'

// The band above the prompt as a surface mounts it.
const BAND = { plugin: 'tool-fold', component: 'AbovePrompt', props: { hasSurvey: false, bodyColumns: 100 } } as const

// A notification as the engine queues it.
const notice = (taskId: string, status?: string) => ({
  text: `<task-notification><task-id>${taskId}</task-id>${status === undefined ? '' : `<status>${status}</status>`}</task-notification>`,
  origin: { kind: 'task-notification' },
})

// The "Agentes" pane as VS Code mounts it.
const PANE = {
  plugin: 'tool-fold',
  component: 'Pane',
  requestId: 'agents',
  surface: 'vscode',
  props: { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'inline', scroll: { offset: 0, bodyRows: 12 }, view: {} },
} as const

const done = { reason: 'answer', answer: '', durationMs: 1000, isAborted: false, turnId: 't1' } as const

/** The engine beneath the mod: a background Bash answers a task id, the store is a map. */
function engine(on: Parameters<Parameters<typeof test>[1]>[1], saved: Record<string, unknown> = {}) {
  on('store.get', (_, e) => ({ value: saved[e.key] }))
  on('store.set', (_, e) => {
    saved[e.key] = e.value
    return { value: undefined }
  })
  on('tool.call', (_, e) => ({
    result: e.tool === 'Bash' ? { stdout: '', stderr: '', interrupted: false, backgroundTaskId: 'b1' } : { taskId: 'm1', timeoutMs: 0 },
  }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  // The band beneath the mod: empty.
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'band' }))
  on('prompt.submit', (_, e) => ({ ...e }))
  on('session.model', () => ({ value: 'claude-opus-5-5' }))
  return mock.clock(on)
}

const BENCH = { tool: 'Bash', command: 'cargo bench --release', description: 'Run the bench', run_in_background: true } as const

test('keys, labels and progress', () => {
  expect(estimateKey('shell', { command: 'cd /x && cargo bench --release -p core' })).toBe('bash:cargo bench')
  expect(estimateKey('monitor', { description: ' Watch CI ' })).toBe('monitor:watch ci')
  expect(waitLabel('shell', { command: 'cargo bench\nmore' })).toBe('cargo bench')
  expect(waitLabel('shell', { command: 'x', description: 'Run the bench' })).toBe('Run the bench')
  expect(progressOf(90_000, 180_000)).toBe(0.5)
  expect(progressOf(400_000, 180_000)).toBe(0.95)
  expect(progressOf(5000, undefined)).toBeUndefined()
})

test('the main agent card shows once the turn ends, counts up, and goes with the work', async ($, on) => {
  const clock = engine(on)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  // The turn still runs: nothing waits yet.
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await ui.unmount()

  await $.turn.complete(done)
  await clock.advance(72_000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /opus-5-5/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Run the bench/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /bash · en segundo plano/ })).toBeDefined()
  // No sample yet: elapsed only, no percentage.
  expect(await ui.find({ type: 'Text', text: /1m 12s/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  // The clock moves the card.
  await clock.advance(3000)
  expect(await ui.find({ type: 'Text', text: /1m 15s/ })).toBeDefined()
  await ui.unmount()

  // The pane lists it as it lists any running agent.
  const pane = await $.ui.mount(PANE as never)
  expect(await pane.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /Run the bench/ })).toBeDefined()
  await pane.unmount()

  // The work ends: the notification clears the card.
  await $.prompt.submit(notice('b1', 'completed') as never)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await ui.unmount()
})

test('a recorded sample gives the estimate and the progress', async ($, on) => {
  const saved: Record<string, unknown> = { 'wait-durations:bash:cargo bench': [100_000, 180_000, 240_000] }
  const clock = engine(on, saved)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(90_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /1m 30s/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  await ui.unmount()

  // It finishes after 4 minutes: the duration joins the samples.
  await clock.advance(150_000)
  await $.prompt.submit(notice('b1', 'completed') as never)
  expect(saved['wait-durations:bash:cargo bench']).toEqual([100_000, 180_000, 240_000, 240_000])
})

test('a new turn hides the card, a monitor event keeps its wait, and a killed task teaches nothing', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = engine(on, saved)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call({ tool: 'Monitor', description: 'Watch CI', timeout_ms: 300000, command: 'gh run watch' })
  await $.turn.complete(done)
  await clock.advance(5000)
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Watch CI/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /monitor · en segundo plano/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  await ui.unmount()

  // An event line wakes the model: new turn, no card; it ends, the card is back.
  await $.prompt.submit(notice('m1') as never)
  await $.turn.start({ text: '', turnId: 't2' })
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await ui.unmount()
  await $.turn.complete({ ...done, turnId: 't2' })
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Watch CI/ })).toBeDefined()
  await ui.unmount()

  await clock.advance(10_000)
  await $.prompt.submit(notice('m1', 'killed') as never)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await ui.unmount()
  expect(saved['wait-durations:monitor:watch ci']).toBeUndefined()
})

test('a background agent is waited on until its turn ends', async ($, on) => {
  const clock = engine(on)
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: 'a1' }))
  on('model.complete', () => ({
    value: { isAnswered: false, text: '', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } },
  }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({
    tool_use_id: 'tu1',
    prompt: 'Review it',
    description: 'Review the diff',
    subagentType: 'Explore',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: true,
    fork: false,
  } as never)
  await $.turn.complete(done)
  await clock.advance(2000)
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /agente · en segundo plano/ })).toBeDefined()
  await ui.unmount()

  await $.turn.complete({ ...done, agentId: 'a1', turnId: 's1' })
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await ui.unmount()
})

test('formatRemaining and remainingOf', () => {
  expect(formatRemaining(45_000)).toBe('<1 min')
  expect(formatRemaining(180_000)).toBe('~3 min')
  expect(formatRemaining(65 * 60_000)).toBe('~1 h 5 min')
  expect(formatRemaining(120 * 60_000)).toBe('~2 h')
  // elapsed × (1 − p) / p; none without an estimate or at 5% and under.
  expect(remainingOf(120_000, 40)).toBe('~3 min')
  expect(remainingOf(120_000, 5)).toBeUndefined()
  expect(remainingOf(120_000, undefined)).toBeUndefined()
})

test('the main agent card comes first, stands out, and shows the time left', async ($, on) => {
  const saved: Record<string, unknown> = { 'wait-durations:bash:cargo bench': [180_000] }
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: 'a1' }))
  const clock = engine(on, saved)
  await $.agent.spawn({
    tool_use_id: 'tu1',
    prompt: 'Find where sessions are created',
    description: 'Find session creation',
    subagentType: 'Explore',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: false,
    fork: false,
  } as never)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(90_000)

  for (const surface of ['desktop', 'pane'] as const) {
    const ui = surface === 'pane' ? await $.ui.mount(PANE as never) : await $.ui.mount({ ...BAND, surface: 'desktop' })
    const texts = (await ui.findAll({ type: 'Text' })).map(item => item.text)
    const main = texts.findIndex(text => /Claude · esperando/.test(text))
    const other = texts.findIndex(text => /Explore/.test(text))
    expect(main).toBeGreaterThanOrEqual(0)
    expect(other).toBeGreaterThan(main)
    const name = await ui.find({ type: 'Text', text: /Claude · esperando/ })
    expect(name?.props.underline).toBe(true)
    expect(name?.props.weight).toBe('bold')
    expect(name?.text).toMatch(/^◆/)
    // 50% at 90 s: 90 s left.
    expect(await ui.find({ type: 'Text', text: /≈50% · ~2 min/ })).toBeDefined()
    await ui.unmount()
  }
})
