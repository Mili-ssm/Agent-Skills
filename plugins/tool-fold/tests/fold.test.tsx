import { expect, test } from 'claude-code/testing'

import { foldLabel, runSteps, toolTally } from '../hooks/register'

// A finished Bash call's row as a surface would mount it.
const ROW = {
  plugin: 'tool-fold',
  component: 'ToolUse',
  requestId: 'tu1',
  props: {
    tool_use_id: 'tu1',
    tool: 'Bash',
    input: { command: 'cat test/a.js; sed -n 1,80p test/b.js', description: 'Read highlight browser tests' },
    isRunning: false,
    isErrored: false,
    isInterrupted: false,
  },
} as const

test('a folded row says what the call does', () => {
  expect(foldLabel('Bash', ROW.props.input)).toBe('Read highlight browser tests')
  expect(foldLabel('Edit', { file_path: 'UI/frontend/components/HighlightRows.vue' })).toBe('HighlightRows.vue')
  expect(foldLabel('Grep', { pattern: 'row-highlights' })).toBe('row-highlights')
  expect(foldLabel('Skill', { skill: 'agent-skills:ux-review', args: 'explorer page' })).toBe(
    'agent-skills:ux-review · explorer page',
  )
  expect(foldLabel('mcp__github__get_file', { path: 'README.md' })).toBe('README.md')
})

test('a call is one line until pressed, then the engine box shows under it', async ($, on) => {
  // The engine's own row, as it draws the call.
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'IN cat test/a.js' }))

  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...ROW, surface })
    expect((await ui.find({ type: 'Button' }))?.text).toBe('▸')
    expect((await ui.find({ type: 'Text', text: /Read highlight/ }))?.text).toBe('Read highlight browser tests')
    expect(await ui.find({ type: 'Text', text: /^IN / })).toBeUndefined()
    expect((await ui.find({ type: 'Text', text: /Bash/ }))?.text).toBe(' Bash ')

    await ui.press({ key: 'fold-tu1' })
    expect((await ui.find({ type: 'Button' }))?.text).toBe('▾')
    expect((await ui.find({ type: 'Text', text: /^IN / }))?.text).toBe('IN cat test/a.js')

    await ui.press({ key: 'fold-tu1' })
    expect(await ui.find({ type: 'Text', text: /^IN / })).toBeUndefined()
    await ui.unmount()
  }
})

test('Agent calls and the ctrl+o view keep the engine row', async ($, on) => {
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'engine row' }))

  const agent = await $.ui.mount({ ...ROW, surface: 'vscode', props: { ...ROW.props, tool: 'Agent' } })
  expect((await agent.find({ type: 'Text' }))?.text).toBe('engine row')
  await agent.unmount()

  const expanded = await $.ui.mount({ ...ROW, surface: 'terminal', props: { ...ROW.props, isExpanded: true } })
  expect((await expanded.find({ type: 'Text' }))?.text).toBe('engine row')
  await expanded.unmount()
})

test('the result block hides while its call is folded', async ($, on) => {
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'OUT 3 lines' }))
  const RESULT = {
    plugin: 'tool-fold',
    component: 'ToolResult',
    requestId: 'tu1',
    props: { tool_use_id: 'tu1', tool: 'Bash', output: { stdout: 'x' }, isErrored: false },
  } as const

  const folded = await $.ui.mount({ ...RESULT, surface: 'vscode' })
  expect(await folded.find({ type: 'Text', text: /OUT/ })).toBeUndefined()
  await folded.unmount()

  const row = await $.ui.mount({ ...ROW, surface: 'vscode' })
  await row.press({ key: 'fold-tu1' })
  await row.unmount()
  const shown = await $.ui.mount({ ...RESULT, surface: 'vscode' })
  expect((await shown.find({ type: 'Text', text: /OUT/ }))?.text).toBe('OUT 3 lines')
  await shown.unmount()
})

test('a reply groups its calls until text or an Agent call', () => {
  const steps = runSteps([
    { type: 'thinking', thinking: '…' },
    { type: 'tool_use', id: 't1', name: 'Bash', input: { description: 'Run tests' } },
    { type: 'tool_use', id: 't2', name: 'Skill', input: { skill: 'qa-review' } },
    // The engine folds reads into its own count line: they neither join nor close a run.
    { type: 'tool_use', id: 'r1', name: 'Read', input: { file_path: 'a.ts' } },
    { type: 'text', text: 'All green.' },
    { type: 'tool_use', id: 't3', name: 'Agent', input: {} },
  ])
  expect(steps.map(step => ('join' in step ? step.join.id : 'close'))).toEqual(['t1', 't2', 'close', 'close'])
  const call = (tool: string, label = '') => ({ tool, label })
  expect(toolTally([call('Bash'), call('Read'), call('Bash'), call('Skill', 'agent-skills:qa-review · x')])).toBe(
    'qa-review · Bash · Read',
  )
  expect(toolTally(['A', 'B', 'C', 'D', 'E', 'F'].map(name => call(name)))).toBe('A · B · C · D · E · …')
})

test('a group draws on its first row; the rest show only once it is unfolded', async ($, on) => {
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: `engine ${e.requestId}` }))
  const call = (id: string, tool: string, label: string) => ({ id, tool, label, status: 'done' as const })
  // The state the reply's rows leave: two Bash calls and a Skill in one closed run.
  const run = {
    id: 'g-tu1',
    calls: [call('tu1', 'Bash', 'Run tests'), call('tu2', 'Bash', 'Lint'), call('tu3', 'Skill', 'qa-review')],
    isClosed: true,
    summary: 'Comprueba que los tests y el lint pasan',
  }
  on('state.get', (_, e, next) =>
    e.key === 'group' && e.id === 'g-tu1'
      ? { value: { value: run, version: 1 } }
      : e.key === 'groupOf' && ['tu1', 'tu2', 'tu3'].includes(e.id ?? '')
        ? { value: { value: 'g-tu1', version: 1 } }
        : next(e),
  )
  const second = { ...ROW, requestId: 'tu2', props: { ...ROW.props, tool_use_id: 'tu2' } }

  const first = await $.ui.mount({ ...ROW, surface: 'vscode' })
  expect((await first.find({ type: 'Text', text: /qa-review · Bash/ }))?.text).toBe(' qa-review · Bash ')
  expect((await first.find({ type: 'Text', text: /Comprueba/ }))?.text).toBe('Comprueba que los tests y el lint pasan')
  const hidden = await $.ui.mount({ ...second, surface: 'vscode' })
  expect(await hidden.find({ type: 'Text' })).toBeUndefined()
  await hidden.unmount()

  await first.press({ key: 'fold-g-tu1' })
  const shown = await $.ui.mount({ ...second, surface: 'vscode' })
  expect((await shown.find({ type: 'Button' }))?.text).toBe('▸')
  expect(await shown.find({ type: 'Text', text: /engine/ })).toBeUndefined()
  await shown.press({ key: 'fold-tu2' })
  expect((await shown.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine tu2')
  await shown.unmount()
  await first.unmount()
})

test('the ctrl+o view shows the result of a folded call', async ($, on) => {
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'OUT 3 lines' }))
  const result = await $.ui.mount({
    plugin: 'tool-fold',
    component: 'ToolResult',
    requestId: 'tu9',
    surface: 'terminal',
    props: { tool_use_id: 'tu9', tool: 'Bash', output: { stdout: 'x' }, isErrored: false, isExpanded: true },
  })
  expect((await result.find({ type: 'Text', text: /OUT/ }))?.text).toBe('OUT 3 lines')
  await result.unmount()
})
