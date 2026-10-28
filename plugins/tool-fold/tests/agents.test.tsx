import { expect, mock, test } from 'claude-code/testing'

import { commandOf, countsLine, describeStep, estimateInput, formatDuration, summarize } from '../hooks/agents'

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
    expect((await ui.find({ type: 'Text', text: /haiku/ }))?.text).toBe('● haiku-5-5')
    // The mission replaces the short description; the card keeps the last two calls.
    expect((await ui.find({ type: 'Text', text: /Busca/ }))?.text).toBe('  Busca dónde se crean las sesiones')
    expect((await ui.find({ type: 'Text', text: /Read/ }))?.text).toBe('  └ ✓ Read session.py')
    expect((await ui.find({ type: 'Text', text: /Search/ }))?.text).toBe('  └ ✓ Search "Session(" in src/')
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
  expect((await ui.find({ type: 'Text', text: /1m 15s/ }))?.text).toBe('1m 15s')
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
  expect((await pane.find({ type: 'Text', text: /Benchmark/ }))?.text).toBe('  └ ✓ Benchmark the codec')
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
    // Only the progress estimates count here, not the mission line.
    estimates += String(e.prompt).includes('porcentaje') ? 1 : 0
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
  expect((await pane.find({ type: 'Text', text: /%/ }))?.text).toBe('▰▰▱▱▱ ≈40%')
  await pane.unmount()
  expect(estimates).toBe(1)
  await clock.advance(30_000)
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(estimates).toBe(2)
})

test('a background agent that ends moves its card to its finished notice', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.open', () => ({ value: { isPlaced: false } }))
  on('ui.close', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'engine row' }))
  mock.clock(on)

  await $.agent.spawn({ ...SPAWN, background: true })
  await $.tool.call({ tool: 'Bash', command: 'cargo test', description: 'Run tests', agentId: 'a1' })
  await $.turn.complete({ agentId: 'a1', answer: 'ok', durationMs: 90000, isAborted: false, turnId: 't1', reason: 'answer' })

  // Its own row empties...
  const row = await $.ui.mount({ ...ROW, surface: 'vscode', props: { ...ROW.props, isRunning: false } })
  expect(await row.find({ type: 'Text' })).toBeUndefined()
  await row.unmount()
  // ...and the notice at the bottom draws the folded card.
  const notice = await $.ui.mount({
    plugin: 'tool-fold',
    component: 'UserMessage',
    requestId: 'n1',
    surface: 'vscode',
    props: { text: 'Agent "Find session creation" finished', origin: { kind: 'task-notification' }, isExpanded: true, task: { status: 'completed', toolUseId: 'tu1' } },
  } as never)
  expect((await notice.find({ type: 'Text', text: /^Explore$/ }))?.text).toBe('Explore')
  expect((await notice.find({ type: 'Text', text: /1 command/ }))?.text).toBe('  1 call · 1 command')
  await notice.unmount()
})

test('pane texts are cut to the pane width, so a narrow panel is not widened', async ($, on) => {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.log', () => ({ value: undefined }))
  mock.clock(on)
  await $.agent.spawn({ ...SPAWN, description: 'Añadir fuzzing acotado y opcional con dos objetivos (lector de formato y preflight de LAS)' })
  await $.tool.call({ tool: 'Bash', command: 'cargo fuzz run', description: 'Escribe la documentación de fuzzing en fuzz/README.md con ejemplos', agentId: 'a1' })
  const pane = await $.ui.mount({
    plugin: 'tool-fold',
    component: 'Pane',
    requestId: 'agents',
    surface: 'vscode',
    props: { title: 'Agentes', isFocused: false, bodyColumns: 40, placement: 'inline', scroll: { offset: 0, bodyRows: 12 }, view: {} },
  } as never)
  for (const text of await pane.findAll({ type: 'Text' })) {
    expect(text.text.length).toBeLessThanOrEqual(40)
  }
  await pane.unmount()
})

test('the estimate reads the brief, elapsed time and each call with its duration', () => {
  const text = estimateInput(
    {
      id: 'a1',
      toolUseId: 'tu1',
      type: 'performance-analyst',
      description: 'Measure V5 vs V7',
      mission: 'Medir conversión de V5 frente a V7',
      brief: 'Measure full conversion and read of V5 against V7.3-pre and document it.',
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
    },
    600_000,
  )
  expect(text).toContain('Encargo:\nMeasure full conversion')
  expect(text).toContain('Tiempo transcurrido: 10m 00s')
  expect(text).toContain('- 1m 35s ✓ Compila el workspace en release')
  expect(text).toContain('- 7m 00s ✓ Convierte la muestra a V7')
  expect(text).toContain('- lleva 10s: Mide la lectura de V7')
  expect(text).toContain('Tu estimación anterior: 40%')
})
