import { expect, test } from 'claude-code/testing'

import { bar, formatDuration, formatTally, formatTokens } from '../hooks/register'

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
  expect(bar(50, 100)).toBe('▇▇▇▁▁')
  expect(bar(100, 100)).toBe('▇▇▇▇▇')
  expect(bar(1, 100)).toBe('▇▁▁▁▁')
})

const complete = (init: { agentId?: string; durationMs: number; turnId: string; model: string; input: number; output: number }) => ({
  ...(init.agentId === undefined ? {} : { agentId: init.agentId }),
  answer: 'done',
  durationMs: init.durationMs,
  isAborted: false,
  turnId: init.turnId,
  reason: 'answer' as const,
  usage: usage(init.model, init.input, init.output),
})

test('an answer logs one line with its duration and the tokens of the main loop and its subagents', async ($, on) => {
  const lines: string[] = []
  // These hooks stand for the engine beneath the mod.
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.log', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })

  await $.turn.start({ text: 'Plan the login feature', turnId: 't1' })
  // A Haiku subagent ends inside the answer: no line yet...
  await $.turn.complete(complete({ agentId: 'a1', durationMs: 9000, turnId: 's1', model: 'claude-haiku-5-5', input: 100000, output: 8000 }))
  expect(lines).toEqual([])
  // ...then the main loop's answer closes it.
  await $.turn.complete(complete({ durationMs: 75000, turnId: 't1', model: 'claude-opus-5-5', input: 40000, output: 3000 }))

  expect(lines).toEqual(['⏱ 1m15s · haiku ▇▇▇▇▇ 108k · opus ▇▇▁▁▁ 43k │ Σ 1m15s · 151k'])

  // The summary command answers with the session so far.
  const { text } = await $.command.run({ command: 'usage-band' })
  expect(text).toBe(
    [
      'Session: 1m15s over 1 answers · 151k tokens',
      'haiku    ▇▇▇▇▇  108k (8k out) 72%',
      'opus     ▇▇▁▁▁   43k (3k out) 28%',
    ].join('\n'),
  )
})

test('a subagent-only turn end logs nothing', async ($, on) => {
  const lines: string[] = []
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.log', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })

  await $.turn.complete(complete({ agentId: 'a1', durationMs: 5000, turnId: 's1', model: 'claude-haiku-5-5', input: 1000, output: 100 }))
  expect(lines).toEqual([])
})
