import { expect, mock, test } from 'claude-code/testing'

import { commandOf, describeStep, formatDuration, summarize } from '../hooks/agents'

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
  expect(summarize({ read: 3, search: 2, edit: 1, run: 1 })).toBe(
    'Explored 3 files, 2 searches · Edited 1 file · Ran 1 command',
  )
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
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...ROW, surface })
    expect((await ui.find({ type: 'Text', text: /^Explore$/ }))?.text).toBe('Explore')
    expect((await ui.find({ type: 'Text', text: /haiku/ }))?.text).toBe('● haiku-5-5')
    // The mission replaces the short description; the card keeps the last two calls.
    expect((await ui.find({ type: 'Text', text: /Busca/ }))?.text).toBe('Busca dónde se crean las sesiones')
    expect((await ui.find({ type: 'Text', text: /Read/ }))?.text).toBe('  ✓ Read session.py')
    expect((await ui.find({ type: 'Text', text: /Search/ }))?.text).toBe('  ✓ Search "Session(" in src/')
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
  expect((await ui.find({ type: 'Text', text: /Explored/ }))?.text).toBe('  └ Explored 1 file, 1 search')
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

test('while the Agentes pane is placed, running agents live there and the chat keeps one line', async ($, on) => {
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
  const PANE = {
    plugin: 'tool-fold',
    component: 'Pane',
    requestId: 'agents',
    surface: 'vscode',
    props: { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'inline', scroll: { offset: 0, bodyRows: 12 }, view: {} },
  } as const

  await $.agent.spawn({ ...SPAWN, subagentType: 'performance-analyst' })
  await $.tool.call({ tool: 'Bash', command: 'cargo bench', agentId: 'a1' })
  expect(panes).toEqual(['open agents'])

  const pane = await $.ui.mount(PANE as never)
  expect((await pane.find({ type: 'Text', text: /^performance-analyst$/ }))?.text).toBe('performance-analyst')
  expect((await pane.find({ type: 'Text', text: /cargo bench/ }))?.text).toBe('  ✓ Run cargo bench')
  await pane.unmount()
  const chat = await $.ui.mount({ ...ROW, surface: 'vscode' })
  expect((await chat.find({ type: 'Text', text: /^performance-analyst$/ }))?.text).toBe('performance-analyst')
  expect(await chat.find({ type: 'Text', text: /cargo bench/ })).toBeUndefined()
  await chat.unmount()

  await $.turn.complete({ agentId: 'a1', answer: 'done', durationMs: 60000, isAborted: false, turnId: 't1', reason: 'answer' })
  expect(panes).toEqual(['open agents', 'close agents'])
  const ended = await $.ui.mount({ ...ROW, surface: 'vscode', props: { ...ROW.props, isRunning: false } })
  expect((await ended.find({ type: 'Text', text: /Ran 1 command/ }))?.text).toBe('  └ Ran 1 command')
  await ended.unmount()
})
