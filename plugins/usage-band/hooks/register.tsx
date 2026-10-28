import { atom, read, update } from 'claude-code'
import type { Register, TurnUsage } from 'claude-code'

import type { Tally, Usage } from '../types'

// The slash command that shows the band again after "Hide".
const COMMAND = 'usage-band'
const EMPTY: Usage = { durationMs: 0, turns: 0, byModel: {} }
// Bump the shape tags when Usage's fields change: older stored values are then read as absent.
const last = atom({ plugin: 'usage-band', key: 'last' } as const, null, { shape: 'usage-1' })
const session = atom({ plugin: 'usage-band', key: 'session' } as const, EMPTY, {
  shape: 'usage-1',
})
const isHidden = atom({ plugin: 'usage-band', key: 'isHidden' } as const, false)

/** Model family for grouping: `claude-haiku-5-5` → `haiku`. */
export function family(model: string): string {
  return /haiku|sonnet|opus|fable/.exec(model)?.[0] ?? model.replace(/^claude-/, '')
}

/** Adds one turn's token usage to a tally (returns a new tally). */
export function addUsage(tally: Tally, usage: TurnUsage): Tally {
  const name = family(usage.model)
  const before = tally[name] ?? { total: 0, output: 0 }
  const total =
    usage.input_tokens +
    usage.cache_read_input_tokens +
    usage.cache_creation_input_tokens +
    usage.output_tokens
  return {
    ...tally,
    [name]: { total: before.total + total, output: before.output + usage.output_tokens },
  }
}

/** Sums two tallies (returns a new tally). */
export function mergeTallies(a: Tally, b: Tally): Tally {
  const merged: Tally = { ...a }
  for (const [name, tokens] of Object.entries(b)) {
    const before = merged[name] ?? { total: 0, output: 0 }
    merged[name] = { total: before.total + tokens.total, output: before.output + tokens.output }
  }
  return merged
}

/** 950 → `950`, 12345 → `12k`, 1234567 → `1.2M`. */
export function formatTokens(count: number): string {
  if (count < 1000) {
    return `${count}`
  }
  if (count < 1_000_000) {
    return `${Math.round(count / 1000)}k`
  }
  return `${(count / 1_000_000).toFixed(1)}M`
}

/** 8400 → `8s`, 75000 → `1m15s`, 3725000 → `1h02m`. */
export function formatDuration(ms: number): string {
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) {
    return `${seconds}s`
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m${String(seconds % 60).padStart(2, '0')}s`
  }
  return `${Math.floor(seconds / 3600)}h${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}m`
}

/** `opus 45k (3k out) · haiku 120k (8k out)`, biggest first. */
export function formatTally(tally: Tally): string {
  const rows = Object.entries(tally).sort(([, a], [, b]) => b.total - a.total)
  if (rows.length === 0) {
    return 'no tokens'
  }
  return rows
    .map(([name, tokens]) => `${name} ${formatTokens(tokens.total)} (${formatTokens(tokens.output)} out)`)
    .join(' · ')
}

export const register: Register = on => {
  // Tokens of the answer in progress: the main loop's and every subagent's that ends meanwhile.
  // Module state: a hot reload mid-answer only loses that answer's partial count.
  let current: Tally = {}

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: COMMAND,
      description: 'Show the usage band again (last answer and session: time and tokens per model)',
    })

    return started
  })

  on('command.run', { command: COMMAND }, async $ => {
    await update($, isHidden, () => false)

    return { text: 'Usage band shown.' }
  })

  // A new answer starts on the main loop: count from zero.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      current = {}
    }

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.usage !== undefined) {
      current = addUsage(current, e.usage)
    }
    // Only the main loop's end closes an answer; a subagent's end just adds its tokens.
    if (e.agentId === undefined) {
      const answer: Usage = { durationMs: e.durationMs, turns: 1, byModel: current }
      await update($, last, () => answer)
      await update($, session, total => ({
        durationMs: total.durationMs + answer.durationMs,
        turns: total.turns + 1,
        byModel: mergeTallies(total.byModel, answer.byModel),
      }))
      current = {}
    }

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const answer = await read($, last)
    // Stay out of the way of surveys, before the first answer, and when hidden.
    if (e.props.hasSurvey || answer === null || (await read($, isHidden))) {
      return next(e)
    }
    const total = await read($, session)
    const { Box, Button, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="column">
        <Text dimColor>
          Last answer {formatDuration(answer.durationMs)} · {formatTally(answer.byModel)}
        </Text>
        <Box>
          <Text dimColor>
            Session {formatDuration(total.durationMs)} over {total.turns} answers ·{' '}
            {formatTally(total.byModel)}{' '}
          </Text>
          <Button key="hide" label="Hide" onPress={() => update($, isHidden, () => true)} />
        </Box>
      </Box>
    )
  })
}
