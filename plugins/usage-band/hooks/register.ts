import { atom, read, update } from 'claude-code'
import type { Register, TurnUsage } from 'claude-code'

import type { Tally, Usage } from '../types'

// The slash command that answers with the session summary.
const COMMAND = 'usage-band'
const EMPTY: Usage = { durationMs: 0, turns: 0, byModel: {} }
// Bump the shape tags when Usage's fields change: older stored values are then read as absent.
const session = atom({ plugin: 'usage-band', key: 'session' } as const, EMPTY, {
  shape: 'usage-1',
})
// Cells of a family's mini bar, and the levels a cell can show (empty to full).
const CELLS = 5
const LEVELS = '▁▂▃▄▅▆▇█'
// Families named on the footer line before `+n`.
const MAX_SHOWN = 4

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

/** A `CELLS`-wide bar: `tokens` against `max` (the biggest), at least one filled cell, `▇` full and `▁` empty. */
export function bar(tokens: number, max: number): string {
  const filled = max <= 0 ? 0 : Math.min(CELLS, Math.max(1, Math.round((tokens / max) * CELLS)))
  return '▇'.repeat(filled) + '▁'.repeat(CELLS - filled)
}

/** Total tokens of a tally. */
export function sumTokens(tally: Tally): number {
  return Object.values(tally).reduce((sum, tokens) => sum + tokens.total, 0)
}

/** `⏱ 1m15s · opus ▇▇▇▁▁ 43k · haiku ▇▇▇▇▇ 108k │ Σ 12m · 1.2M`; families biggest first, then `+n`. */
export function formatLine(answer: Usage, total: Usage): string {
  const rows = Object.entries(answer.byModel).sort(([, a], [, b]) => b.total - a.total)
  const max = rows[0]?.[1].total ?? 0
  const shown = rows.slice(0, MAX_SHOWN).map(([name, t]) => `${name} ${bar(t.total, max)} ${formatTokens(t.total)}`)
  if (rows.length > MAX_SHOWN) {
    shown.push(`+${rows.length - MAX_SHOWN}`)
  }
  return `⏱ ${formatDuration(answer.durationMs)} · ${shown.join(' · ')} │ Σ ${formatDuration(total.durationMs)} · ${formatTokens(sumTokens(total.byModel))}`
}

/** Multi-line session summary: per family its total, output, share of the session and a bar. */
export function formatSummary(total: Usage): string {
  const rows = Object.entries(total.byModel).sort(([, a], [, b]) => b.total - a.total)
  const all = sumTokens(total.byModel)
  const head = `Session: ${formatDuration(total.durationMs)} over ${total.turns} answers · ${formatTokens(all)} tokens`
  if (rows.length === 0) {
    return `${head}\nno tokens yet`
  }
  const max = rows[0]?.[1].total ?? 0
  const lines = rows.map(([name, t]) => {
    const share = all === 0 ? 0 : Math.round((t.total / all) * 100)
    return `${name.padEnd(8)} ${bar(t.total, max)} ${formatTokens(t.total).padStart(5)} (${formatTokens(t.output)} out) ${share}%`
  })
  return [head, ...lines].join('\n')
}

export const register: Register = on => {
  // Tokens of the answer in progress: the main loop's and every subagent's that ends meanwhile.
  // Module state: a hot reload mid-answer only loses that answer's partial count.
  let current: Tally = {}

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: COMMAND,
      description: 'Show the session summary: time and tokens per model',
    })

    return started
  })

  on('command.run', { command: COMMAND }, async $ => ({ text: formatSummary(await read($, session)) }))

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
      const total = await update($, session, before => ({
        durationMs: before.durationMs + answer.durationMs,
        turns: before.turns + 1,
        byModel: mergeTallies(before.byModel, answer.byModel),
      }))
      // A dim row under the answer; surfaces without an above-prompt band draw it too.
      if (sumTokens(answer.byModel) > 0) {
        $.ui.log(formatLine(answer, total))
      }
      current = {}
    }

    return next(e)
  })
}
