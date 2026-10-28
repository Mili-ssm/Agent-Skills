import { expect, mock, test } from 'claude-code/testing'

import { describeStep, formatDuration, summarize } from '../hooks/register'

// The Agent call's row as a surface would mount it.
const ROW = {
  plugin: 'agents-pane',
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
  mock.clock(on)
  on('ui.log', (_, e) => {
    logs.push(e.text)
    return { value: undefined }
  })
  const logs: string[] = []

  await $.agent.spawn(SPAWN)
  await $.tool.call({ tool: 'Read', file_path: 'src/session.py', agentId: 'a1' })
  await $.tool.call({ tool: 'Grep', pattern: 'Session(', path: 'src', agentId: 'a1' })

  expect(logs).toEqual([])
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...ROW, surface })
    expect((await ui.find({ type: 'Text', text: /^Explore$/ }))?.text).toBe('Explore')
    expect((await ui.find({ type: 'Text', text: /haiku/ }))?.text).toBe('haiku-5-5')
    expect((await ui.find({ type: 'Text', text: /Explored/ }))?.text).toBe('└ Explored 1 file, 1 search')
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
