import { expect, mock, test } from 'claude-code/testing'

import { formatRemaining, remainingOf } from '../hooks/agents'
import { SIMILARITY_MIN, similarity, statedDuration } from '../hooks/estimates'
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
  expect(await ui.findAll({ type: 'Text', text: /Run the bench/ })).toHaveLength(1)
  // No sample yet: the elapsed time sits by the model, no percentage on the right.
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('● opus-5-5 · 1m 12s')
  expect(await ui.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  await ui.unmount()
  // VS Code (the surface some app panels report) carries the main agent's card in its band too.
  ui = await $.ui.mount({ ...BAND, surface: 'vscode' })
  expect(await ui.find({ type: 'Text', text: /Claude · esperando/ })).toBeDefined()
  // The clock moves the card.
  await clock.advance(3000)
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('● opus-5-5 · 1m 15s')
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
  const saved: Record<string, unknown> = { 'wait-samples': [100_000, 180_000, 240_000].map(durationMs => ({ summary: 'Run the bench', durationMs, at: 1 })) }
  const clock = engine(on, saved)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(90_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: /opus-5-5/ }))?.text).toBe('● opus-5-5 · 1m 30s')
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
    expect((await ui.find({ type: 'Text', text: /^◆$/ }))?.props.color).toBe('suggestion')
    // 50% at 90 s: 90 s left.
    expect(await ui.find({ type: 'Text', text: /≈50% · ~2 min/ })).toBeDefined()
    // The wait is blue, its thin line too.
    expect(String((await ui.find({ type: 'Svg' }))?.props.source)).toContain('#58a6ff')
    await ui.unmount()
  }
})

/** A model.complete stub answering `text`, recording the prompts. */
const haiku = (on: Parameters<Parameters<typeof test>[1]>[1], text: string, prompts: string[] = []) =>
  on('model.complete', (_, e) => {
    prompts.push(String((e as { prompt?: string }).prompt))
    return { value: { isAnswered: true, text, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })

const RAW = { tool: 'Bash', command: "cat > $S <<'EOF'\nbody\nEOF", run_in_background: true } as const

test('with a description Haiku writes no label; a guessed estimate draws the line and time left', async ($, on) => {
  const clock = engine(on)
  const prompts: string[] = []
  haiku(on, 'minutos: 4', prompts)
  await $.turn.start({ text: 'go', turnId: 't1' })
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

test('without a description Haiku names the wait and guesses its duration', async ($, on) => {
  const clock = engine(on)
  haiku(on, 'descripcion: Escribe el script de prueba\nminutos: 10')
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
  haiku(on, 'minutos: 1')
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(150_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /≈95% · más de lo previsto/ })).toBeDefined()
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
  await $.turn.start({ text: 'go', turnId: 't1' })
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

test('with no similar summary Haiku picks from the latest ones', async ($, on) => {
  const clock = engine(on, { 'wait-samples': [sample('Deploy the docs site', 900_000), sample('Train the model overnight', 120_000)] })
  const prompts: string[] = []
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    prompts.push(prompt)
    const text = prompt.includes('<anteriores>') ? '2' : 'minutos: 30'
    return { value: { isAnswered: true, text, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call(BENCH)
  await $.turn.complete(done)
  await clock.advance(60_000)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  // The pick (120 s) outranks the guess (30 min): 60 s is 50%.
  expect(prompts.some(prompt => prompt.includes('2. Train the model overnight'))).toBe(true)
  expect(await ui.find({ type: 'Text', text: /≈50%/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^⟲$/ })).toBeDefined()
  await ui.unmount()
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
  await $.turn.start({ text: 'go', turnId: 't1' })
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

test('the pane title counts the cards it shows', async ($, on) => {
  const clock = engine(on)
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  const titles: string[] = []
  on('ui.open', (_, e) => {
    titles.push(e.title)
    return { value: { isPlaced: true } }
  })
  on('session.surfaces', () => ({ value: ['vscode'] }) as never)
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn(SPAWN)
  await $.turn.complete(done)
  await clock.advance(1000)
  expect(titles[0]).toBe('Agentes · 1')
  // The turn ended: the main card joins the running agent.
  expect(titles.at(-1)).toBe('Agentes · 2')
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
