import { expect, mock, test } from 'claude-code/testing'

import { foldLabel, groupCounts, noticeLine, runSteps, toolTally } from '../hooks/register'

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
  expect(foldLabel('SendMessage', { to: 'af732a1e51dd9ef7', summary: 'Fix round for Task 11' })).toBe('Fix round for Task 11')
  expect(foldLabel('AskUserQuestion', {})).toBe('')
})

test('a call is one line until pressed, then the engine box shows under it', async ($, on) => {
  // The engine's own row, as it draws the call.
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: 'IN cat test/a.js' }))

  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...ROW, surface })
    expect((await ui.find({ type: 'Button' }))?.text).toBe('▸')
    expect((await ui.find({ type: 'Text', text: /Read highlight/ }))?.text).toBe('Read highlight browser tests')
    expect(await ui.find({ type: 'Text', text: /^IN / })).toBeUndefined()
    expect((await ui.find({ type: 'Text', text: /Bash/ }))?.text).toBe('Bash')

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
    { type: 'tool_use', id: 't3', name: 'Agent', input: { subagent_type: 'agent-skills:implementer' } },
    { type: 'tool_use', id: 'q1', name: 'AskUserQuestion', input: {} },
  ])
  // Agents join runs like tools and skills; a question to the person ends one.
  expect(steps.map(step => ('join' in step ? `${step.join.id}:${step.join.tag}` : 'close'))).toEqual([
    't1:Bash',
    't2:qa-review',
    'close',
    't3:implementer',
    'close',
  ])
  const call = (tool: string, tag = tool) => ({ tool, tag })
  expect(
    toolTally([call('Bash'), call('Edit'), call('Agent', 'implementer'), call('Bash'), call('Skill', 'qa-review')]),
  ).toBe('qa-review · implementer · Bash · Edit')
  expect(toolTally(['A', 'B', 'C', 'D', 'E', 'F'].map(name => call(name)))).toBe('A · B · C · D · E · …')
  // What kinds of call a group held, so a tag list naming an agent and a tool reads plainly.
  expect(groupCounts([call('Agent', 'general-purpose'), call('Bash'), call('Bash'), call('Read')])).toBe(
    '1 agent · 2 commands · 1 search',
  )
})

test('a group draws on its first row; the rest show only once it is unfolded', async ($, on) => {
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: `engine ${e.requestId}` }))
  const call = (id: string, tool: string, label: string) => ({ id, tool, tag: tool === 'Skill' ? label : tool, label, status: 'done' as const })
  // The state the reply's rows leave: two Bash calls and a Skill in one closed run.
  const run = {
    id: 'g-tu1',
    calls: [call('tu1', 'Bash', 'Run tests'), call('tu2', 'Bash', 'Lint'), call('tu3', 'Skill', 'qa-review')],
    isClosed: true,
    summary: 'Comprueba que los tests y el lint pasan',
    startedAt: 0,
    endedAt: 75_000,
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
  expect((await first.find({ type: 'Text', text: /qa-review · Bash/ }))?.text).toBe('qa-review · Bash')
  expect((await first.find({ type: 'Text', text: /Comprueba/ }))?.text).toBe('    Comprueba que los tests y el lint pasan')
  expect((await first.find({ type: 'Text', text: /commands/ }))?.text).toBe('1 skill · 2 commands · 1m 15s')
  const hidden = await $.ui.mount({ ...second, surface: 'vscode' })
  expect(await hidden.find({ type: 'Text' })).toBeUndefined()
  await hidden.unmount()

  await first.press({ key: 'fold-g-tu1' })
  const shown = await $.ui.mount({ ...second, surface: 'vscode' })
  expect((await shown.find({ type: 'Button' }))?.text).toBe('▸')
  // Each row has a frame of its own: a tree mark ties it to the group above.
  expect((await shown.find({ type: 'Text', text: /^└$/ }))?.text).toBe('└')
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

test('agent notices: a task line is compacted, a hand-back loses the engine framing', async ($, on) => {
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: `engine: ${(e.props as { text: string }).text}` }))
  expect(noticeLine('Agent "Implement Task 11: local CI script" finished', undefined, { status: 'completed', durationMs: 182000 })).toBe(
    '✓ "Implement Task 11: local CI script" · completed · 182s',
  )
  const handBack = {
    plugin: 'tool-fold',
    component: 'UserMessage',
    requestId: 'm1',
    surface: 'vscode',
    props: {
      text: '[Subagent hand-back] The text below is the final report of a subagent. The report follows:\nAll 13 ADRs written.',
      origin: { kind: 'peer-send-message' },
      // A surface with no ctrl+o reports every row expanded.
      isExpanded: true,
      from: { name: '@agent-skills-doc-curator' },
    },
  } as const
  const ui = await $.ui.mount(handBack as never)
  expect((await ui.find({ type: 'Text' }))?.text).toBe('engine: ↩ All 13 ADRs written.')
  await ui.unmount()

  const task = await $.ui.mount({
    ...handBack,
    props: { text: 'Agent "Review Task 13a" finished', origin: { kind: 'task-notification' }, isExpanded: true, task: { status: 'completed' } },
  } as never)
  expect((await task.find({ type: 'Text' }))?.text).toBe('✓ "Review Task 13a" · completed')
  await task.unmount()

  const typed = await $.ui.mount({ ...handBack, props: { ...handBack.props, origin: { kind: 'composer' }, from: undefined } } as never)
  expect((await typed.find({ type: 'Text' }))?.text).toMatch(/^engine: \[Subagent/)
  await typed.unmount()
})

test('an agent in a folded group: nothing while it runs (the pane has it), folded with the group once ended', async ($, on) => {
  mock.clock(on)
  on('ui.render', ($, e) => $.ui.resolve(e).Text({ children: `engine ${e.requestId}` }))
  const call = (id: string, tool: string, tag: string) => ({ id, tool, tag, label: tag, status: 'done' as const })
  const run = { id: 'g-b1', calls: [call('b1', 'Bash', 'Bash'), call('ag1', 'Agent', 'implementer')], isClosed: false }
  const agent = (status: 'running' | 'done') => ({
    id: 'a1',
    toolUseId: 'ag1',
    type: 'agent-skills:implementer',
    description: 'Implement Task 14',
    model: 'claude-sonnet-5-5',
    status,
    startedAt: 0,
    ...(status === 'done' ? { durationMs: 60000 } : {}),
    current: [],
    recent: [],
    counts: {},
  })
  let status: 'running' | 'done' = 'running'
  on('state.get', (_, e, next) =>
    e.key === 'group' && e.id === 'g-b1'
      ? { value: { value: run, version: 1 } }
      : e.key === 'groupOf' && ['b1', 'ag1'].includes(e.id ?? '')
        ? { value: { value: 'g-b1', version: 1 } }
        : e.key === 'byCall' && e.id === 'ag1'
          ? { value: { value: { shape: 'runs-4', value: [agent(status)] }, version: 1 } }
          : next(e),
  )
  const ROW_AGENT = {
    ...ROW,
    requestId: 'ag1',
    props: { ...ROW.props, tool_use_id: 'ag1', tool: 'Agent', input: { subagent_type: 'agent-skills:implementer' } },
  }

  const live = await $.ui.mount({ ...ROW_AGENT, surface: 'vscode' })
  expect(await live.find({ type: 'Text', text: /implementer/ })).toBeUndefined()
  // No tree mark left hanging over an empty row.
  expect(await live.find({ type: 'Text', text: /└/ })).toBeUndefined()
  await live.unmount()

  // Unfolded, a running agent still shows nothing in the chat.
  const header = await $.ui.mount({ ...ROW, requestId: 'b1', props: { ...ROW.props, tool_use_id: 'b1' }, surface: 'vscode' })
  await header.press({ key: 'fold-g-b1' })
  const liveOpen = await $.ui.mount({ ...ROW_AGENT, surface: 'vscode' })
  expect(await liveOpen.find({ type: 'Text', text: /└/ })).toBeUndefined()
  await liveOpen.unmount()

  // Ended and unfolded: the mark opens the card's first line, its mission aligns under it.
  status = 'done'
  const opened = await $.ui.mount({ ...ROW_AGENT, surface: 'vscode' })
  expect((await opened.find({ type: 'Text', text: /^└$/ }))?.text).toBe('└')
  expect((await opened.find({ type: 'Text', text: /Implement Task 14/ }))?.text).toBe('    Implement Task 14')
  await opened.unmount()
  await header.press({ key: 'fold-g-b1' })
  await header.unmount()

  const ended = await $.ui.mount({ ...ROW_AGENT, surface: 'vscode' })
  expect(await ended.find({ type: 'Text', text: /implementer/ })).toBeUndefined()
  await ended.unmount()
})
