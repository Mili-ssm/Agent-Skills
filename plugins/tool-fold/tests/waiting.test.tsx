import { expect, mock, test } from 'claude-code/testing'

import { formatRemaining, remainingOf } from '../hooks/agents'
import { SIMILARITY_MIN, similarity, statedDuration } from '../hooks/estimates'
import { agentDots, formatContext } from '../hooks/cycle'
import { cleanPhrase, estimateKey, minutesOf, progressOf, waitLabel } from '../hooks/waiting'

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

const SPAWN_FG = {
  tool_use_id: 'tu1',
  prompt: 'Find where sessions are created',
  description: 'Find session creation',
  subagentType: 'Explore',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'claude-opus-5-5',
  background: false,
  fork: false,
} as never

const done = { reason: 'answer', answer: '', durationMs: 1000, isAborted: false, turnId: 't1' } as const

/** The engine beneath the mod: a background Bash answers a task id, the store is a map. */
function engine(on: Parameters<Parameters<typeof test>[1]>[1], saved: Record<string, unknown> = {}, bashExtra: Record<string, unknown> = {}) {
  on('store.get', (_, e) => ({ value: saved[e.key] }))
  on('store.set', (_, e) => {
    saved[e.key] = e.value
    return { value: undefined }
  })
  on('tool.call', (_, e) => ({
    result: e.tool === 'Bash' ? { stdout: '', stderr: '', interrupted: false, backgroundTaskId: String((e as { command?: unknown }).command).includes('sleep 600') ? 'b2' : 'b1', ...bashExtra } : { taskId: 'm1', timeoutMs: 0 },
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
  expect(estimateKey('shell', { command: 'cd /x && cargo bench --release -p core' })).toBe('bash:cargo bench --release -p core')
  expect(estimateKey('shell', { command: "cat > $S <<'EOF'\nbody", description: 'Write the script' })).toBe('bash:write the script')
  expect(estimateKey('shell', { command: "cat  > $S <<'EOF'\nbody" })).toBe("bash:cat > $s <<'eof'")
  expect(minutesOf('3,5')).toBe(210_000)
  expect(minutesOf('muchos')).toBeUndefined()
  expect(cleanPhrase('"Ejecuta los tests."\nextra')).toBe('Ejecuta los tests')
  expect(estimateKey('monitor', { description: ' Watch CI ' })).toBe('monitor:watch ci')
  expect(waitLabel('shell', { command: 'cargo bench\nmore' })).toBe('cargo bench')
  expect(waitLabel('shell', { command: 'x', description: 'Run the bench' })).toBe('Run the bench')
  expect(progressOf(90_000, 180_000)).toBe(0.5)
  expect(progressOf(400_000, 180_000)).toBe(0.99)
  expect(progressOf(5000, undefined)).toBeUndefined()
})

test('the main agent card shows once the turn ends, counts up, and goes with the work', async ($, on) => {
  const clock = engine(on)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  // The turn still runs, but the wait is open: the card shows, labelled as background work.
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · en segundo plano/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeUndefined()
  await ui.unmount()

  await $.turn.complete(done)
  await clock.advance(72_000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /opus-5-5/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Run the bench/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /bash · en segundo plano/ })).toBeDefined()
  expect(await ui.findAll({ type: 'Text', text: /Run the bench/ })).toHaveLength(1)
  // No sample yet: the elapsed time sits by the model, no percentage on the right.
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('opus-5-5 · 1m 12s')
  expect(await ui.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  await ui.unmount()
  // VS Code (the surface some app panels report) carries the main agent's card in its band too.
  ui = await $.ui.mount({ ...BAND, surface: 'vscode' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  // The clock moves the card.
  await clock.advance(3000)
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('opus-5-5 · 1m 15s')
  await ui.unmount()

  // The pane lists it as it lists any running agent.
  const pane = await $.ui.mount(PANE as never)
  expect(await pane.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /Run the bench/ })).toBeDefined()
  await pane.unmount()

  // The work ends: the notification clears the card.
  await $.prompt.submit(notice('b1', 'completed') as never)
  // The wait is gone and the cycle is idle: the card stays as the done one, green, until the next prompt.
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /^◆$/ }))?.props.color).toBe('success')
  await ui.unmount()
  await clock.advance(60_000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await ui.unmount()
})

test('a recorded sample gives the estimate and the progress', async ($, on) => {
  const saved: Record<string, unknown> = { 'wait-samples': [100_000, 180_000, 240_000].map(durationMs => ({ summary: 'Run the bench', durationMs, at: 1 })) }
  const clock = engine(on, saved)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(90_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('opus-5-5 · 1m 30s')
  await ui.unmount()

  // It finishes after 4 minutes: the duration joins the samples.
  await clock.advance(150_000)
  await $.prompt.submit(notice('b1', 'completed') as never)
  expect((saved['wait-samples'] as { durationMs: number }[]).map(item => item.durationMs)).toEqual([100_000, 180_000, 240_000, 240_000])
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
  const clock = engine(on, { 'wait-durations:agent:Explore': [100_000, 180_000, 240_000] })
  on('agent.spawn', (_, e) => ({ model: 'claude-haiku-5-5', agentId: e.tool_use_id === 'tu2' ? 'a2' : 'a1' }))
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
  expect(await ui.find({ type: 'Text', text: /esperando a Explore/ })).toBeDefined()
  // Even with a history, the wait on an agent has no right datum: the agent's own card carries it.
  expect(await ui.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  await ui.unmount()

  // A second agent: the detail counts them instead of naming one.
  await $.agent.spawn({
    tool_use_id: 'tu2',
    prompt: 'More',
    description: 'Other',
    subagentType: 'Plan',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: true,
    fork: false,
  } as never)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando a 2 agentes/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /esperando a Explore/ })).toBeUndefined()
  await ui.unmount()
  await $.turn.complete({ ...done, agentId: 'a2', turnId: 's2' })

  await $.turn.complete({ ...done, agentId: 'a1', turnId: 's1' })
  await clock.advance(5000)
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
  expect(remainingOf(120_000, 5)).toBe('~38 min')
  expect(remainingOf(120_000, 3)).toBe('?1 h 5 min')
  expect(remainingOf(120_000, 0.5)).toBeUndefined()
  expect(remainingOf(120_000, undefined)).toBeUndefined()
})

test('the main agent card comes first, stands out, and shows the time left', async ($, on) => {
  const saved: Record<string, unknown> = { 'wait-samples': [{ summary: 'Run the bench', durationMs: 180_000, at: 1 }] }
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
    expect(name?.props.weight).toBe('bold')
    expect(name?.text).toBe('Claude · esperando')
    expect((await ui.find({ type: 'Text', text: /^◆$/ }))?.props.color).toBe('#6ba3e6')
    // 50% at 90 s: 90 s left.
    expect(await ui.find({ type: 'Text', text: /≈50% · ~2 min/ })).toBeDefined()
    // The wait is blue, its thin line too.
    expect(String((await ui.find({ type: 'Svg' }))?.props.source)).toContain('#4f8fd8')
    await ui.unmount()
  }
})

/** A model.complete stub answering `text`, recording the prompts. */
const haiku = (on: Parameters<Parameters<typeof test>[1]>[1], text: string, prompts: string[] = [], reestimates = true) =>
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    // The cycle's own phrase calls (what Claude does now, the conclusion) are not the estimate calls these tests answer and count.
    if (prompt.includes('<latest_actions>') || prompt.includes('<answer>')) {
      return { value: { isAnswered: false, text: '', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
    }
    prompts.push(prompt)
    if (!reestimates && prompt.includes('<estimacion_anterior>')) {
      return { value: { isAnswered: false, text: '', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
    }
    return { value: { isAnswered: true, text, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })

const RAW = { tool: 'Bash', command: "cat > $S <<'EOF'\nbody\nEOF", run_in_background: true } as const

test('with a description Haiku writes no label; a guessed estimate draws the line and time left', async ($, on) => {
  const clock = engine(on)
  const prompts: string[] = []
  haiku(on, 'minutos: 4', prompts)
  await $.turn.start({ text: '', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(120_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(prompts).toHaveLength(1)
  expect(prompts[0]).not.toContain('descripcion:')
  expect(await ui.find({ type: 'Text', text: /Run the bench/ })).toBeDefined()
  // 2 of 4 minutes: 50%, 2 min left.
  expect(await ui.find({ type: 'Text', text: /≈50% · ~2 min/ })).toBeDefined()
  expect(await ui.find({ type: 'Svg' })).toBeDefined()
  await ui.unmount()
})

test('without a description Haiku names the wait and, in its own call, estimates its duration', async ($, on) => {
  const clock = engine(on)
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    const text = prompt.includes('<tareas_parecidas>') ? 'minutos: 10' : 'descripcion: Escribe el script de prueba'
    return { value: { isAnswered: true, text, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(RAW)
  await $.turn.complete(done)
  await clock.advance(300_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Escribe el script de prueba/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  await ui.unmount()
})

test('a recorded median wins over the guess', async ($, on) => {
  const clock = engine(on, { 'wait-samples': [{ summary: 'Run the bench', durationMs: 180_000, at: 1 }] })
  haiku(on, '60')
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(90_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈50% · ~2 min/ })).toBeDefined()
  await ui.unmount()
})

test('past the estimate the card says so', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'minutos: 1', [], false)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(150_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈99% · más de lo previsto/ })).toBeDefined()
  await ui.unmount()
})

test('within 15 s of the estimate the card is not overdue; past it is', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'minutos: 1', [], false)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(70_000)
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈99% · <1 min/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /más de lo previsto/ })).toBeUndefined()
  await ui.unmount()
  await clock.advance(6_000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈99% · más de lo previsto/ })).toBeDefined()
  await ui.unmount()
})

test('with no estimate at all only the empty track is drawn', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'no idea')
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(5000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  expect(await ui.find({ type: 'Svg' })).toBeDefined()
  await ui.unmount()
})

const sample = (summary: string, durationMs: number) => ({ summary, durationMs, at: 1 })
const withAnswer = (answer: string) => ({ ...done, answer })

test('similarity is word overlap', () => {
  expect(SIMILARITY_MIN).toBe(0.5)
  expect(similarity('Run the cargo bench release', 'Run cargo bench release now')).toBeGreaterThanOrEqual(SIMILARITY_MIN)
  expect(similarity('Run the bench', 'Fetch the logs from CI')).toBeLessThan(SIMILARITY_MIN)
})

test('similar past runs give the estimate and the ⟲ icon; unrelated ones are ignored', async ($, on) => {
  const clock = engine(on, {
    'wait-samples': [sample('Compile the viewer crate in release', 600_000), sample('Run the cargo bench release', 180_000), sample('Run the cargo bench release core', 120_000)],
  })
  const prompts: string[] = []
  haiku(on, 'none', prompts)
  await $.turn.start({ text: '', turnId: 't1' })
  await $.tool.call({ ...BENCH, description: 'Run cargo bench release' })
  await $.turn.complete(done)
  await clock.advance(75_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  // Median of 180 s and 120 s is 150 s: 75 s is 50%.
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^⟲$/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /^⟲$/ }))?.props.dimColor).toBe(true)
  // Similar runs found: no pick call, and the guess asks no minutes.
  expect(prompts.every(prompt => !prompt.includes('<anteriores>'))).toBe(true)
  await ui.unmount()
})

test('Haiku gets the text and the similar runs (top five, most similar first) in one call, and its minutes win', async ($, on) => {
  const clock = engine(on, {
    'wait-samples': [
      sample('Deploy the docs site', 900_000),
      sample('Run the bench', 180_000),
      sample('Run the bench on core', 120_000),
      sample('Run the bench on core again', 100_000),
      sample('Bench run one', 100_000),
      sample('Bench run two', 100_000),
      sample('Bench run three', 100_000),
    ],
  })
  const prompts: string[] = []
  haiku(on, 'minutos: 2', prompts)
  await $.turn.start({ text: '', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(60_000)
  expect(prompts).toHaveLength(1)
  expect(prompts[0]).toContain('Run the bench')
  expect(prompts[0]).toContain('cargo bench --release')
  const listed = prompts[0]?.split('\n').filter(line => /^\d\. /.test(line)) ?? []
  expect(listed).toHaveLength(5)
  expect(listed[0]).toBe('1. Run the bench — 3 min')
  expect(prompts[0]).not.toContain('Deploy the docs site')
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  // Haiku's 2 minutes replace the 3 of the similar run: 60 s is 50%.
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^⟲$/ })).toBeDefined()
  await ui.unmount()
})

test('with a stated duration Haiku sees it and its answer shows ✦; without similar runs the prompt says none', async ($, on) => {
  const clock = engine(on)
  const prompts: string[] = []
  haiku(on, 'minutos: 6', prompts)
  await $.turn.start({ text: '', turnId: 't1' })
  await $.tool.call({ tool: 'Bash', command: 'sleep 300', description: 'Wait for the deploy', run_in_background: true } as never)
  await $.turn.complete(done)
  await clock.advance(1000)
  expect(prompts[0]).toContain('<duracion_indicada>5 min</duracion_indicada>')
  expect(prompts[0]).toContain('<tareas_parecidas>none</tareas_parecidas>')
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /^✦$/ })).toBeDefined()
  await ui.unmount()
})

test('past the estimate Haiku is asked again with the elapsed time, throttled to 30 s, and must answer more than elapsed', async ($, on) => {
  const clock = engine(on)
  const prompts: string[] = []
  let answer = 'minutos: 1'
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    // The cycle's own phrase calls (what Claude does now, the conclusion) are not the estimate calls these tests count.
    if (!prompt.includes('<latest_actions>') && !prompt.includes('<answer>')) {
      prompts.push(prompt)
    }
    return { value: { isAnswered: true, text: answer, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  const reasks = () => prompts.filter(prompt => prompt.includes('<estimacion_anterior>'))
  await clock.advance(70_000)
  expect(reasks()).toHaveLength(0)
  // Overdue at 60 s plus the 15 s grace: asked at the first tick past it; 1 min is below elapsed, so the total becomes max(1, 75 x 1.25, 75 s + 2 min) = 195 s.
  answer = 'minutos: 1'
  await clock.advance(6000)
  expect(reasks()).toHaveLength(1)
  expect(reasks()[0]).toContain('<ya_transcurrido>1.3 min</ya_transcurrido>')
  expect(reasks()[0]).toContain('<estimacion_anterior>1 min</estimacion_anterior>')
  await clock.advance(1000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /más de lo previsto/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /≈\d+%/ })).toBeDefined()
  await ui.unmount()
  // No more asks while it is within the new estimate (195 s + 15 s).
  await clock.advance(100_000)
  expect(reasks()).toHaveLength(1)
  // Overdue again: asked again, at most every 30 s.
  answer = 'minutos: 10'
  await clock.advance(40_000)
  expect(reasks()).toHaveLength(2)
  const { text } = await $.command.run({ command: 'agents-debug' } as never)
  expect(text).toContain('re-estimates')
  expect(text).toContain('old=1 min new=3.3 min')
})

test('waiting card: icon, datum and line share the blue hex; two owned processes: the latest-ending one gives the estimate; an overdue owned wait is re-estimated past the grace', async ($, on) => {
  const clock = engine(on)
  const prompts: string[] = []
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    if (prompt.includes('<latest_actions>') || prompt.includes('<answer>')) {
      return { value: { isAnswered: false, text: '', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
    }
    prompts.push(prompt)
    return { value: { isAnswered: true, text: prompt.includes('sleep 600') ? 'minutos: 10' : 'minutos: 1', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({ description: 'Run checks', prompt: 'p', subagentType: 'agent-skills:check-runner', background: false } as never)
  await $.tool.call({ tool: 'Bash', command: 'sleep 60', description: 'short', run_in_background: true, agentId: 'a1' } as never)
  await $.tool.call({ tool: 'Bash', command: 'sleep 600', description: 'long', run_in_background: true, agentId: 'a1' } as never)
  await $.turn.complete({ ...done, agentId: 'a1' })
  await clock.advance(30_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando · 2 procesos/ })).toBeDefined()
  // The 600 s process ends last: 30 s of 600 s is 5%, not the short one's 50%.
  const datum = await ui.find({ type: 'Text', text: /≈5%/ })
  expect(datum).toBeDefined()
  expect(datum?.props.color).toBe('#6ba3e6')
  expect((await ui.find({ type: 'Text', text: /^◷$/ }))?.props.color).toBe('#6ba3e6')
  expect((await ui.findAll({ type: 'Svg' })).some(svg => String(svg.props.source).includes('#4f8fd8'))).toBe(true)
  await ui.unmount()
  // The short wait is overdue at 60 s; the first ask comes at the first tick past the 15 s grace.
  const reasks = () => prompts.filter(prompt => prompt.includes('<estimacion_anterior>'))
  await clock.advance(44_000)
  expect(reasks()).toHaveLength(0)
  await clock.advance(2000)
  expect(reasks().length).toBeGreaterThan(0)
})

test('a Haiku guess shows the ? icon', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'minutos: 4')
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(120_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /^\?$/ })).toBeDefined()
  await ui.unmount()
})

test("Claude's own estimate from its message overrides similar runs and shows ✦", async ($, on) => {
  const clock = engine(on, { 'wait-samples': [sample('Run the bench', 180_000)] })
  const prompts: string[] = []
  haiku(on, '150', prompts)
  await $.turn.start({ text: '', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(withAnswer('Lanzado. Calculo unas 2–3 horas.'))
  await clock.advance(75 * 60_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(prompts.some(prompt => prompt.includes('Calculo unas 2–3 horas'))).toBe(true)
  // 75 of 150 minutes.
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^✦$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^⟲$/ })).toBeUndefined()
  await ui.unmount()
})

test('a message with no duration leaves the other estimates alone', async ($, on) => {
  const clock = engine(on, { 'wait-samples': [sample('Run the bench', 180_000)] })
  haiku(on, 'none')
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(withAnswer('Lanzado, espero.'))
  await clock.advance(90_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^⟲$/ })).toBeDefined()
  await ui.unmount()
})

test('minutesOf reads only a bare number; prose gives none', () => {
  expect(minutesOf('150')).toBe(9_000_000)
  expect(minutesOf('3 of 5 → 40')).toBeUndefined()
  expect(minutesOf('none')).toBeUndefined()
})

test('cleanPhrase drops thinking aloud and long replies', () => {
  expect(cleanPhrase('Wait, the instruction says to reply')).toBe('')
  expect(cleanPhrase('Hmm, let me think')).toBe('')
  expect(cleanPhrase(Array(30).fill('a').join(' '))).toBe('')
  expect(cleanPhrase('"Compila el proyecto."\nextra')).toBe('Compila el proyecto')
})

test('a message ETA "unas 2–3 horas" answered 150 sets 150 minutes; prose sets nothing', async () => {
  expect(minutesOf('150')).toBe(150 * 60000)
  expect(minutesOf('unas 2–3 horas')).toBeUndefined()
})

const SPAWN = { description: 'Run checks', prompt: 'p', subagentType: 'agent-skills:check-runner', background: true } as never

test('several waits make one main card; the process with the latest end gives the estimate; prefix stripped', async ($, on) => {
  const saved: Record<string, unknown> = { 'wait-samples': [100_000, 180_000, 240_000].map(durationMs => ({ summary: 'Run the bench', durationMs, at: 1 })) }
  const clock = engine(on, saved)
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn(SPAWN)
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(90_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.findAll({ type: 'Text', text: /Claude · esperando/ })).toHaveLength(1)
  expect(await ui.find({ type: 'Text', text: /esperando a check-runner · bash en segundo plano/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /agent-skills:/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  await ui.unmount()
})

test('the band draws no wait card where the Agentes pane is placed; Desktop keeps it', async ($, on) => {
  const clock = engine(on)
  on('ui.panes', () => ({ value: [{ id: 'agents', title: 'Agentes · 1', isShown: true, hasFocus: false, isPlaced: true }] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(1000)
  const vscode = await $.ui.mount({ ...BAND, surface: 'vscode' })
  expect(await vscode.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await vscode.unmount()
  const desktop = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await desktop.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  await desktop.unmount()
})

test('the pane title is fixed: the count sits on the Agentes line', async ($, on) => {
  const clock = engine(on)
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  const titles: string[] = []
  on('ui.open', (_, e) => {
    titles.push(e.title)
    return { value: { isPlaced: true } }
  })
  on('session.surfaces', () => ({ value: ['terminal'] }) as never)
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn(SPAWN)
  await $.turn.complete(done)
  await clock.advance(1000)
  // A fixed title never retitles (that blinked); the count is drawn on the divider.
  expect(new Set(titles)).toEqual(new Set(['Agentes']))
})

test('a subagent that ends its turn with a background process keeps its card, waiting, until the process ends', async ($, on) => {
  const clock = engine(on)
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({ description: 'Run checks', prompt: 'p', subagentType: 'agent-skills:check-runner', background: false } as never)
  await $.tool.call({ tool: 'Bash', command: 'sleep 240', description: 'sleep 240', run_in_background: true, agentId: 'a1' } as never)
  await $.turn.complete({ ...done, agentId: 'a1' })
  await clock.advance(5000)
  // The main turn still runs and the main agent waits on nothing: only the subagent's card shows.
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /^check-runner$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /esperando · sleep 240 en segundo plano/ })).toBeDefined()
  // Waiting on its process, the card swaps the runner's icon for the sleep icon.
  expect(await ui.find({ type: 'Text', text: /^◷$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^▶$/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeUndefined()
  await ui.unmount()
  // The main agent has no wait of its own.
  const { text } = await $.command.run({ command: 'agents-debug' } as never)
  expect(text).toContain('waits: shell b1')
  await $.prompt.submit(notice('b1', 'completed') as never)
  const after = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await after.find({ type: 'Text', text: /esperando/ })).toBeUndefined()
  await after.unmount()
})

test('statedDuration reads durations written in a command or description', () => {
  expect(statedDuration('sleep 290 && echo done-290')).toBe(290_000)
  expect(statedDuration('sleep 5m')).toBe(300_000)
  expect(statedDuration('Pedirle que espera 180 segundos')).toBe(180_000)
  expect(statedDuration('Sleep 290 seconds then echo done-290')).toBe(290_000)
  expect(statedDuration('Wait 5 minutes in background')).toBe(300_000)
  expect(statedDuration('unas 2–3 horas')).toBe(9_000_000)
  expect(statedDuration('Run the bench')).toBeUndefined()
  expect(statedDuration('build v2.5 of the crate')).toBeUndefined()
})

test('a stated duration beats similar runs and shows ✦', async ($, on) => {
  const clock = engine(on, { 'wait-samples': [sample('Wait 5 minutes in background', 2000)] })
  haiku(on, 'none')
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call({ tool: 'Bash', command: 'sleep 300', description: 'Wait 5 minutes in background', run_in_background: true } as never)
  await $.turn.complete(done)
  await clock.advance(150_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^✦$/ })).toBeDefined()
  // The label stays in the mission; the detail does not repeat it.
  expect(await ui.findAll({ type: 'Text', text: /Wait 5 minutes in background/ })).toHaveLength(1)
  await ui.unmount()
})

test('a subagent waiting on sleep 240 shows elapsed over 240 s with ✦, not overdue at 18 s', async ($, on) => {
  const clock = engine(on, { 'wait-samples': [sample('sleep 240', 2000)], 'agent-samples': [sample('agent-skills:check-runner: Run checks', 3000)] })
  haiku(on, 'none')
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({ description: 'Run checks', prompt: 'p', subagentType: 'agent-skills:check-runner', background: false } as never)
  await $.tool.call({ tool: 'Bash', command: 'sleep 240', description: 'sleep 240', run_in_background: true, agentId: 'a1' } as never)
  await $.turn.complete({ ...done, agentId: 'a1' })
  await clock.advance(18_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈8%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^✦$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /más de lo previsto/ })).toBeUndefined()
  await ui.unmount()
})

test('an agent that ends its turn with open waits is not recorded as a sample', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = engine(on, saved)
  haiku(on, 'none')
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({ description: 'Run checks', prompt: 'p', subagentType: 'agent-skills:check-runner', background: false } as never)
  await $.tool.call({ tool: 'Bash', command: 'sleep 240', run_in_background: true, agentId: 'a1' } as never)
  await clock.advance(18_000)
  await $.turn.complete({ ...done, agentId: 'a1', durationMs: 18_000 })
  expect(saved['agent-samples']).toBeUndefined()
})

/** A subagent a1 that launched `sleep 240` (shell b1) and ended its turn; the main loop runs turn t1. */
async function ownedWait($: Parameters<Parameters<typeof test>[1]>[0], on: Parameters<Parameters<typeof test>[1]>[1], saved: Record<string, unknown>, bashExtra: Record<string, unknown> = {}) {
  const clock = engine(on, saved, bashExtra)
  haiku(on, 'none')
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({ description: 'Run checks', prompt: 'p', subagentType: 'agent-skills:check-runner', background: false } as never)
  await $.tool.call({ tool: 'Bash', command: 'sleep 240', description: 'sleep 240', run_in_background: true, agentId: 'a1' } as never)
  await $.turn.complete({ ...done, agentId: 'a1', turnId: 's1' })
  return clock
}
const waitsOf = async ($: Parameters<Parameters<typeof test>[1]>[0]) => ((await $.command.run({ command: 'agents-debug' } as never)).text.split('\n').find(line => line.startsWith('waits:')) ?? '')

test("a subagent woken by its command's end (backgroundWakesOwner) ends that wait and records the sample", async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = await ownedWait($, on, saved, { backgroundWakesOwner: true })
  await clock.advance(240_000)
  expect(await waitsOf($)).toBe('waits: shell b1')
  // The wake-up turn of the subagent carries the notification.
  await $.turn.start({ text: notice('b1', 'completed').text, turnId: 's2', agentId: 'a1' })
  expect(await waitsOf($)).toBe('waits: none')
  expect((saved['wait-samples'] as { durationMs: number }[]).map(item => item.durationMs)).toEqual([240_000])
})

test('a woken subagent whose message names another task keeps the wait', async ($, on) => {
  const clock = await ownedWait($, on, {}, { backgroundWakesOwner: true })
  await clock.advance(10_000)
  await $.turn.start({ text: notice('zzz', 'completed').text, turnId: 's2', agentId: 'a1' })
  expect(await waitsOf($)).toBe('waits: shell b1')
})

test('a subagent command that ends with its final response makes no wait', async ($, on) => {
  await ownedWait($, on, {}, { backgroundEndsWithFinalResponse: true })
  expect(await waitsOf($)).toBe('waits: none')
})

test('safety net a: the main loop notification naming an ended agent\'s wait drops it with no sample', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = await ownedWait($, on, saved)
  await clock.advance(240_000)
  await $.prompt.submit(notice('b1', 'completed') as never)
  expect(await waitsOf($)).toBe('waits: none')
  expect(saved['wait-samples']).toBeUndefined()
})

test('safety net b: an ended agent\'s wait past max(2 x estimate, estimate + 10 min) is dropped with no sample', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = await ownedWait($, on, saved)
  // sleep 240 states 4 min: the limit is 14 min.
  await clock.advance(13 * 60_000)
  expect(await waitsOf($)).toBe('waits: shell b1')
  await clock.advance(2 * 60_000)
  expect(await waitsOf($)).toBe('waits: none')
  expect(saved['wait-samples']).toBeUndefined()
})


test('the main card is drawn first in its own group, then a divider, then the agents, in the pane and the band', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'none')
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn(SPAWN_FG)
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(5000)
  for (const surface of ['pane', 'desktop'] as const) {
    const ui = surface === 'pane' ? await $.ui.mount(PANE as never) : await $.ui.mount({ ...BAND, surface: 'desktop' })
    const texts = (await ui.findAll({ type: 'Text' })).map(item => item.text)
    const main = texts.findIndex(text => /Claude · esperando/.test(text))
    const divider = texts.findIndex(text => /^── Agentes \d+ ─+$/.test(text))
    const agent = texts.findIndex(text => /^Explore$/.test(text))
    expect(main).toBeGreaterThanOrEqual(0)
    expect(divider).toBeGreaterThan(main)
    expect(agent).toBeGreaterThan(divider)
    await ui.unmount()
  }
  // The work ends: only the agent shows, under the Agentes line with its count.
  await $.prompt.submit(notice('b1', 'completed') as never)
  const alone = await $.ui.mount(PANE as never)
  expect((await alone.find({ type: 'Text', text: /── Agentes/ }))?.text).toMatch(/^── Agentes 1 ─+$/)
  expect(await alone.find({ type: 'Text', text: /^Explore$/ })).toBeDefined()
  await alone.unmount()
})

test('the main card persists across a main turn start: only the label switches', async ($, on) => {
  const clock = engine(on)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(5000)
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  await ui.unmount()
  await $.turn.start({ text: 'wake', turnId: 't2' })
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /Claude · en segundo plano/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Run the bench/ })).toBeDefined()
  await ui.unmount()
  // The clock keeps running through the turn.
  await clock.advance(3000)
  await $.turn.complete({ ...done, turnId: 't2' })
  await $.prompt.submit(notice('b1', 'completed') as never)
  await clock.advance(5000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · (esperando|en segundo plano)/ })).toBeUndefined()
  await ui.unmount()
})

/** A background agent a1 (check-runner) spawned by the main loop; the engine lists it with `status`. */
async function backgroundAgent($: Parameters<Parameters<typeof test>[1]>[0], on: Parameters<Parameters<typeof test>[1]>[1], status: () => string, bashExtra: Record<string, unknown> = {}) {
  const clock = engine(on, {}, bashExtra)
  haiku(on, 'none')
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('agent.list', () => ({ value: [{ id: 'a1', description: 'Run checks', type: 'agent-skills:check-runner', status: status() }] }) as never)
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn(SPAWN)
  await $.tool.call({ tool: 'Agent', description: 'Run checks', run_in_background: true } as never)
  await $.turn.complete(done)
  return clock
}
const runsLine = async ($: Parameters<Parameters<typeof test>[1]>[0]) => (await $.command.run({ command: 'agents-debug' } as never)).text.split('\n').filter(line => /^runs:|^  run /.test(line))

test('a background agent stays running after its Agent call returns and while parked; it ends at its last turn', async ($, on) => {
  let status = 'waiting'
  const clock = await backgroundAgent($, on, () => status, { backgroundWakesOwner: true, backgroundEndsWithFinalResponse: true })
  await $.tool.call({ tool: 'Bash', command: 'sleep 150', description: 'sleep 150', run_in_background: true, agentId: 'a1' } as never)
  // Its Bash answered "ends with final response", yet it is the background agent's own wait.
  expect(await waitsOf($)).toBe('waits: agent a1; shell b1')
  expect(await runsLine($)).toEqual(['runs: 1 running of 1', '  run a1 running background=true agent-skills:check-runner'])
  // Its turn ends while it is parked on its command: still running, its waits kept.
  await $.turn.complete({ ...done, agentId: 'a1', turnId: 's1' })
  expect(await runsLine($)).toEqual(['runs: 1 running of 1', '  run a1 running background=true agent-skills:check-runner'])
  expect(await waitsOf($)).toBe('waits: agent a1; shell b1')
  // The main card counts the agent and the agent's card shows its process estimate.
  await clock.advance(30_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /esperando a check-runner/ })).toBeDefined()
  await ui.unmount()
  // Woken by the command's end, then its last turn completes.
  await $.turn.start({ text: notice('b1', 'completed').text, turnId: 's2', agentId: 'a1' })
  status = 'completed'
  await $.turn.complete({ ...done, agentId: 'a1', turnId: 's2' })
  expect(await runsLine($)).toEqual(['runs: 0 running of 1', '  run a1 done background=true agent-skills:check-runner'])
  expect(await waitsOf($)).toBe('waits: none')
})

test('a woken background agent keeps its spawn time: the orange card counts the whole task, not the wake turn', async ($, on) => {
  const status = 'completed'
  const clock = engine(on, {}, { backgroundWakesOwner: true, backgroundEndsWithFinalResponse: true })
  haiku(on, 'none')
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('agent.list', () => ({ value: [{ id: 'a1', description: 'Run checks', type: 'agent-skills:check-runner', status }] }) as never)
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({ description: 'Run checks', prompt: 'sleep 3 minutes then report', subagentType: 'agent-skills:check-runner', background: true } as never)
  await $.tool.call({ tool: 'Agent', description: 'Run checks', run_in_background: true } as never)
  await $.turn.complete(done)
  await $.tool.call({ tool: 'Bash', command: 'sleep 180', description: 'sleep 180', run_in_background: true, agentId: 'a1' } as never)
  await $.turn.complete({ ...done, agentId: 'a1', turnId: 's1' })
  await clock.advance(180_000)
  await $.turn.start({ text: notice('b1', 'completed').text, turnId: 's2', agentId: 'a1' })
  await clock.advance(4_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const texts = (await ui.findAll({ type: 'Text' })).map(item => item.text)
  await ui.unmount()
  expect(texts.some(text => /\b3m/.test(text) || /3 min/.test(text))).toBe(true)
  const percent = texts.map(text => /≈(\d+)%/.exec(text)?.[1]).find(value => value !== undefined)
  expect(Number(percent)).toBeGreaterThanOrEqual(90)
})

test('the main card while a turn runs: orange with no estimate, blue with background work; done it stays grey until the next prompt', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = engine(on, saved)
  const prompts: string[] = []
  haiku(on, 'minutos: 2', prompts)
  await $.turn.start({ text: 'Refactor the parser module', turnId: 't1' })
  expect(prompts).toHaveLength(0)
  await clock.advance(60_000)
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const name = await ui.find({ type: 'Text', text: /Claude · trabajando/ })
  expect(name).toBeDefined()
  // No time inference: no percentage, orange, with the prompt as detail until a call arrives.
  expect(await ui.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /^◆$/ }))?.props.color).toBe('#d8836a')
  expect(await ui.find({ type: 'Text', text: /Refactor the parser module/ })).toBeDefined()
  await ui.unmount()
  // The latest call becomes the detail until Haiku says something.
  await $.tool.call({ tool: 'Read', file_path: '/src/lexer.ts' } as never)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /lexer\.ts/ })).toBeDefined()
  await ui.unmount()
  // The turn ends with nothing in the background: once Claude is idle the card turns green and stays.
  await clock.advance(30_000)
  await $.turn.complete({ ...done, turnId: 't1' })
  await clock.advance(2000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^✓$/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /^◆$/ }))?.props.color).toBe('success')
  await ui.unmount()
  expect(saved['turn-samples']).toBeUndefined()
  await clock.advance(600_000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeDefined()
  // The header time stopped when Claude went idle.
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('opus-5-5 · 1m 30s')
  await ui.unmount()
  // The owner's next prompt starts a new cycle: working again, from zero.
  await $.prompt.submit({ text: 'Now the lexer', wait: false, origin: { kind: 'composer' } } as never)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /Claude · trabajando/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('opus-5-5 · 0s')
  await ui.unmount()
})

const USAGE = (model: string, input: number) => ({ model, input_tokens: input, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 })

test('the header time spans the whole request: across the turn and the wait', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'minutos: 10')
  await $.prompt.submit({ text: 'Run the benchmarks', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'Run the benchmarks', turnId: 't1' })
  await clock.advance(60_000)
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(192_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  // 60 s working + 192 s waiting since the prompt, not the wait's own 192 s.
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('opus-5-5 · 4m 12s')
  await ui.unmount()
})

test('the stats line: context first with icon and color, calls, skills, cycle agents with model dots, session; Haiku\'s phrase is the activity', async ($, on) => {
  const clock = engine(on)
  on('session.usage', () => ({ value: { startedAt: 0, rateLimits: [], context: { window: 200000, tokens: 26000, percent: 13 } } }) as never)
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    const text = prompt.includes('<latest_actions>') ? 'Revisa los hooks del plugin' : prompt.includes('<answer>') ? 'Todo listo y probado' : 'none'
    return { value: { isAnswered: true, text, usage: USAGE('claude-haiku-5-5', 10) } } as never
  })
  const models = ['claude-sonnet-5-5', 'claude-haiku-5-5']
  let spawned = 0
  on('agent.spawn', () => ({ model: models[spawned] ?? 'x', agentId: `a${++spawned}` }) as never)
  await $.prompt.submit({ text: 'Review the hooks', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'Review the hooks', turnId: 't1' })
  await $.tool.call({ tool: 'Skill', skill: 'qa-review' } as never)
  for (const id of ['tu1', 'tu2']) {
    await $.tool.call({ tool: 'Agent', description: 'x' } as never)
    await $.agent.spawn({ ...SPAWN_FG, tool_use_id: id } as never)
  }
  await clock.advance(12_000)
  const texts = async (): Promise<string[]> => {
    const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
    const all = (await ui.findAll({ type: 'Text' })).map(item => item.text)
    await ui.unmount()
    return all
  }
  // Working: Haiku's phrase replaces the raw call label, stats as above.
  let all = await texts()
  expect(all).toContain('  ▸ Revisa los hooks del plugin')
  expect(all.some(text => /Agent x|qa-review/.test(text))).toBe(false)
  expect(all.join('')).toContain('◔ 13%    3 calls · 1 skill · ●● 2 agents')
  for (const id of ['a1', 'a2']) {
    await $.turn.complete({ ...done, agentId: id, turnId: `s-${id}` })
  }
  // Done: the conclusion, the session total with its tokens, and the dots stay (agents used in the whole request).
  await $.turn.complete({ ...done, turnId: 't1', answer: 'All reviewed', usage: USAGE('claude-opus-5-5', 7_000_000) } as never)
  await clock.advance(2000)
  all = await texts()
  expect(all).toContain('  ✓ Todo listo y probado')
  expect(all.join('')).toContain('◔ 13%    3 calls · 1 skill · ●● 2 agents')
  // The context icon is its own text, colored by use.
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: 'Σ 12s · 7.0M' })).toBeDefined()
  expect(await ui.find({ type: 'Box', props: { justifyContent: 'space-between' } })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /^◔ 13%$/ }))?.props.color).toBe('#5f9e6e')
  // (the main card's own model dot comes first, then the stats line's, then the agent cards')
  expect((await ui.findAll({ type: 'Text', text: /^●$/ })).map(dot => dot.props.color).slice(1, 3)).toEqual(['#d97aaa', '#46b0b8'])
  // The only agent count outside the stats line is the divider's (cards shown).
  expect(all.filter(text => /agent/i.test(text) && !text.includes('Σ') && !/^── Agentes/.test(text) && !/^\s*agents?$|^ \d+ agents?$/.test(text))).toEqual([])
  await ui.unmount()
})

test('context icon by quarters and color by use; agent dots by family', () => {
  const at = (percent: number | undefined) => formatContext(percent)
  expect(at(undefined)).toBeNull()
  expect(at(Number.NaN)).toBeNull()
  expect([0, 12, 12.5, 37, 37.5, 62, 62.5, 87, 87.5, 100].map(p => at(p)?.icon).join('')).toBe('○○◔◔◑◑◕◕●●')
  const GREEN = '#5f9e6e'
  const AMBER = '#c49a3c'
  const RED = '#c0605a'
  expect([0, 49.9].map(p => at(p)?.color)).toEqual([GREEN, GREEN])
  expect([50, 65, 80].map(p => at(p)?.color)).toEqual([AMBER, AMBER, AMBER])
  expect([80.1, 95, 100, 140].map(p => at(p)?.color)).toEqual([RED, RED, RED, RED])
  expect(at(13.4)?.text).toBe('◔ 13%')
  expect(at(140)?.text).toBe('● 100%')
  expect(agentDots({ agentModels: ['claude-haiku-5-5', 'claude-opus-5-5', 'mystery', 'claude-haiku-5-5'] })).toEqual(['#9478d8', '#46b0b8', undefined])
})

test('with background work the blue card replaces the working one in the same place', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'minutos: 2')
  await $.turn.start({ text: 'Run the benchmarks', turnId: 't1' })
  await $.tool.call(BENCH)
  await clock.advance(5000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · en segundo plano/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Claude · trabajando/ })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /^◆$/ }))?.props.color).toBe('#6ba3e6')
  await ui.unmount()
  await $.turn.complete(done)
  const after = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await after.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  expect(await after.find({ type: 'Text', text: /^100%$/ })).toBeUndefined()
  await after.unmount()
})

test('a turn shorter than 20 s is not remembered', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const clock = engine(on, saved)
  haiku(on, 'none')
  await $.turn.start({ text: 'Quick question', turnId: 't1' })
  await clock.advance(5000)
  await $.turn.complete(done)
  expect(saved['turn-samples']).toBeUndefined()
})

test('the main card is listo once the main loop is idle, with no settle timer, after a command and a compaction fork', async ($, on) => {
  const clock = engine(on, {}, { backgroundTaskId: undefined })
  haiku(on, 'minutos: 2')
  await $.prompt.submit({ text: 'como va esto?', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'como va esto?', turnId: 't1' })
  await clock.advance(10_000)
  await $.tool.call({ tool: 'Bash', command: 'ls', description: 'List' } as never)
  // The turn ends; the settle timer never gets to fire.
  await $.turn.complete({ ...done, turnId: 't1', answer: 'ok' })
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeDefined()
  await ui.unmount()
  // A command and a compaction fork (an agent id no list names) do not reopen the cycle.
  await $.command.run({ command: 'agents-debug', args: '', origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'summarize', turnId: 'c1', agentId: 'fork-1' })
  await $.tool.call({ tool: 'Read', file_path: '/x.ts', agentId: 'fork-1' } as never)
  await clock.advance(5000)
  await clock.advance(60_000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Claude · trabajando/ })).toBeUndefined()
  await ui.unmount()
  const out = await $.command.run({ command: 'agents-debug', args: '', origin: { kind: 'composer' } } as never)
  expect(JSON.stringify(out)).toContain('cycle: busySince=')
})

test('an engine-listed agent this mod lost is adopted as a main wait (blue); when the engine stops listing it the card is listo and the cycle ended', async ($, on) => {
  const clock = engine(on, {}, { backgroundTaskId: undefined })
  haiku(on, 'none')
  let listed = true
  on('agent.list', () => ({ value: listed ? [{ id: 'ghost', description: 'Long bench', type: 'agent-skills:check-runner', status: 'running' }] : [] }) as never)
  on('ui.panes', () => ({ value: [] }) as never)
  await $.prompt.submit({ text: 'hola', wait: false, origin: { kind: 'composer' } } as never)
  await $.turn.start({ text: 'hola', turnId: 't1' })
  await clock.advance(10_000)
  await $.turn.complete({ ...done, turnId: 't1', answer: 'ok' })
  await clock.advance(20_000)
  let ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · (esperando|en segundo plano)/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Claude · trabajando/ })).toBeUndefined()
  await ui.unmount()
  expect(await waitsOf($)).toBe('waits: agent ghost')
  const out = (await $.command.run({ command: 'agents-debug', args: '', origin: { kind: 'composer' } } as never)).text
  expect(out).toContain('engine agents: ghost running agent-skills:check-runner')
  listed = false
  await clock.advance(3000)
  ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /Claude · listo/ })).toBeDefined()
  await ui.unmount()
  const after = (await $.command.run({ command: 'agents-debug', args: '', origin: { kind: 'composer' } } as never)).text
  expect(after).toContain('settling=false')
  expect(after).toContain('waits: none')
})

test('the main card waiting on one agent names it once', async ($, on) => {
  const clock = engine(on, {})
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('model.complete', () => ({
    value: { isAnswered: false, text: '', usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } },
  }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({
    tool_use_id: 'tu1',
    prompt: 'Build it',
    description: 'Build it',
    subagentType: 'agent-skills:implementer',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-opus-5-5',
    background: true,
    fork: false,
  } as never)
  await $.turn.complete(done)
  await clock.advance(2000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  const texts = (await ui.findAll({ type: 'Text' })).map(item => item.text)
  expect(texts.filter(text => /esperando a implementer/.test(text))).toEqual(['  esperando a implementer'])
  expect(texts.some(text => /implementer · esperando/.test(text))).toBe(false)
  await ui.unmount()
})
