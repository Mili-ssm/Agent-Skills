import type { EngineInterface } from 'claude-code'

import type { WaitSample } from '../types'
import type { PlanState } from './plan'

// Finished work remembered across sessions ($.store, a local file), newest last. Each kind of work has its own key
// (processes `wait-samples`, subagents `agent-samples`), so their summaries never mix.
export const WAIT_SAMPLES_KEY = 'wait-samples'
export const AGENT_SAMPLES_KEY = 'agent-samples'
const REMEMBERED = 50
// Word overlap (Jaccard) from which a stored summary counts as the same kind of work.
export const SIMILARITY_MIN = 0.5
// Progress held under 100% while the work runs, in percent.
export const MAX_PERCENT = 99
// A run counts as past its estimate only this long after the estimate.
export const OVERDUE_GRACE_MS = 15_000
// A card of work that ended well stays in view, full and green, this long.
export const LINGER_MS = 5000
// A run shorter than this teaches nothing (a command that failed at once).
// Runs shorter than this teach nothing: earlier versions recorded ~5 s agents that only launched background work.
export const MIN_SAMPLE_MS = 20_000

const STOPWORDS = new Set([
  'the', 'and', 'for', 'with', 'from', 'into', 'run', 'running', 'that', 'this', 'les', 'los', 'las', 'del', 'para', 'con', 'por', 'una', 'uno', 'que', 'ejecuta', 'ejecutar',
])

/** Lowercased words of 3+ letters or digits, stopwords out. */
export function wordsOf(text: string): Set<string> {
  const found = text.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? []
  return new Set(found.filter(word => !STOPWORDS.has(word)))
}

/** Jaccard overlap of two summaries' words: 0 (nothing shared) to 1 (same words). */
export function similarity(a: string, b: string): number {
  const left = wordsOf(a)
  const right = wordsOf(b)
  const shared = [...left].filter(word => right.has(word)).length
  const total = left.size + right.size - shared
  return total === 0 ? 0 : shared / total
}

/** Middle of a list of durations: the typical one, robust to an odd outlier. */
export const median = (values: readonly number[]): number | undefined => {
  if (values.length === 0) {
    return undefined
  }
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1 ? sorted[middle] : Math.round(((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2)
}

/** The samples under a store key (anything of another shape is dropped). */
export async function loadSamples($: EngineInterface, key: string): Promise<WaitSample[]> {
  const value = await $.store.get(key).catch(() => undefined)
  return Array.isArray(value)
    ? value.filter(
        (item): item is WaitSample =>
          typeof item === 'object' &&
          item !== null &&
          typeof item.summary === 'string' &&
          typeof item.durationMs === 'number' &&
          item.durationMs >= MIN_SAMPLE_MS,
      )
    : []
}

/** Remembers a finished run's summary and duration under `key` (runs under MIN_SAMPLE_MS teach nothing). */
export async function recordSample($: EngineInterface, key: string, summary: string, durationMs: number, at: number): Promise<void> {
  if (durationMs < MIN_SAMPLE_MS) {
    return
  }
  const list = await loadSamples($, key)
  await $.store.set(key, [...list, { summary, durationMs, at }].slice(-REMEMBERED)).catch(() => undefined)
}

/** The median duration of the stored summaries similar enough to `summary`; undefined when none is. */
export function similarMedian(samples: readonly WaitSample[], summary: string): number | undefined {
  return median(samples.filter(sample => similarity(sample.summary, summary) >= SIMILARITY_MIN).map(sample => sample.durationMs))
}

// Past runs listed to Haiku with the text: the most similar ones, never fewer words in common than this.
const SIMILAR_SHOWN = 5
const SIMILAR_LISTED_MIN = 0.2
// A re-estimate of one piece of work waits this long after the last ask of it.
export const REESTIMATE_GAP_MS = 30_000
// An answer outside this range is Haiku misreading the question.
const MAX_ESTIMATE_MIN = 24 * 60

/** The (at most five) stored runs most like `summary`, most similar first; empty when none shares words with it. */
export function similarRuns(samples: readonly WaitSample[], summary: string): WaitSample[] {
  return samples
    .map(sample => ({ sample, score: similarity(sample.summary, summary) }))
    .filter(item => item.score >= SIMILAR_LISTED_MIN)
    .sort((a, b) => b.score - a.score)
    .slice(0, SIMILAR_SHOWN)
    .map(item => item.sample)
}

/** Milliseconds in a reply that is exactly the line `minutos: N` (`3`, `0.5`, `3,5`); undefined for anything else, prose included. */
export function minutesLine(reply: string): number | undefined {
  const found = /^\s*minutos:\s*(\d+(?:[.,]\d+)?)\s*$/i.exec(reply)?.[1]
  const minutes = found === undefined ? Number.NaN : Number.parseFloat(found.replace(',', '.'))
  return Number.isFinite(minutes) && minutes > 0 && minutes <= MAX_ESTIMATE_MIN ? Math.round(minutes * 60000) : undefined
}

/** The icon source of an estimate Haiku gave: a stated duration, else similar runs it was shown, else its own guess. */
export const sourceOfAsk = (statedMs: number | undefined, similar: readonly WaitSample[]): 'stated' | 'similar' | 'guess' =>
  statedMs !== undefined ? 'stated' : similar.length > 0 ? 'similar' : 'guess'

/** Why a running item is asked again: progress (50% / 80% of the estimate), periodic (long runs), overdue (past the estimate). */
export type ReaskKind = 'progress' | 'periodic' | 'overdue'

export type MinutesAsk = {
  /** The description, command or brief of the work. */
  text: string
  /** A duration the text states, when it parses one. */
  statedMs?: number
  /** Similar finished runs (top five), or none. */
  similar: readonly WaitSample[]
  /** A re-estimate: how long the work already took, what was said it would take, which variant and, only when it comes from real progress (a task list, the %-estimator; never elapsed / estimate), the percent. */
  again?: { elapsedMs: number; previousMs: number; kind: ReaskKind; percent?: number }
  /** What the work did so far (an agent's task list and recent calls); never a wait's output. Cut to PROGRESS_CHARS. */
  progress?: string
  /** The item's id, for the re-estimate log. */
  id?: string
}

// Characters of `<progreso>`, apart from the 1500 of `<tarea>`.
export const PROGRESS_CHARS = 600

/**
 * Fields a re-estimated item carries besides the types' (`types/index.d.ts` is not extended here): the ask counter that
 * drops stale answers, how many of the 50% / 80% re-asks were done, and the percent anchor (`at` is elapsed ms).
 */
export type ReaskFields = { /** The step plan of a long agent (see plan.tsx). */ plan?: PlanState; askSeq?: number; reaskStep?: number; anchor?: Anchor; /** Drawn only: ms to the estimated end, so the card's time left agrees with its bar. */ etaLeftMs?: number; /** Clock time its last call ended (the thinking indicator counts from it). */ lastCallEndedAt?: number; /** The `lastCallEndedAt` whose thinking episode already hinted the plan. */ thinkHintedFor?: number }

/** Where the percent stood (`pct`) when the estimate last changed, `at` ms into the run: it never goes back from there. */
export type Anchor = { at: number; pct: number }

/**
 * The percent a running item shows, 0 to 99: elapsed over the estimate, or, after the estimate changed, a line from the
 * anchor's percent to 99 at the new end, so a longer estimate never lowers it.
 */
export function percentAt(elapsedMs: number, etaMs: number, anchor?: Anchor): number {
  if (anchor === undefined) {
    return Math.min(MAX_PERCENT, Math.max(0, Math.round((Math.max(0, elapsedMs) / etaMs) * 100)))
  }
  const span = etaMs - anchor.at
  const fraction = span <= 0 ? 1 : Math.min(1, Math.max(0, (elapsedMs - anchor.at) / span))
  return Math.min(MAX_PERCENT, Math.max(0, Math.round(anchor.pct + (MAX_PERCENT - anchor.pct) * fraction)))
}

/** The anchor to store when an item's estimate becomes `nextMs` at `elapsedMs`: the percent shown now, or the old anchor if unchanged. */
export function reanchor(prev: { etaMs?: number; anchor?: Anchor }, nextMs: number, elapsedMs: number): Anchor | undefined {
  if (prev.etaMs === undefined || prev.etaMs <= 0 || nextMs === prev.etaMs) {
    return prev.anchor
  }
  return { at: elapsedMs, pct: percentAt(elapsedMs, prev.etaMs, prev.anchor) }
}

// Re-ask schedule: fractions of the current estimate (by elapsed time, never by percent), then every tenth of it within bounds.
const REASK_FRACTIONS = [0.5, 0.8] as const
const PERIODIC_MIN_MS = 5 * 60_000
const PERIODIC_MAX_MS = 20 * 60_000
// A progress or periodic answer within this share of the current total is noise.
const DAMPING_MIN = 0.2

/** Elapsed ms between periodic re-asks: a tenth of the estimate, 5 to 20 minutes. */
export const periodicGapMs = (etaMs: number): number => Math.min(PERIODIC_MAX_MS, Math.max(PERIODIC_MIN_MS, etaMs / 10))

/** How many of the 50% / 80% re-asks an estimate of `etaMs` has already passed at `elapsedMs` (0, 1 or 2). */
export const stepFor = (elapsedMs: number, etaMs: number): number => REASK_FRACTIONS.filter(fraction => elapsedMs >= etaMs * fraction).length

/**
 * Whether a running item is asked again now, and how. Called from the tick, never from a draw. `lastAskAt` is the clock
 * time of its latest ask (the first one counts); `step` how many 50% / 80% re-asks went out. Stated and message
 * estimates are only re-asked once overdue.
 */
export function nextReask(
  item: { elapsedMs: number; etaMs: number; source?: string; lastAskAt: number; step?: number },
  now: number,
): { kind: ReaskKind; step: number } | undefined {
  const step = item.step ?? 0
  // The first overdue ask (the first tick past the grace) is never held by the throttle; later ones are, every 30 s.
  const isOverdue = item.elapsedMs >= item.etaMs + OVERDUE_GRACE_MS
  const isFirstOverdue = isOverdue && item.lastAskAt < now - (item.elapsedMs - item.etaMs - OVERDUE_GRACE_MS)
  if (now - item.lastAskAt < REESTIMATE_GAP_MS && !isFirstOverdue) {
    return undefined
  }
  if (isOverdue) {
    return { kind: 'overdue', step }
  }
  if (item.source === 'stated' || item.source === 'message') {
    return undefined
  }
  const [half, late] = REASK_FRACTIONS
  if (step < 2 && item.elapsedMs >= item.etaMs * late) {
    return { kind: 'progress', step: 2 }
  }
  if (step < 1 && item.elapsedMs >= item.etaMs * half) {
    return { kind: 'progress', step: 1 }
  }
  return now - item.lastAskAt >= periodicGapMs(item.etaMs) ? { kind: 'periodic', step } : undefined
}

/**
 * The estimate to store after a re-ask answered `totalMs` (elapsed + Haiku's remaining) for an item now at `currentMs`:
 * an overdue answer only lengthens; a progress or periodic one counts if it differs 20% or more, blended 50/50 with
 * the current total (it may go down). Undefined when the answer is ignored.
 */
export function settleEstimate(kind: ReaskKind, currentMs: number, totalMs: number, elapsedMs: number): number | undefined {
  if (kind === 'overdue') {
    return totalMs > currentMs ? totalMs : undefined
  }
  if (Math.abs(totalMs - currentMs) / currentMs < DAMPING_MIN) {
    return undefined
  }
  const blended = Math.round((currentMs + totalMs) / 2)
  return blended > elapsedMs ? blended : undefined
}

// The latest re-estimates (item, variant, old, Haiku's remaining, proposed total, elapsed), newest last, for `/agents-debug`.
export const reestimateLog: string[] = []
const LOG_KEPT = 10
export const logReestimate = (line: string): void => {
  reestimateLog.push(line)
  reestimateLog.splice(0, Math.max(0, reestimateLog.length - LOG_KEPT))
}

// Closes every re-ask prompt, after the data.
const TRAILER = '\n\nResponde solo con la línea minutos: N (minutos restantes, número entero).'

const fmtMin = (ms: number): string => `${Math.round((ms / 60000) * 10) / 10} min`

const HEAD_OVERDUE = (previous: string, elapsed: string): string =>
  `Una tarea en segundo plano de un agente de programación ya superó su estimación anterior (${previous}) y lleva ${elapsed}. ` +
  'La estimación anterior fue demasiado baja: no la repitas. Estima cuántos minutos FALTAN a partir de ahora, sin contar lo ya transcurrido. ' +
  'Usa tareas_parecidas. Responde solo con esta línea:\nminutos: N\n' +
  '<example>Con 12 min transcurridos y estimación anterior de 8 min, la respuesta es:\nminutos: 5</example>'

// A black box (a background shell, or an agent with no real percent): no percent, only the clock and the references.
const HEAD_BLIND = (elapsed: string): string =>
  `Una tarea en segundo plano (sin información de avance) lleva ${elapsed}. ` +
  'Estima cuántos minutos FALTAN para terminar, sin contar lo ya transcurrido. ' +
  'Tu mejor referencia son tareas_parecidas y, si hay, duracion_indicada y <progreso>; sin tareas_parecidas, parte de la estimación anterior. Responde solo con esta línea:\nminutos: N\n' +
  '<example>Con 6 min transcurridos, la respuesta es:\nminutos: 7</example>'

const HEAD_PROGRESS = (elapsed: string, percent: number): string =>
  `Una tarea en segundo plano de un agente de programación lleva ${elapsed} y va por ${percent}%. ` +
  'Estima cuántos minutos FALTAN para terminar, sin contar lo ya transcurrido. ' +
  'Si el porcentaje es mayor que 0, FALTAN ≈ transcurrido × (100 − porcentaje) / porcentaje; corrígelo con tareas_parecidas y <progreso> (tareas y llamadas recientes). Con 0%, usa tareas_parecidas. ' +
  'La estimación anterior es solo una pista. Responde solo con esta línea:\nminutos: N\n' +
  '<example>Con 6 min transcurridos y 40%, la respuesta es:\nminutos: 9</example>'

/**
 * Asks Haiku (one call) for the minutes a piece of work takes: it sees the text and the similar past runs together.
 * Reads `minutos: N` strictly. A first ask answers the total; a re-ask (`again`) answers the minutes that REMAIN, in the
 * progress / periodic or the overdue wording, and the total returned is elapsed + remaining (capped). Undefined when it does not answer well.
 */
export async function askMinutes($: EngineInterface, ask: MinutesAsk): Promise<number | undefined> {
  const runs = ask.similar.length === 0 ? 'none' : `\n${ask.similar.map((run, index) => `${index + 1}. ${run.summary} — ${fmtMin(run.durationMs)}`).join('\n')}`
  const { again } = ask
  const data =
    `<tarea>${ask.text.slice(0, 1500)}</tarea>\n` +
    (ask.statedMs === undefined ? '' : `<duracion_indicada>${fmtMin(ask.statedMs)}</duracion_indicada>\n`) +
    `<tareas_parecidas>${runs}</tareas_parecidas>\n` +
    (again === undefined ? '' : `<ya_transcurrido>${fmtMin(again.elapsedMs)}</ya_transcurrido>\n`) +
    (again?.kind === 'overdue' || again?.percent === undefined ? '' : `<porcentaje>${again.percent}%</porcentaje>\n`) +
    (ask.progress === undefined || ask.progress === '' ? '' : `<progreso>${ask.progress.slice(0, PROGRESS_CHARS)}</progreso>\n`)
  let prompt: string
  if (again === undefined) {
    prompt = `${data}\nUna tarea en segundo plano de un agente de programación ejecuta lo de arriba. Estima cuántos minutos tardará en total. Responde solo con esta línea:\nminutos: N\n<example>minutos: 4</example>`
  } else if (again.kind === 'overdue') {
    prompt = `${HEAD_OVERDUE(fmtMin(again.previousMs), fmtMin(again.elapsedMs))}\n\n${data}<estimacion_anterior>${fmtMin(again.previousMs)}</estimacion_anterior>${TRAILER}`
  } else {
    const head = again.percent === undefined ? HEAD_BLIND(fmtMin(again.elapsedMs)) : HEAD_PROGRESS(fmtMin(again.elapsedMs), again.percent)
    prompt = `${head}\n\n${data}<estimacion_anterior>${fmtMin(again.previousMs)}</estimacion_anterior>${TRAILER}`
  }
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 20, timeoutMs: 15000 })
  // Only the first line counts: Haiku often keeps writing after `minutos: N` (and hits maxTokens), which once dropped
  // every re-ask and froze cards at 99%. A complete first line is a complete answer.
  const firstLine = reply.text.trim().split('\n')[0] ?? ''
  const ms = reply.isAnswered ? minutesLine(firstLine) : undefined
  if (again === undefined) {
    return ms
  }
  if (ms === undefined) {
    // A failed re-ask is logged too, so a card stuck at 99% shows why in `/agents-debug`.
    logReestimate(`${ask.id ?? '?'} ${again.kind} failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'} elapsed=${fmtMin(again.elapsedMs)}`)
    return undefined
  }
  const total = Math.min(again.elapsedMs + ms, MAX_ESTIMATE_MIN * 60000)
  logReestimate(`${ask.id ?? '?'} ${again.kind} old=${fmtMin(again.previousMs)} haiku-remaining=${fmtMin(ms)} total=${fmtMin(total)} elapsed=${fmtMin(again.elapsedMs)}`)
  return total
}

const NUM = String.raw`(\d+(?:[.,]\d+)?)`
const SLEEP = new RegExp(String.raw`\bsleep\s+${NUM}\s*([smhd])?(?![\p{L}\d])`, 'giu')
const STATED = new RegExp(
  String.raw`(?<![\p{L}\d.,])${NUM}(?:\s*(?:[–—-]|\s(?:a|to)\s)\s*${NUM})?\s*(horas?|hours?|hrs?|h|minutos?|minutes?|mins?|segundos?|seconds?|secs?|s)(?![\p{L}\d])`,
  'iu',
)
const UNIT_MS = { d: 86_400_000, h: 3_600_000, m: 60_000, s: 1000 } as const
const toNumber = (text: string): number => Number.parseFloat(text.replace(',', '.'))

/**
 * A duration written in a command or description, in ms: `sleep 290` (also `sleep 5m`; several add up),
 * `espera 180 segundos`, `Wait 5 minutes`, `unas 2–3 horas` (a range is its midpoint); undefined when none.
 */
export function statedDuration(text: string): number | undefined {
  let slept = 0
  for (const match of text.matchAll(SLEEP)) {
    slept += toNumber(match[1] ?? '0') * UNIT_MS[(match[2]?.toLowerCase() ?? 's') as keyof typeof UNIT_MS]
  }
  if (slept > 0) {
    return Math.round(slept)
  }
  const found = STATED.exec(text)
  if (found === null) {
    return undefined
  }
  const low = toNumber(found[1] ?? '0')
  const value = found[2] === undefined ? low : (low + toNumber(found[2])) / 2
  const unit = (found[3] ?? 's').toLowerCase()
  const ms = Math.round(value * (unit.startsWith('h') ? UNIT_MS.h : unit.startsWith('m') ? UNIT_MS.m : UNIT_MS.s))
  return ms > 0 ? ms : undefined
}
