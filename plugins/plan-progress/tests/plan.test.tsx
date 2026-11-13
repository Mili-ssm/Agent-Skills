import { expect, test } from 'claude-code/testing'

import { activeTask, bar, cleanPhrase, glyphBar, isPlanPath, parsePlan, progressSvg } from '../hooks/register'

// A plan in the shape Superpowers' writing-plans produces.
const PLAN = `# Login with magic links

## Context
Some prose, no steps.

### Task 1: Token model
- [x] **Step 1: Write the failing test**
- [x] **Step 2: Implement**

### Task 2: Email sender
- [x] **Step 1: Write the failing test**
- [ ] **Step 2: Implement**
- [ ] **Step 3: Commit**

### Task 3: Login route
- [ ] **Step 1: Write the failing test**
`

// The band above the prompt as a surface would mount it.
const BAND = {
  plugin: 'plan-progress',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 4,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 4 },
    view: {},
  },
} as const

test('parsePlan counts steps per task and skips headings without steps', () => {
  const plan = parsePlan('docs/plans/login.md', PLAN)

  expect(plan.title).toBe('Login with magic links')
  expect(plan.tasks.map(task => `${task.title} ${task.done}/${task.total}`)).toEqual([
    'Task 1: Token model 2/2',
    'Task 2: Email sender 1/3',
    'Task 3: Login route 0/1',
  ])
  expect([plan.done, plan.total]).toEqual([3, 6])
})

const row = (task: { title: string; done: number; total: number }): string => `${task.title} ${task.done}/${task.total}`

test('parsePlan keeps the headings shape for a plan with two task headings', () => {
  const plan = parsePlan('docs/plans/a.md', '# A\n### Task 1: Parser\n- [x] Step 1\n- [ ] Step 2\n### Task 2: Card\n- [ ] Step 1\n')
  expect(plan.tasks.map(row)).toEqual(['Task 1: Parser 1/2', 'Task 2: Card 0/1'])
  expect([plan.done, plan.total, plan.unit]).toEqual([1, 3, 'steps'])
  expect(plan.tasks.every(task => task.solo === undefined && task.ticked === undefined)).toBe(true)
})

test('parsePlan reads a task list: top-level checkboxes are tasks, nested ones their subtasks', () => {
  const plan = parsePlan(
    'docs/plans/m.md',
    '# Migration plan\n## Tasks\n- [x] Inventory the endpoints\n- [ ] Migrate the login\n  - [x] move the route\n  - [ ] port the tests\n- [ ] Remove the old client\n',
  )
  expect(plan.tasks.map(row)).toEqual(['Inventory the endpoints 1/1', 'Migrate the login 1/2', 'Remove the old client 0/1'])
  expect([plan.done, plan.total, plan.unit]).toEqual([1, 3, 'tasks'])
  const active = activeTask(plan)
  expect([active?.title, active?.done, active?.total, active?.solo]).toEqual(['Migrate the login', 1, 2, undefined])
  expect(plan.tasks[2]?.solo).toBe(true)
})

test('parsePlan task list: flat list, stale subtasks under a ticked task, indented top level, no heading', () => {
  const flat = parsePlan('p.md', '- [x] one\n- [ ] two\n')
  expect([flat.done, flat.total, flat.tasks.map(row)]).toEqual([1, 2, ['one 1/1', 'two 0/1']])

  const stale = parsePlan('p.md', '- [x] one\n  - [ ] left over\n  - [x] other\n- [ ] two\n')
  expect(stale.tasks.map(row)).toEqual(['one 2/2', 'two 0/1'])
  expect([stale.done, stale.total]).toEqual([1, 2])

  const nested = parsePlan('p.md', '# P\n1. Phase\n   - [x] a\n   - [ ] b\n     - [ ] sub\n\t- [ ] c\n')
  // Top level is the smallest indentation (3), a tab counts as 4: `sub` and `c` are b's subtasks.
  expect(nested.tasks.map(row)).toEqual(['a 1/1', 'b 0/2'])
  expect(nested.total).toBe(2)

  // Subtasks all ticked but the task itself not: still the current task.
  const open = parsePlan('p.md', '- [ ] one\n  - [x] a\n- [ ] two\n')
  expect(activeTask(open)?.title).toBe('one')
  expect(open.done).toBe(0)

  // A plain bullet at task level ends the task above it: the checkboxes under it are tasks, not its subtasks.
  const plain = parsePlan('p.md', '- [x] one\n- Phase 2\n  - [ ] two\n  - [ ] three\n')
  expect(plain.tasks.map(row)).toEqual(['one 1/1', 'two 0/1', 'three 0/1'])
  expect([plain.done, plain.total]).toEqual([1, 3])
  const deeper = parsePlan('p.md', '- [ ] root\n- Group\n  - [ ] g1\n  - Phase 2\n    - [ ] p2a\n')
  expect(deeper.tasks.map(row)).toEqual(['root 0/1', 'g1 0/1', 'p2a 0/1'])

  // Checkboxes inside fenced code are examples, not tasks.
  const fenced = parsePlan('p.md', '- [ ] real\n```md\n- [ ] example\n  - [ ] nested\n```\n')
  expect(fenced.tasks.map(row)).toEqual(['real 0/1'])
})

test('bar and isPlanPath', () => {
  expect(bar(3, 6, 10)).toBe('█████░░░░░')
  expect(bar(0, 0, 4)).toBe('░░░░')
  expect(isPlanPath('/repo/docs/superpowers/plans/2026-10-28-login.md')).toBe(true)
  expect(isPlanPath('/repo/docs/adr/0001.md')).toBe(false)
})

test('glyphBar', () => {
  expect(glyphBar(5, 10, 10)).toBe('▰▰▰▰▰▱▱▱▱▱')
})

test('progressSvg is a continuous line: 1px track, 2px fill by done/total, green when finished', () => {
  const svg = progressSvg(3, 6, 160, '#d97757')
  expect(svg).toContain('class="track" x="0" y="0.5" width="160" height="1"')
  expect(svg).toContain('class="done" x="0" y="0" width="80.00" height="2"')
  expect(svg).toContain('height="1" fill="#d97757" fill-opacity="0.45"')
  expect(svg).not.toContain('#3fb950')
  expect(progressSvg(0, 6, 160, '#d97757')).not.toContain('class="done"')
  expect(progressSvg(4, 4, 160, '#3fb950')).toContain('width="160.00" height="2" rx="1" fill="#3fb950"')
})

test('cards show the newest plan and Haiku\'s remaining line; the status line stays clear; no plan passes', async ($, on) => {
  let files = 1
  const statuses: (string | undefined)[] = []
  // These hooks stand for the engine: one plan folder with one file.
  on('fs.list', (_, e) =>
    e.path.endsWith('/docs/plans') && files > 0
      ? { value: [{ name: 'login.md', kind: 'file', size: 1, mtimeMs: 1, isLink: false }] }
      : { value: [] },
  )
  let text = PLAN
  on('fs.read', () => ({ value: text }))
  on('command.register', () => ({ value: { command: 'plan-progress' } }))
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  let haiku: string | null = 'finish the email sender and the login route'
  on('model.complete', () => ({
    value: haiku === null ? { isAnswered: false, text: '' } : { isAnswered: true, text: `"${haiku}."`, usage: { model: 'claude-haiku-5-5', input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } },
  }) as never)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('turn.complete', () => ({ text: '' }))
  // The engine's own band is empty: what the chain falls to when the card passes.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine band</Text>
  })

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  // Haiku's call is fire and forget: let it land.
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(statuses.at(-1)).toBeUndefined()

  const terminal = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await terminal.find({ type: 'Text', text: /Login/ }))?.text).toBe('Login with magic links')
  expect((await terminal.find({ type: 'Text', text: /3\/6/ }))?.text).toContain('3/6')
  expect((await terminal.find({ type: 'Text', text: /50%/ }))?.text).toContain('50%')
  expect((await terminal.find({ type: 'Text', text: /▰▰▰▰▰▱▱▱▱▱/ }))?.text).toBe('▰▰▰▰▰▱▱▱▱▱')
  expect((await terminal.find({ type: 'Text', text: /▶/ }))?.text).toBe('▶ finish the email sender and the login route')
  await terminal.unmount()

  const desktop = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await desktop.find({ type: 'Svg' }))?.props.alt).toBe('3 of 6 steps done')
  expect((await desktop.find({ type: 'Text', text: /Login/ }))?.text).toBe('Login with magic links')
  expect((await desktop.find({ type: 'Text', text: /▶/ }))?.text).toContain('finish the email sender')
  await desktop.unmount()
  expect(statuses.every(status => status === undefined)).toBe(true)

  // Haiku not answering: the active task line stays.
  haiku = null
  text = PLAN.replace('- [ ] **Step 2: Implement**', '- [x] **Step 2: Implement**')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await new Promise(resolve => setTimeout(resolve, 0))
  const fallback = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await fallback.find({ type: 'Text', text: /▶/ }))?.text).toBe('▶ Task 2: Email sender · 2/3')
  await fallback.unmount()

  // The chain passes (nothing beneath draws) when a survey is up, or there is no plan.
  files = 0
  await $.turn.complete({
    answer: 'ok',
    durationMs: 1,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
    usage: { model: 'm', input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
  })
  expect(statuses.at(-1)).toBeUndefined()
  const survey = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true }, surface: 'terminal' })
  expect((await survey.find({ type: 'Text' }))?.text).toBe('engine band')
  await survey.unmount()
  const empty = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await empty.find({ type: 'Text' }))?.text).toBe('engine band')
  await empty.unmount()
})

test('cleanPhrase keeps the first line and drops thinking aloud', () => {
  expect(cleanPhrase('Spike de densidad, luego spec v7.4.\n\nLet me count words: ...')).toBe('Spike de densidad, luego spec v7.4')
  expect(cleanPhrase('"Cerrar R1-T2."')).toBe('Cerrar R1-T2')
  expect(cleanPhrase('Let me count the words first')).toBe('')
  expect(cleanPhrase('')).toBe('')
})
