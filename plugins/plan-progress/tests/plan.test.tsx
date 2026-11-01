import { expect, test } from 'claude-code/testing'

import { bar, glyphBar, isPlanPath, parsePlan, progressSvg, statusLine } from '../hooks/register'

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

test('bar and isPlanPath', () => {
  expect(bar(3, 6, 10)).toBe('█████░░░░░')
  expect(bar(0, 0, 4)).toBe('░░░░')
  expect(isPlanPath('/repo/docs/superpowers/plans/2026-10-28-login.md')).toBe(true)
  expect(isPlanPath('/repo/docs/adr/0001.md')).toBe(false)
})

test('glyphBar and statusLine', () => {
  expect(glyphBar(5, 10, 10)).toBe('▰▰▰▰▰▱▱▱▱▱')
  expect(statusLine(parsePlan('p.md', PLAN))).toBe('▰▰▰▰▰▱▱▱▱▱ 3/6 · ▶ Task 2: Email sender 1/3')
  expect(statusLine(parsePlan('p.md', '# Done\n## T\n- [x] a\n'))).toBe('✓ Done 1/1')
})

test('progressSvg fills done/total steps left to right, green when finished', () => {
  const svg = progressSvg(3, 6, 100, 6, '#d97757')
  expect(svg).toContain('class="track" x="0" y="0" width="100"')
  expect(svg).toContain('class="done" x="0" y="0" width="50.00"')
  expect(svg).not.toContain('#3fb950')
  expect(progressSvg(0, 6, 100, 6, '#d97757')).not.toContain('class="done"')
  expect(progressSvg(4, 4, 100, 6, '#3fb950')).toContain('width="100.00" height="6" rx="3" fill="#3fb950"')
})

test('status line only without a card (vscode); terminal and desktop cards show the newest plan; no plan passes', async ($, on) => {
  let files = 1
  const statuses: (string | undefined)[] = []
  // These hooks stand for the engine: one plan folder with one file.
  on('fs.list', (_, e) =>
    e.path.endsWith('/docs/plans') && files > 0
      ? { value: [{ name: 'login.md', kind: 'file', size: 1, mtimeMs: 1, isLink: false }] }
      : { value: [] },
  )
  on('fs.read', () => ({ value: PLAN }))
  on('command.register', () => ({ value: { command: 'plan-progress' } }))
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  let surfaces: ('desktop' | 'vscode')[] = ['desktop']
  on('session.surfaces', () => ({ value: surfaces }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('turn.complete', () => ({ text: '' }))
  // The engine's own band is empty: what the chain falls to when the card passes.
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine band</Text>
  })

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  // The card draws on desktop and terminal: no status line to duplicate it.
  expect(statuses.at(-1)).toBeUndefined()

  const terminal = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await terminal.find({ type: 'Text', text: /Login/ }))?.text).toBe('Login with magic links')
  expect((await terminal.find({ type: 'Text', text: /3\/6/ }))?.text).toContain('3/6')
  expect((await terminal.find({ type: 'Text', text: /50%/ }))?.text).toContain('50%')
  expect((await terminal.find({ type: 'Text', text: /▰▰▰▰▰▱▱▱▱▱/ }))?.text).toBe('▰▰▰▰▰▱▱▱▱▱')
  expect((await terminal.find({ type: 'Text', text: /▶/ }))?.text).toBe('▶ Task 2: Email sender · 1/3')
  await terminal.unmount()

  const desktop = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await desktop.find({ type: 'Svg' }))?.props.alt).toBe('3 of 6 steps done')
  expect((await desktop.find({ type: 'Text', text: /Login/ }))?.text).toBe('Login with magic links')
  expect((await desktop.find({ type: 'Text', text: /▶/ }))?.text).toContain('Task 2: Email sender')
  await desktop.unmount()

  // VS Code draws no card: the status line is its display.
  surfaces = ['vscode']
  await $.session.start({ cwd: '/', surface: 'vscode', isInteractive: true })
  expect(statuses.at(-1)).toBe('▰▰▰▰▰▱▱▱▱▱ 3/6 · ▶ Task 2: Email sender 1/3')

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
