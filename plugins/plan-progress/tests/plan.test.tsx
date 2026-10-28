import { expect, test } from 'claude-code/testing'

import { bar, isPlanPath, parsePlan } from '../hooks/register'

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

// The pane as a surface would mount it.
const PANE = {
  plugin: 'plan-progress',
  component: 'Pane',
  requestId: 'plan-progress',
  props: {
    title: 'Plan',
    isFocused: false,
    bodyColumns: 40,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
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

test('the pane shows the newest plan with the active task, on every surface', async ($, on) => {
  // These hooks stand for the engine: one plan folder with one file.
  on('fs.list', (_, e) =>
    e.path.endsWith('/docs/plans')
      ? { value: [{ name: 'login.md', kind: 'file', size: 1, mtimeMs: 1, isLink: false }] }
      : { value: [] },
  )
  on('fs.read', () => ({ value: PLAN }))
  on('command.register', () => ({ value: { command: 'plan-progress' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /▶/ }))?.text).toBe('▶ Task 2: Email sender 1/3')
    expect((await ui.find({ type: 'Text', text: /\(50%\)/ }))?.text).toContain('3/6 (50%)')
    await ui.unmount()
  }
})
