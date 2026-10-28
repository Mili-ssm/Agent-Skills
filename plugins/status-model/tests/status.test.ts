import { expect, test } from 'claude-code/testing'

// A spawn as the engine raises it for a model's Agent call.
const SPAWN = {
  tool_use_id: 'tu1',
  prompt: 'Research htmx error swapping',
  description: 'Research htmx',
  subagentType: 'agent-skills:researcher',
  provider: { plugin: 'agent-skills', tier: 'append' },
  parentModel: 'claude-opus-5-5',
  background: false,
  fork: false,
} as const

test('the line shows the main model, then the running and last subagent', async ($, on) => {
  // These hooks stand for the engine; `ui.status` records what the mod pins.
  let line: string | undefined
  on('ui.status', (_, e) => {
    line = e.text
    return { value: undefined }
  })
  on('session.model', () => ({ value: 'claude-opus-5-5' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: 'a1' }))
  on('turn.complete', () => ({ text: '' }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(line).toBe('opus-5-5')

  await $.agent.spawn(SPAWN)
  expect(line).toBe('opus-5-5 │ 1 running │ last: researcher → haiku-5-5 …')

  await $.turn.complete({
    agentId: 'a1',
    answer: 'done',
    durationMs: 12000,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
  })
  expect(line).toBe('opus-5-5 │ last: researcher → haiku-5-5 ✓ 12s')
})
