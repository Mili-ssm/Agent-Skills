import { atom, read, update } from 'claude-code'
import type { EngineInterface, PromptOrigin, Register, Timer, TurnUsage } from 'claude-code'

import type { Cycle, Tally, Usage } from '../types'

// The slash command that answers with the session summary.
const COMMAND = 'usage-band'
const EMPTY: Usage = { durationMs: 0, turns: 0, byModel: {} }
// Bump the shape tags when Usage's fields change: older stored values are then read as absent.
const session = atom({ plugin: 'usage-band', key: 'session' } as const, EMPTY, {
  shape: 'usage-1',
})
const EMPTY_CYCLE: Cycle = { byModel: {}, busyMs: 0, runningSince: null, tools: 0, skills: 0, agents: 0 }
// The interaction cycle in progress: from the person's last prompt on (see `isPersonPrompt`).
const cycleAtom = atom({ plugin: 'usage-band', key: 'cycle' } as const, EMPTY_CYCLE, {
  shape: 'cycle-1',
})
// The live status line redraws this often while a main-loop turn runs.
const TICK_MS = 1000
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

/** Pluralised count: `1 tool`, `14 tools`. */
function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : 's'}`
}

/** `opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k`; families biggest first, then `+n`. Empty for an empty tally. */
export function formatModels(byModel: Tally): string[] {
  const rows = Object.entries(byModel).sort(([, a], [, b]) => b.total - a.total)
  const max = rows[0]?.[1].total ?? 0
  const shown = rows.slice(0, MAX_SHOWN).map(([name, t]) => `${name} ${bar(t.total, max)} ${formatTokens(t.total)}`)
  if (rows.length > MAX_SHOWN) {
    shown.push(`+${rows.length - MAX_SHOWN}`)
  }
  return shown
}

/** Busy time of a cycle: its finished turns plus the running turn so far (`now` is read only while one runs). */
export function elapsedMs(cycle: Cycle, now: number): number {
  return Math.max(0, cycle.busyMs + (cycle.runningSince === null ? 0 : now - cycle.runningSince))
}

/** True once a cycle has anything to show: a running turn, time, tokens or counted calls. */
export function hasActivity(cycle: Cycle): boolean {
  return (
    cycle.runningSince !== null ||
    cycle.busyMs !== 0 ||
    cycle.tools + cycle.skills + cycle.agents > 0 ||
    sumTokens(cycle.byModel) > 0
  )
}

/** `⏱ 3m12s · opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k · 14 tools · 2 skills · 3 agents`; zero counts left out. */
export function formatCycle(cycle: Cycle, elapsed: number): string {
  const counts = [
    [cycle.tools, 'tool'],
    [cycle.skills, 'skill'],
    [cycle.agents, 'agent'],
  ] as const
  const parts = [
    `⏱ ${formatDuration(elapsed)}`,
    ...formatModels(cycle.byModel),
    ...counts.filter(([n]) => n > 0).map(([n, noun]) => count(n, noun)),
  ]
  return parts.join(' · ')
}

/** The cycle's line then `│ Σ 38m10s · 41.7M` (the session's busy time and tokens). */
export function formatLine(cycle: Cycle, elapsed: number, total: Usage): string {
  return `${formatCycle(cycle, elapsed)} │ Σ ${formatDuration(total.durationMs)} · ${formatTokens(sumTokens(total.byModel))}`
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

/**
 * True for a prompt the person typed (`origin.kind` `composer`, or `bridge` for their phone or web client)
 * and that is not marked `isMeta`; notifications, peers, schedules, plugins, the SDK host and the like are
 * machine-made and do not start a cycle. The usage command's own line does not either.
 */
export function isPersonPrompt(e: { origin: PromptOrigin; isMeta?: true; command?: { name: string } }): boolean {
  const kind = e.origin.kind
  return (kind === 'composer' || kind === 'bridge') && e.isMeta !== true && e.command?.name !== COMMAND
}

/** The cycle that follows `cycle` when the person submits a prompt at `now`. */
function nextCycle(cycle: Cycle, now: number): Cycle {
  // A turn still running (the person typed over it) goes on into the new cycle, counted from this prompt.
  const carried = cycle.runningSince === null ? 0 : -(now - cycle.runningSince)
  return { ...EMPTY_CYCLE, busyMs: carried, runningSince: cycle.runningSince }
}

// Module state, lost on a hot reload: `session.start` restarts the tick, and the next publish resends the status.
let tick: Timer | undefined
// The status line as last sent (`undefined`: cleared), so it is sent only when its text changed.
let lastStatus: string | undefined

/** Draws the cycle on the status line, if its text changed. Never throws. */
async function publish($: EngineInterface): Promise<void> {
  try {
    const cycle = await read($, cycleAtom)
    const now = cycle.runningSince === null ? 0 : await $.clock.now()
    const text = hasActivity(cycle) ? formatCycle(cycle, elapsedMs(cycle, now)) : undefined
    if (text !== lastStatus) {
      lastStatus = text
      $.ui.status(text)
    }
  } catch (error) {
    $.ui.log(`usage-band: ${String(error)}`, { to: 'debug' })
  }
}

/** Starts the one-second redraw that moves the elapsed time; it runs only while a main-loop turn does. */
function startTick($: EngineInterface): void {
  tick ??= $.clock.every(TICK_MS, () => {
    void publish($)
  })
}

function stopTick(): void {
  tick?.cancel()
  tick = undefined
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: COMMAND,
      description: 'Show the current cycle and the session summary: time and tokens per model',
    })
    // After a hot reload the timer is gone: a turn that is still running needs it again.
    if ((await read($, cycleAtom)).runningSince !== null) {
      startTick($)
    }
    await publish($)

    return started
  })

  on('session.end', async ($, e, next) => {
    const ended = await next(e)
    stopTick()
    await update($, cycleAtom, () => EMPTY_CYCLE)
    await publish($)

    return ended
  })

  on('command.run', { command: COMMAND }, async $ => {
    const cycle = await read($, cycleAtom)
    const now = cycle.runningSince === null ? 0 : await $.clock.now()
    const line = hasActivity(cycle) ? formatCycle(cycle, elapsedMs(cycle, now)) : 'nothing yet'

    return { text: `Current cycle: ${line}\n${formatSummary(await read($, session))}` }
  }).catch(($, e, next) => next(e))

  // The person's prompt closes the cycle before it: its line goes in first, so the row lands above their message.
  on('prompt.submit', async ($, e, next) => {
    if (isPersonPrompt(e)) {
      const now = await $.clock.now()
      const cycle = await read($, cycleAtom)
      if (sumTokens(cycle.byModel) > 0) {
        $.ui.log(formatLine(cycle, elapsedMs(cycle, now), await read($, session)))
      }
      await update($, cycleAtom, before => nextCycle(before, now))
      await publish($)
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  // Main-loop calls only; counted as they are made, so the live line moves while a long call runs.
  on('tool.call', async ($, e, next) => {
    if (e.agentId === undefined) {
      const key = e.tool === 'Skill' ? 'skills' : e.tool === 'Agent' ? 'agents' : 'tools'
      await update($, cycleAtom, before => ({ ...before, [key]: before[key] + 1 }))
      await publish($)
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.start', async ($, e, next) => {
    const started = await next(e)
    if (e.agentId === undefined) {
      const now = await $.clock.now()
      await update($, cycleAtom, before => ({ ...before, runningSince: now }))
      startTick($)
      await publish($)
    }

    return started
  })

  on('turn.complete', async ($, e, next) => {
    const completed = await next(e)
    const isMain = e.agentId === undefined
    const { usage } = e
    // Tokens of the main loop and of every subagent join the cycle, even a subagent that ends while the main loop is idle
    // (a background agent finishing before its hand-back).
    await update($, cycleAtom, before => ({
      ...before,
      byModel: usage === undefined ? before.byModel : addUsage(before.byModel, usage),
      busyMs: isMain ? before.busyMs + e.durationMs : before.busyMs,
      runningSince: isMain ? null : before.runningSince,
    }))
    await update($, session, before => ({
      durationMs: before.durationMs + (isMain ? e.durationMs : 0),
      turns: before.turns + (isMain ? 1 : 0),
      byModel: usage === undefined ? before.byModel : addUsage(before.byModel, usage),
    }))
    if (isMain) {
      stopTick()
    }
    await publish($)

    return completed
  })
}
