import { expect, test } from 'claude-code/testing'

import { foldLabel } from '../hooks/register'

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
})

test('a call is one line until pressed, then the engine box shows under it', async ($, on) => {
  // The engine's own row, as it draws the call.
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'IN cat test/a.js' }))

  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...ROW, surface })
    expect((await ui.find({ type: 'Button' }))?.text).toBe('● Bash Read highlight browser tests ▸')
    expect(await ui.find({ type: 'Text', text: /^IN / })).toBeUndefined()

    await ui.press({ key: 'fold-tu1' })
    expect((await ui.find({ type: 'Button' }))?.text).toBe('● Bash Read highlight browser tests ▾')
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
