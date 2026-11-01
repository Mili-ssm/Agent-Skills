import { expect, mock, test } from 'claude-code/testing'

import { approx, estimateKey, glyphLine, progressOf, progressSvg, waitLabel } from '../hooks/waiting'

// The band above the prompt as a surface mounts it.
const BAND = { plugin: 'tool-fold', component: 'AbovePrompt', props: { hasSurvey: false, bodyColumns: 100 } } as const

// A notification as the engine queues it.
const notice = (taskId: string, status?: string) => ({
  text: `<task-notification><task-id>${taskId}</task-id>${status === undefined ? '' : `<status>${status}</status>`}</task-notification>`,
  origin: { kind: 'task-notification' },
})

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
  return mock.clock(on)
}

const BENCH = { tool: 'Bash', command: 'cargo bench --release', description: 'Run the bench', run_in_background: true } as const

test('keys, labels and progress', () => {
  expect(estimateKey('shell', { command: 'cd /x && cargo bench --release -p core' })).toBe('bash:cargo bench')
  expect(estimateKey('monitor', { description: ' Watch CI ' })).toBe('monitor:watch ci')
  expect(waitLabel('shell', { command: 'cargo bench\nmore' })).toBe('cargo bench')
  expect(waitLabel('shell', { command: 'x', description: 'Run the bench' })).toBe('Run the bench')
  expect(approx(180_000)).toBe('~3m')
  expect(approx(40_000)).toBe('~40s')
  expect(progressOf(90_000, 180_000)).toBe(0.5)
  expect(progressOf(400_000, 180_000)).toBe(0.95)
  expect(progressOf(5000, undefined)).toBeUndefined()
  expect(glyphLine(0.5, 10)).toBe('▰▰▰▰▰▱▱▱▱▱')
  expect(progressSvg(undefined, 100, '#d97757')).not.toContain('class="done"')
  expect(progressSvg(0.5, 100, '#d97757')).toContain('width="50.00"')
})

test('the card shows once the turn ends, counts up, and goes with the work', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = engine(on, saved)
  for (const surface of ['terminal', 'desktop'] as const) {
    // Each surface starts with no sample: the first run's duration would otherwise give the second an estimate.
    delete saved['wait-durations:bash:cargo bench']
    await $.turn.start({ text: 'go', turnId: 't1' })
    await $.tool.call(BENCH)
    // The turn still runs: nothing waits yet.
    let ui = await $.ui.mount({ ...BAND, surface })
    expect(await ui.find({ type: 'Text', text: /Esperando/ })).toBeUndefined()
    await ui.unmount()

    await $.turn.complete(done)
    await clock.advance(72_000)
    ui = await $.ui.mount({ ...BAND, surface })
    expect(await ui.find({ type: 'Text', text: /Esperando/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Run the bench/ })).toBeDefined()
    // No sample yet: elapsed only.
    expect((await ui.find({ type: 'Text', text: /1m 12s/ }))?.text).toBe('1m 12s')
    expect(await ui.find({ type: 'Text', text: /bash · en segundo plano/ })).toBeDefined()
    // The clock moves the card.
    await clock.advance(3000)
    expect(await ui.find({ type: 'Text', text: /1m 15s/ })).toBeDefined()
    await ui.unmount()

    // The work ends: the notification clears the card.
    await $.prompt.submit(notice('b1', 'completed') as never)
    ui = await $.ui.mount({ ...BAND, surface })
    expect(await ui.find({ type: 'Text', text: /Esperando/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('a recorded sample gives the estimate and the progress', async ($, on) => {
  const saved: Record<string, unknown> = { 'wait-durations:bash:cargo bench': [100_000, 180_000, 240_000] }
  const clock = engine(on, saved)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(90_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /1m 30s/ }))?.text).toBe('1m 30s / ~3m')
  expect((await ui.find({ type: 'Svg' }))?.props?.source).toContain('width="2000.00"')
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
  await ui.unmount()

  // An event line wakes the model: new turn, no card; it ends, the card is back.
  await $.prompt.submit(notice('m1') as never)
  await $.turn.start({ text: '', turnId: 't2' })
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Esperando/ })).toBeUndefined()
  await ui.unmount()
  await $.turn.complete({ ...done, turnId: 't2' })
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Watch CI/ })).toBeDefined()
  await ui.unmount()

  await clock.advance(10_000)
  await $.prompt.submit(notice('m1', 'killed') as never)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Esperando/ })).toBeUndefined()
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
  expect(await ui.find({ type: 'Text', text: /Review the diff/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /agente · en segundo plano/ })).toBeDefined()
  await ui.unmount()

  await $.turn.complete({ ...done, agentId: 'a1', turnId: 's1' })
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Esperando/ })).toBeUndefined()
  await ui.unmount()
})
