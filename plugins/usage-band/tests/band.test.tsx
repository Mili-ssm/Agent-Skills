import { expect, test } from 'claude-code/testing'

import { formatDuration, formatTally, formatTokens } from '../hooks/register'

// The band as a surface would mount it.
const BAND = {
  plugin: 'usage-band',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 4,
    bodyColumns: 120,
    scroll: { offset: 0, bodyRows: 4 },
    view: {},
  },
} as const

// Token usage as a turn reports it.
const usage = (model: string, input: number, output: number) => ({
  model,
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: 0,
  cache_creation_input_tokens: 0,
})

test('formatters', () => {
  expect(formatTokens(950)).toBe('950')
  expect(formatTokens(12345)).toBe('12k')
  expect(formatTokens(1234567)).toBe('1.2M')
  expect(formatDuration(8400)).toBe('8s')
  expect(formatDuration(75000)).toBe('1m15s')
  expect(formatDuration(3725000)).toBe('1h02m')
  expect(formatTally({})).toBe('no tokens')
})

test('an answer shows its duration and the tokens of the main loop and its subagents', async ($, on) => {
  // These hooks stand for the engine beneath the mod.
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))

  await $.turn.start({ text: 'Plan the login feature', turnId: 't1' })
  // A Haiku subagent ends inside the answer...
  await $.turn.complete({
    agentId: 'a1',
    answer: 'found it',
    durationMs: 9000,
    isAborted: false,
    turnId: 's1',
    reason: 'answer',
    usage: usage('claude-haiku-5-5', 100000, 8000),
  })
  // ...then the main loop's answer closes it.
  await $.turn.complete({
    answer: 'Here is the plan',
    durationMs: 75000,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
    usage: usage('claude-opus-5-5', 40000, 3000),
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    expect((await ui.find({ type: 'Text', text: /Last answer/ }))?.text).toBe(
      'Last answer 1m15s · haiku 108k (8k out) · opus 43k (3k out)',
    )
    expect((await ui.find({ type: 'Text', text: /Session/ }))?.text).toContain('Session 1m15s over 1 answers')
    await ui.unmount()
  }
})
