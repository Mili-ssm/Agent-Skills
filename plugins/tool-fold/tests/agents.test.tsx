import { expect, mock, test } from 'claude-code/testing'

import {
  AGENT_ICONS,
  FAMILY_COLOR,
  STATE_COLOR,
  commandOf,
  countsLine,
  describeStep,
  dotColor,
  estimateInput,
  estimateOf,
  formatDuration,
  iconOf,
  progressSvg,
  stateOf,
  summarize,
} from '../hooks/agents'
import { median } from '../hooks/estimates'

// The Agent call's row as a surface would mount it.
const ROW = {
  plugin: 'tool-fold',
  component: 'ToolUse',
  requestId: 'tu1',
  props: {
    tool_use_id: 'tu1',
    tool: 'Agent',
    input: { description: 'Find session creation' },
    isRunning: true,
    isErrored: false,
    isInterrupted: false,
  },
} as const

// A spawn as the engine raises it for a model's Agent call.
const SPAWN = {
  tool_use_id: 'tu1',
  prompt: 'Find where sessions are created',
  description: 'Find session creation',
  subagentType: 'Explore',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'claude-opus-5-5',
  background: false,
  fork: false,
} as const

const PANE_PROPS = { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 12 }, view: {} }

test('icons follow the agent type, with or without the plugin prefix', () => {
  expect(iconOf('Explore')).toBe('⌕')
  expect(iconOf('agent-skills:researcher')).toBe('⌕')
  expect(iconOf('agent-skills:implementer')).toBe('✎')
  expect(iconOf('doc-curator')).toBe('✎')
  expect(iconOf('agent-skills:check-runner')).toBe('▶')
  expect(iconOf('performance-analyst')).toBe('▶')
  expect(iconOf('general-purpose')).toBe('◇')
  expect(Object.keys(AGENT_ICONS)).toContain('summarizer')
})

test('state colors: running orange, waiting blue, completed green, failed and stopped red', () => {
  expect(STATE_COLOR.running).toEqual({ hex: '#d97757', theme: 'claude' })
  expect(STATE_COLOR.waiting.hex).toBe('#58a6ff')
  expect(STATE_COLOR.completed).toEqual({ hex: '#3fb950', theme: 'success' })
  expect(STATE_COLOR.failed.theme).toBe('error')
  expect(stateOf({ id: 'a1', status: 'running' })).toBe('running')
  expect(stateOf({ id: 'wait-b1', status: 'running' })).toBe('waiting')
  expect(stateOf({ id: 'a1', status: 'done' })).toBe('completed')
  expect(stateOf({ id: 'a1', status: 'failed' })).toBe('failed')
  expect(stateOf({ id: 'a1', status: 'aborted' })).toBe('failed')
  expect(progressSvg(1, 4, 100, '#fff')).toContain('width="25.00"')
})

test('steps are named and grouped as Codex does', () => {
  expect(describeStep('Read', { file_path: 'src/app/session.py' }).label).toBe('Read session.py')
  expect(describeStep('Grep', { pattern: 'Session(', path: 'src' }).label).toBe('Search "Session(" in src/')
  expect(describeStep('Bash', { command: 'npm test\nnpm run lint' }).label).toBe('Run npm test')
  expect(commandOf('cd /home/mili/Documentos/WORK/app && S=/tmp/x; sed -n 1p /tmp/claude-1000/-home-mili/scratch/out.json')).toBe(
    'sed -n 1p …/scratch/out.json',
  )
  expect(commandOf('cd /home/mili/Rust/octree_viewer_v3\ncargo test -p viewer')).toBe('cargo test -p viewer')
  expect(commandOf('S=/tmp/claude-1000/x/scratchpad python3 merge.py')).toBe('python3 merge.py')
  expect(summarize({ read: 3, search: 2, edit: 1, run: 1 })).toBe(
    '7 calls · Explored 3 files, 2 searches · Edited 1 file · Ran 1 command',
  )
  // Distinct files rather than edits; skills by name.
  expect(
    countsLine({ counts: { read: 6, search: 3, edit: 6, run: 20 }, files: ['a', 'b', 'c', 'd'], skills: ['qa-review'], failures: 1 }),
  ).toBe('35 calls · 9 searches · 4 edits · 20 commands · qa-review · 1 failed')
  expect(formatDuration(75000)).toBe('1m 15s')
})

test('a running agent shows its live tool, then folds into one summary line', async ($, on) => {
  // These hooks stand for the engine beneath the mod.
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  // Haiku's answer for the mission line.
  on('model.complete', () => ({
    value: {
      isAnswered: true,
      text: '«Busca dónde se crean las sesiones.»',
      usage: { input_tokens: 80, output_tokens: 12, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
    },
  }))
  mock.clock(on)
  const statuses: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  on('ui.log', (_, e) => {
    logs.push(e.text)
    return { value: undefined }
  })
  const logs: string[] = []

  await $.agent.spawn(SPAWN)
  await $.tool.call({ tool: 'Read', file_path: 'src/session.py', agentId: 'a1' })
  await $.tool.call({ tool: 'Grep', pattern: 'Session(', path: 'src', agentId: 'a1' })

  expect(logs).toEqual([])
  // Running agents live in their cards only: nothing on the status line.
  expect(statuses.filter(text => text !== undefined)).toEqual([])
  // While it runs, its chat row draws nothing: the Agentes pane holds its card.
  const row = await $.ui.mount({ ...ROW, surface: 'vscode' })
  expect(await row.find({ type: 'Text' })).toBeUndefined()
  await row.unmount()
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({
      plugin: 'tool-fold',
      component: 'Pane',
      requestId: 'agents',
      surface,
      props: { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 12 }, view: {} },
    } as never)
    expect((await ui.find({ type: 'Text', text: /^Explore$/ }))?.text).toBe('Explore')
    expect((await ui.find({ type: 'Text', text: /haiku/ }))?.text).toMatch(/^● haiku-5-5 · \d+s$/)
    // One detail line: the latest call (the mission shows while it has none).
    expect(await ui.find({ type: 'Text', text: /Read session/ })).toBeUndefined()
    expect((await ui.find({ type: 'Text', text: /Search/ }))?.text).toBe('✓ Search "Session(" in src/')
    await ui.unmount()
  }

  await $.turn.complete({
    agentId: 'a1',
    answer: 'src/session.py:12',
    durationMs: 75000,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
  })

  const ui = await $.ui.mount({ ...ROW, surface: 'vscode', props: { ...ROW.props, isRunning: false } })
  expect((await ui.find({ type: 'Text', text: /1m 15s/ }))?.text).toBe('● haiku-5-5 · 1m 15s')
  expect((await ui.find({ type: 'Text', text: /calls · / }))?.text).toBe('  2 calls · 2 searches')
  expect(await ui.find({ type: 'Text', text: /Search "/ })).toBeUndefined()
  await ui.unmount()
})

test('the main loop and other tools keep the engine row', async ($, on) => {
  on('agent.spawn', () => ({ deny: 'not allowed' }))
  // The engine's own row.
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'Agent(Find session creation)' }))

  await $.agent.spawn(SPAWN)

  const ui = await $.ui.mount({ ...ROW, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /Explore/ })).toBeUndefined()
  await ui.unmount()
})

test('a workflow agent gets no Haiku mission call', async ($, on) => {
  on('agent.spawn', (_, e) => ({ model: 'claude-haiku-5-5', agentId: `a-${e.tool_use_id}` }))
  mock.clock(on)
  let missions = 0
  on('model.complete', () => {
    missions += 1
    return { value: { isAnswered: true, text: 'x', usage: { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })

  await $.agent.spawn({ ...SPAWN, workflow: { runId: 'r1', name: 'review' } } as never)
  await $.agent.spawn({ ...SPAWN, tool_use_id: 'tu2' })
  // The mission call runs after the spawn returned.
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(missions).toBe(1)
})

test('while the Agentes pane is placed, running agents live there only; the chat shows them once ended', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  mock.clock(on)
  const panes: string[] = []
  on('ui.open', (_, e) => {
    panes.push(`open ${e.id}`)
    return { value: { isPlaced: true } }
  })
  on('ui.close', (_, e) => {
    panes.push(`close ${e.id}`)
    return { value: undefined }
  })
  on('ui.log', () => ({ value: undefined }))
  const PANE = {
    plugin: 'tool-fold',
    component: 'Pane',
    requestId: 'agents',
    surface: 'vscode',
    props: { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'inline', scroll: { offset: 0, bodyRows: 12 }, view: {} },
  } as const

  await $.agent.spawn({ ...SPAWN, subagentType: 'performance-analyst' })
  await $.tool.call({ tool: 'Bash', command: 'cargo bench', description: 'Benchmark the codec', agentId: 'a1' })
  expect(panes).toEqual(['open agents'])

  const pane = await $.ui.mount(PANE as never)
  expect((await pane.find({ type: 'Text', text: /^performance-analyst$/ }))?.text).toBe('performance-analyst')
  // A call reads by what it does alone, without the command.
  expect((await pane.find({ type: 'Text', text: /Benchmark/ }))?.text).toBe('✓ Benchmark the codec')
  expect(await pane.find({ type: 'Text', text: /cargo bench/ })).toBeUndefined()
  await pane.unmount()
  // The chat shows a running agent nothing while the pane holds it.
  const chat = await $.ui.mount({ ...ROW, surface: 'vscode' })
  expect(await chat.find({ type: 'Text' })).toBeUndefined()
  await chat.unmount()

  await $.turn.complete({ agentId: 'a1', answer: 'done', durationMs: 60000, isAborted: false, turnId: 't1', reason: 'answer' })
  expect(panes).toEqual(['open agents', 'close agents'])
  const ended = await $.ui.mount({ ...ROW, surface: 'vscode', props: { ...ROW.props, isRunning: false } })
  expect((await ended.find({ type: 'Text', text: /1 command/ }))?.text).toBe('  1 call · 1 command')
  await ended.unmount()
})

test('an agent without a task list gets a Haiku estimate in the pane', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.log', () => ({ value: undefined }))
  let estimates = 0
  on('model.complete', (_, e) => {
    // Only the progress estimates count here (they carry the estimate's rules), not the mission line.
    estimates += String(e.system ?? '').includes('Estimas cuánto lleva hecho') ? 1 : 0
    return { value: { isAnswered: true, text: '40', usage: { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  const clock = mock.clock(on)

  await $.agent.spawn(SPAWN)
  // The first call asks at once; one 30 s apart waits for the gap, then asks once.
  await $.tool.call({ tool: 'Read', file_path: 'a.rs', agentId: 'a1' })
  await $.tool.call({ tool: 'Bash', command: 'cargo bench', description: 'Benchmark', agentId: 'a1' })
  await new Promise(resolve => setTimeout(resolve, 20))
  const pane = await $.ui.mount({
    plugin: 'tool-fold',
    component: 'Pane',
    requestId: 'agents',
    surface: 'vscode',
    props: { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 12 }, view: {} },
  } as never)
  expect((await pane.find({ type: 'Text', text: /%/ }))?.text).toBe('≈40% · <1 min')
  await pane.unmount()
  expect(estimates).toBe(1)
  // The thin progress line: an Svg on a surface that has one, a glyph line on the terminal; the key datum is orange while running.
  const surfaces = {
    vscode: await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never),
    terminal: await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'terminal', props: PANE_PROPS } as never),
  }
  const svg = await surfaces.vscode.find({ type: 'Svg' })
  expect(String(svg?.props.source)).toContain('fill="#d97757"')
  expect(String(svg?.props.source)).toContain('fill-opacity="0.45"')
  expect(svg?.props.height).toBe(2)
  expect(svg?.props.width).toBeUndefined()
  expect((await surfaces.vscode.find({ type: 'Text', text: /%/ }))?.props.color).toBe('claude')
  expect(await surfaces.terminal.find({ type: 'Svg' })).toBeUndefined()
  expect((await surfaces.terminal.find({ type: 'Text', text: /^▰/ }))?.props.color).toBe('claude')
  await surfaces.vscode.unmount()
  await surfaces.terminal.unmount()
  await clock.advance(30_000)
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(estimates).toBe(2)
})

test('an agent that ends keeps its folded card on its row and adds one line at the bottom', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  const logs: string[] = []
  on('ui.log', (_, e) => {
    logs.push(e.text)
    return { value: undefined }
  })
  mock.clock(on)

  await $.agent.spawn({ ...SPAWN, background: true })
  await $.tool.call({ tool: 'Bash', command: 'cargo test', description: 'Run tests', agentId: 'a1' })
  await $.turn.complete({ agentId: 'a1', answer: 'ok', durationMs: 90000, isAborted: false, turnId: 't1', reason: 'answer' })

  // The bottom of the chat gets one line: what ended and what it did.
  expect(logs.filter(line => line.startsWith('✓'))).toEqual(['✓ Explore · sonnet-5-5 · 1m 30s · Find session creation · 1 call · 1 command'])
  // Its own row keeps the folded card.
  const row = await $.ui.mount({ ...ROW, surface: 'vscode', props: { ...ROW.props, isRunning: false } })
  expect((await row.find({ type: 'Text', text: /^Explore$/ }))?.text).toBe('Explore')
  expect((await row.find({ type: 'Text', text: /1 command/ }))?.text).toBe('  1 call · 1 command')
  await row.unmount()
})

test('pane texts are cut to the room the surface really has, so a narrow panel is not widened', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.log', () => ({ value: undefined }))
  mock.clock(on)
  await $.agent.spawn({ ...SPAWN, description: 'Añadir fuzzing acotado y opcional con dos objetivos (lector de formato y preflight de LAS)' })
  await $.tool.call({ tool: 'Bash', command: 'cargo fuzz run', description: 'Escribe la documentación de fuzzing en fuzz/README.md con ejemplos', agentId: 'a1' })
  const mount = (surface: string) =>
    $.ui.mount({
      plugin: 'tool-fold',
      component: 'Pane',
      requestId: 'agents',
      surface,
      props: { title: 'Agentes', isFocused: false, bodyColumns: 40, placement: 'inline', scroll: { offset: 0, bodyRows: 12 }, view: {} },
    } as never)
  // A terminal draws one character per cell: no line is longer than the pane.
  const terminal = await mount('terminal')
  for (const text of await terminal.findAll({ type: 'Text' })) {
    expect(text.text.length).toBeLessThanOrEqual(40)
  }
  await terminal.unmount()
  // VS Code's proportional font fits about 1.5 characters per cell: lines use that room, and stay one line.
  const vscode = await mount('vscode')
  const lines = await vscode.findAll({ type: 'Text' })
  for (const text of lines) {
    expect(text.text.length).toBeLessThanOrEqual(Math.floor((40 - 4) * 1.5))
  }
  expect(lines.some(text => text.text.length > 40)).toBe(true)
  await vscode.unmount()
})

test('the estimate reads the mission, elapsed time and each call with its duration', () => {
  const text = estimateInput(
    {
      id: 'a1',
      toolUseId: 'tu1',
      type: 'performance-analyst',
      description: 'Measure V5 vs V7',
      mission: 'Medir conversión de V5 frente a V7',
      model: 'claude-sonnet-5-5',
      status: 'running',
      startedAt: 0,
      current: [{ id: 's3', kind: 'run', label: 'Run cargo bench', detail: 'Mide la lectura de V7', status: 'running', startedAt: 590_000 }],
      recent: [],
      counts: { run: 2 },
      history: [
        { what: 'Compila el workspace en release', ms: 95_000, ok: true },
        { what: 'Convierte la muestra a V7', ms: 420_000, ok: true },
      ],
      estimate: 40,
      typical: { ms: 480_000, of: 6 },
    },
    600_000,
  )
  expect(text).toContain('Referencia: agentes de este tipo suelen tardar ~8m 00s (mediana de 6)')
  expect(text).toContain('Misión: Medir conversión de V5 frente a V7')
  expect(text).toContain('Tiempo transcurrido: 10m 00s')
  expect(text).toContain('- 1m 35s ✓ Compila el workspace en release')
  expect(text).toContain('- 7m 00s ✓ Convierte la muestra a V7')
  expect(text).toContain('- lleva 10s: Mide la lectura de V7')
  expect(text).toContain('Tu estimación anterior: 40%')
})

test('a mission with no measurable end (a watcher) shows no percentage', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: 'w1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', (_, e) => ({
    value: {
      isAnswered: true,
      text: String(e.system ?? '').includes('Estimas cuánto lleva hecho') ? '?' : 'Vigila el PR 42',
      usage: { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
    },
  }))
  mock.clock(on)

  await $.agent.spawn({ ...SPAWN, subagentType: 'pr-watcher', description: 'Watch PR 42' })
  await $.tool.call({ tool: 'Bash', command: 'gh pr checks 42', description: 'Check PR status', agentId: 'w1' })
  await new Promise(resolve => setTimeout(resolve, 20))
  const pane = await $.ui.mount({
    plugin: 'tool-fold',
    component: 'Pane',
    requestId: 'agents',
    surface: 'vscode',
    props: { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 12 }, view: {} },
  } as never)
  expect((await pane.find({ type: 'Text', text: /^pr-watcher$/ }))?.text).toBe('pr-watcher')
  expect(await pane.find({ type: 'Text', text: /%/ })).toBeUndefined()
  await pane.unmount()
})

test('remembered durations: a reference line for Haiku, and time-based progress for an open-ended mission', () => {
  expect(median([480_000, 300_000, 600_000])).toBe(480_000)
  expect(median([])).toBeUndefined()
  const watcher = { startedAt: 0, isOpenEnded: true, typical: { ms: 600_000, of: 4 } }
  // 6 of a usual 10 minutes; never past 95 while it runs.
  expect(estimateOf(watcher, 360_000)).toBe(60)
  expect(estimateOf(watcher, 900_000)).toBe(95)
  // Without a reference an open-ended mission shows nothing; Haiku's reading wins when there is one.
  expect(estimateOf({ startedAt: 0, isOpenEnded: true }, 360_000)).toBeUndefined()
  expect(estimateOf({ startedAt: 0, estimate: 40, typical: { ms: 600_000, of: 4 } }, 360_000)).toBe(40)
})

test('on Desktop, running agents draw in the band above the prompt and open no pane', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  const opened: string[] = []
  on('ui.open', (_, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true } }
  })
  on('session.surfaces', () => ({ value: ['desktop'] }) as never)
  on('ui.panes', () => ({ value: [] }) as never)
  on('ui.log', () => ({ value: undefined }))
  // The engine beneath draws an empty band.
  on('ui.render', ($, e) => $.ui.resolve(e).Box({}))
  mock.clock(on)
  const band = (surface: string) =>
    $.ui.mount({
      plugin: 'tool-fold',
      component: 'AbovePrompt',
      requestId: 'band',
      surface,
      props: { hasSurvey: false, isWorking: true, maxRows: 20, bodyColumns: 80, scroll: { offset: 0, bodyRows: 20 } },
    } as never)

  await $.agent.spawn({ ...SPAWN, subagentType: 'performance-analyst' })
  await $.tool.call({ tool: 'Bash', command: 'cargo bench', description: 'Benchmark the codec', agentId: 'a1' })

  // Desktop never says when its pane is closed: the pane is not opened, the band holds the agent.
  expect(opened).toEqual([])
  const desktop = await band('desktop')
  expect((await desktop.find({ type: 'Text', text: /^performance-analyst$/ }))?.text).toBe('performance-analyst')
  expect((await desktop.find({ type: 'Text', text: /Benchmark/ }))?.text).toBe('✓ Benchmark the codec')
  await desktop.unmount()

  // VS Code places its own pane above the prompt: the band is not drawn there.
  const vscode = await band('vscode')
  expect(await vscode.find({ type: 'Text', text: /performance-analyst/ })).toBeUndefined()
  await vscode.unmount()

  // `/agents-debug` reports what each draw saw, for a surface nobody can watch from here.
  const { text } = await $.command.run({ command: 'agents-debug' } as never)
  expect(text).toContain('surfaces: desktop')
  expect(text).toContain('runs: 1 running of 1')
  expect(text).toMatch(/desktop survey=false running=1 drew 1 cards; beneath /)
  expect(text).toMatch(/vscode survey=false running=0 passed/)
})

test('the model dot takes the color of its family, dim for others', () => {
  expect(FAMILY_COLOR).toEqual({ opus: '#a371f7', sonnet: '#f778ba', haiku: '#39c5cf', fable: '#e3b341' })
  expect(dotColor('claude-opus-5-5')).toBe('#a371f7')
  expect(dotColor('claude-sonnet-5-5')).toBe('#f778ba')
  expect(dotColor('claude-haiku-5-5')).toBe('#39c5cf')
  expect(dotColor('fable-1')).toBe('#e3b341')
  expect(dotColor('gpt-x')).toBe('subtle')
})

/** The engine beneath the mod for the agent memory tests: a map store, agents a1, a2, ... in order. */
function memoryEngine(on: Parameters<Parameters<typeof test>[1]>[1], saved: Record<string, unknown>, prompts: string[] = [], pick = 'none') {
  let spawned = 0
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: `a${++spawned}` }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('store.get', (_, e) => ({ value: saved[e.key] }))
  on('store.set', (_, e) => {
    saved[e.key] = e.value
    return { value: undefined }
  })
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    prompts.push(prompt)
    const text = prompt.includes('Anteriores') ? pick : '?'
    return { value: { isAnswered: true, text, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  return mock.clock(on)
}

const paneOf = ($: Parameters<Parameters<typeof test>[1]>[0]) =>
  $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)

test('a finished agent is remembered apart from waits and gives a similar one its progress, with the ⟲ icon', async ($, on) => {
  const saved: Record<string, unknown> = {}
  const prompts: string[] = []
  const clock = memoryEngine(on, saved, prompts)

  await $.agent.spawn({ ...SPAWN, background: true })
  await $.turn.complete({ agentId: 'a1', answer: 'ok', durationMs: 90_000, isAborted: false, turnId: 't1', reason: 'answer' })
  // Recorded under its own key, as `type: description`; the wait store stays untouched.
  expect(saved['agent-samples']).toMatchObject([{ summary: 'Explore: Find session creation', durationMs: 90_000 }])
  expect(saved['wait-samples']).toBeUndefined()

  await $.agent.spawn({ ...SPAWN, tool_use_id: 'tu2', description: 'Find session creation code', background: true })
  await clock.advance(45_000)
  const pane = await paneOf($)
  // 45 s of the 90 s similar agents took: 50%.
  expect((await pane.find({ type: 'Text', text: /%/ }))?.text).toBe('≈50% · <1 min')
  expect((await pane.find({ type: 'Text', text: /^⟲$/ }))?.props.dimColor).toBe(true)
  await pane.unmount()
  // Past the typical time it says so, and stays under 100%.
  await clock.advance(60_000)
  const late = await paneOf($)
  expect((await late.find({ type: 'Text', text: /%/ }))?.text).toBe('≈95% · más de lo previsto')
  await late.unmount()
  // A found sample needs no Haiku pick, and a failed agent teaches nothing.
  expect(prompts.some(prompt => prompt.includes('Anteriores'))).toBe(false)
})

test('with no similar agent Haiku picks once, given the brief; a failed agent is not remembered', async ($, on) => {
  const saved: Record<string, unknown> = {
    'agent-samples': [{ summary: 'Plan: migrate the database', durationMs: 600_000, at: 1 }],
  }
  const prompts: string[] = []
  const clock = memoryEngine(on, saved, prompts, '1')

  await $.agent.spawn({ ...SPAWN, background: true })
  await new Promise(resolve => setTimeout(resolve, 20))
  await clock.advance(300_000)
  const picks = prompts.filter(prompt => prompt.includes('Anteriores'))
  expect(picks).toHaveLength(1)
  expect(picks[0]).toContain('Find where sessions are created')
  const pane = await paneOf($)
  expect((await pane.find({ type: 'Text', text: /%/ }))?.text).toMatch(/^≈50%/)
  expect(await pane.find({ type: 'Text', text: /^⟲$/ })).toBeDefined()
  await pane.unmount()
  await $.turn.complete({ agentId: 'a1', answer: '', durationMs: 5000, isAborted: false, turnId: 't1', reason: 'error' })
  expect(saved['agent-samples']).toHaveLength(1)
})

test('the agent task list still wins over the similar-agent estimate', async ($, on) => {
  const saved: Record<string, unknown> = {
    'agent-samples': [{ summary: 'Explore: Find session creation', durationMs: 90_000, at: 1 }],
  }
  const clock = memoryEngine(on, saved)

  await $.agent.spawn({ ...SPAWN, background: true })
  await $.tool.call({
    tool: 'TodoWrite',
    todos: [
      { content: 'a', status: 'completed', activeForm: 'a' },
      { content: 'b', status: 'pending', activeForm: 'b' },
    ],
    agentId: 'a1',
  })
  await clock.advance(45_000)
  const pane = await paneOf($)
  expect(await pane.find({ type: 'Text', text: /^1\/2$/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /%/ })).toBeUndefined()
  expect(await pane.find({ type: 'Text', text: /^⟲$/ })).toBeUndefined()
  await pane.unmount()
})
