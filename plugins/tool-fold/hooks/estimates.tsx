import type { EngineInterface } from 'claude-code'

import type { WaitSample } from '../types'

// Finished work remembered across sessions ($.store, a local file), newest last. Each kind of work has its own key
// (processes `wait-samples`, subagents `agent-samples`), so their summaries never mix.
export const WAIT_SAMPLES_KEY = 'wait-samples'
export const AGENT_SAMPLES_KEY = 'agent-samples'
const REMEMBERED = 50
// Word overlap (Jaccard) from which a stored summary counts as the same kind of work.
export const SIMILARITY_MIN = 0.5
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

export type MinutesAsk = {
  /** The description, command or brief of the work. */
  text: string
  /** A duration the text states, when it parses one. */
  statedMs?: number
  /** Similar finished runs (top five), or none. */
  similar: readonly WaitSample[]
  /** A re-estimate: how long the work already took and what was said it would take. */
  again?: { elapsedMs: number; previousMs: number }
}

const fmtMin = (ms: number): string => `${Math.round((ms / 60000) * 10) / 10} min`

/**
 * Asks Haiku (one call) for the minutes a piece of work takes: it sees the text and the similar past runs together.
 * Reads `minutos: N` strictly; a re-estimate must also be longer than the elapsed time. Undefined when it does not answer well.
 */
export async function askMinutes($: EngineInterface, ask: MinutesAsk): Promise<number | undefined> {
  const runs = ask.similar.length === 0 ? 'none' : `\n${ask.similar.map((run, index) => `${index + 1}. ${run.summary} — ${fmtMin(run.durationMs)}`).join('\n')}`
  const reply = await $.model.complete({
    model: 'haiku',
    prompt:
      `<tarea>${ask.text.slice(0, 1500)}</tarea>\n` +
      (ask.statedMs === undefined ? '' : `<duracion_indicada>${fmtMin(ask.statedMs)}</duracion_indicada>\n`) +
      `<tareas_parecidas>${runs}</tareas_parecidas>\n` +
      (ask.again === undefined
        ? ''
        : `<ya_transcurrido>${fmtMin(ask.again.elapsedMs)}</ya_transcurrido>\n<estimacion_anterior>${fmtMin(ask.again.previousMs)}</estimacion_anterior>\n`) +
      '\nUna tarea en segundo plano de un agente de programación ejecuta lo de arriba. ' +
      (ask.again === undefined
        ? 'Estima cuántos minutos tardará en total.'
        : 'Ya pasó la estimación anterior: estima cuántos minutos durará en total, contando lo ya transcurrido (más que lo transcurrido).') +
      ' Responde solo con esta línea:\nminutos: N\n<example>minutos: 4</example>',
    maxTokens: 20,
    timeoutMs: 15000,
  })
  if (!reply.isAnswered || (reply.usage?.output_tokens ?? 0) >= 20) {
    return undefined
  }
  const ms = minutesLine(reply.text)
  return ms !== undefined && (ask.again === undefined || ms > ask.again.elapsedMs) ? ms : undefined
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
