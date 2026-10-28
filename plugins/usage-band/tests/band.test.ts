import { expect, mock, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

import { bar, formatCycle, formatDuration, formatLine, formatTally, formatTokens } from '../hooks/register'
import type { Cycle } from '../types'

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

test('cycle formatters', () => {
  const cycle: Cycle = {
    byModel: { opus: { total: 1_200_000, output: 20_000 }, sonnet: { total: 257_000, output: 7000 } },
    startedAt: 0,
    calls: 62,
    skills: 2,
    agents: 3,
  }
  expect(formatCycle(cycle, 192_000)).toBe('⏱ 3m12s · opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k · 62 calls · 2 skills · 3 agents')
  expect(formatLine(cycle, 192_000, { durationMs: 2_290_000, turns: 9, byModel: { opus: { total: 41_700_000, output: 0 } } })).toBe(
    '⏱ 3m12s · opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k · 62 calls · 2 skills · 3 agents │ Σ 38m10s · 41.7M',
  )
  // Zero counts are left out, a single one is singular, and no tokens leaves just the time.
  expect(formatCycle({ ...cycle, byModel: {}, calls: 1, skills: 0, agents: 0 }, 4000)).toBe('⏱ 4s · 1 call')
})

type On = Parameters<TestBody>[1]

// A turn ending as the engine reports it.
const complete = (init: { agentId?: string; durationMs: number; turnId: string; model: string; input: number; output: number }) => ({
  ...(init.agentId === undefined ? {} : { agentId: init.agentId }),
  answer: 'done',
  durationMs: init.durationMs,
  isAborted: false,
  turnId: init.turnId,
  reason: 'answer' as const,
  usage: usage(init.model, init.input, init.output),
})

// A submitted prompt as the engine raises it, `origin` saying who it came from.
const prompt = (text: string, origin: { kind: string; [key: string]: unknown } = { kind: 'composer' }, extra: object = {}) =>
  ({ text, wait: false, origin, ...extra }) as never

// The engine beneath the mod, recording the log rows and status lines it is asked to draw; time stands still until the test moves it.
function engine(on: On) {
  const lines: string[] = []
  const statuses: (string | undefined)[] = []
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('tool.call', () => ({ result: {} }))
  on('ui.log', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  return { lines, statuses, clock: mock.clock(on) }
}

test('a cycle runs on the wall clock from one prompt to the next, waits on agents included', async ($, on) => {
  const { lines, statuses, clock } = engine(on)

  // The person's first prompt: nothing to close yet; the clock starts.
  await $.prompt.submit(prompt('Plan the login feature'))
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('⏱ 0s')

  // First main turn: the line moves once a second.
  await $.turn.start({ text: 'Plan the login feature', turnId: 't1' })
  await clock.advance(3000)
  expect(statuses.at(-1)).toBe('⏱ 3s')
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  await $.tool.call({ tool: 'Bash', command: 'pwd' })
  await $.tool.call({ tool: 'Skill', skill: 'plan' })
  await $.tool.call({ tool: 'Agent', description: 'Explore', prompt: 'Look around', subagent_type: 'Explore' })
  await $.tool.call({ tool: 'Agent', description: 'Review', prompt: 'Review it', subagent_type: 'Explore' })
  // A subagent's own calls count too.
  await $.tool.call({ tool: 'Bash', command: 'cat a', agentId: 'a1' })
  expect(statuses.at(-1)).toBe('⏱ 3s · 6 calls · 1 skill · 2 agents')
  await clock.advance(117_000)
  await $.turn.complete(complete({ durationMs: 120_000, turnId: 't1', model: 'claude-opus-5-5', input: 700_000, output: 10_000 }))
  expect(statuses.at(-1)).toBe('⏱ 2m00s · opus ▇▇▇▇▇ 710k · 6 calls · 1 skill · 2 agents')

  // The main loop is idle while a background agent works: the clock goes on.
  await clock.advance(600_000)
  expect(statuses.at(-1)).toBe('⏱ 12m00s · opus ▇▇▇▇▇ 710k · 6 calls · 1 skill · 2 agents')
  // The agent ends meanwhile: its tokens join the cycle.
  await $.turn.complete(complete({ agentId: 'a1', durationMs: 90_000, turnId: 's1', model: 'claude-sonnet-5-5', input: 250_000, output: 7000 }))
  expect(statuses.at(-1)).toBe('⏱ 12m00s · opus ▇▇▇▇▇ 710k · sonnet ▇▇▁▁▁ 257k · 6 calls · 1 skill · 2 agents')

  // Its hand-back wakes the model: machine-made prompts (a task notification and the like) start no cycle.
  const machine = [
    prompt('<task-notification>agent done</task-notification>', { kind: 'task-notification' }),
    prompt('wake up', { kind: 'scheduled-trigger' }),
    prompt('hello from a peer', { kind: 'peer' }),
    prompt('from a plugin', { kind: 'plugin', name: 'other', asUser: true }),
    prompt('queued by the engine', { kind: 'unclassified' }),
    prompt('not shown as typed', { kind: 'composer' }, { isMeta: true }),
    prompt('/usage-band', { kind: 'composer' }, { command: { name: 'usage-band', args: '' } }),
  ]
  for (const submission of machine) {
    await $.prompt.submit(submission)
  }
  expect(lines).toEqual([])
  await $.turn.start({ text: '', turnId: 't2' })
  await clock.advance(72_000)
  await $.tool.call({ tool: 'Read', file_path: '/tmp/a.ts' })
  await $.turn.complete(complete({ durationMs: 72_000, turnId: 't2', model: 'claude-opus-5-5', input: 480_000, output: 10_000 }))
  expect(lines).toEqual([])
  // Done, waiting on the person: the clock still says how long since they wrote.
  await clock.advance(60_000)
  expect(statuses.at(-1)).toBe('⏱ 14m12s · opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k · 7 calls · 1 skill · 2 agents')

  // /usage-band: the current cycle on top, then the session, the open cycle's time included.
  const { text } = await $.command.run({ command: 'usage-band' } as never)
  expect(text).toBe(
    [
      'Current cycle: ⏱ 14m12s · opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k · 7 calls · 1 skill · 2 agents',
      'Session: 14m12s over 2 answers · 1.5M tokens',
      'opus     ▇▇▇▇▇  1.2M (20k out) 82%',
      'sonnet   ▇▁▁▁▁  257k (7k out) 18%',
    ].join('\n'),
  )

  // The person's next prompt closes the cycle: its one line goes in first, then the new cycle starts at 0.
  await $.prompt.submit(prompt('Now implement it'))
  expect(lines).toEqual([
    '⏱ 14m12s · opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k · 7 calls · 1 skill · 2 agents │ Σ 14m12s · 1.5M',
  ])
  expect(statuses.at(-1)).toBe('⏱ 0s')

  // The second cycle, short: its line carries the session's running total.
  await $.turn.start({ text: 'Now implement it', turnId: 't3' })
  await clock.advance(5000)
  await $.turn.complete(complete({ durationMs: 5000, turnId: 't3', model: 'claude-opus-5-5', input: 40_000, output: 2000 }))
  expect(statuses.at(-1)).toBe('⏱ 5s · opus ▇▇▇▇▇ 42k')
  await $.prompt.submit(prompt('Thanks', { kind: 'bridge' }))
  expect(lines).toHaveLength(2)
  expect(lines[1]).toBe('⏱ 5s · opus ▇▇▇▇▇ 42k │ Σ 14m17s · 1.5M')
})

test('a cycle without tokens logs no line', async ($, on) => {
  const { lines } = engine(on)

  await $.prompt.submit(prompt('Just a question'))
  await $.prompt.submit(prompt('Another'))
  expect(lines).toEqual([])
})

test('a prompt typed over a running turn starts the new cycle at that moment', async ($, on) => {
  const { lines, statuses, clock } = engine(on)

  await $.prompt.submit(prompt('Start'))
  await $.turn.start({ text: 'Start', turnId: 't1' })
  await clock.advance(10_000)
  await $.prompt.submit(prompt('Actually, do this instead'))
  // Nothing finished yet, so no line; the new cycle's time counts from its prompt.
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('⏱ 0s')
  await clock.advance(4000)
  expect(statuses.at(-1)).toBe('⏱ 4s')
  await $.turn.complete(complete({ durationMs: 14_000, turnId: 't1', model: 'claude-haiku-5-5', input: 1000, output: 200 }))
  expect(statuses.at(-1)).toBe('⏱ 4s · haiku ▇▇▇▇▇ 1k')
})

test('a subagent-only turn end before any prompt shows in the status line and logs nothing', async ($, on) => {
  const { lines, statuses } = engine(on)

  await $.turn.complete(complete({ agentId: 'a1', durationMs: 5000, turnId: 's1', model: 'claude-haiku-5-5', input: 1000, output: 100 }))
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('⏱ 0s · haiku ▇▇▇▇▇ 1k')
})
