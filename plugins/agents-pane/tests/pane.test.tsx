import { expect, test } from 'claude-code/testing'

// The pane as a surface would mount it.
const PANE = {
  plugin: 'agents-pane',
  component: 'Pane',
  requestId: 'agents-pane',
  props: {
    title: 'Agents',
    isFocused: false,
    bodyColumns: 50,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
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

test('a spawned agent is listed running, then done with its duration', async ($, on) => {
  // These hooks stand for the engine beneath the mod.
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: 'a1' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('turn.complete', () => ({ text: '' }))

  await $.agent.spawn(SPAWN)

  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /Explore/ }))?.text).toBe('… Explore · haiku-5-5')
    expect((await ui.find({ type: 'Text', text: /running/ }))?.text).toBe('1 running · haiku 1')
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

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /Explore/ }))?.text).toBe('✓ Explore · haiku-5-5 · 1m15s')
  expect((await ui.find({ type: 'Text', text: /running/ }))?.text).toBe('0 running · haiku 1')
  await ui.unmount()
})

test('a refused spawn adds no row', async ($, on) => {
  on('agent.spawn', () => ({ deny: 'not allowed' }))

  await $.agent.spawn(SPAWN)

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('No subagents yet.')
  await ui.unmount()
})
