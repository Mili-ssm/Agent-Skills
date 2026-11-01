import type { EngineInterface } from 'claude-code'

import type { WaitSample } from '../types'

// Finished work remembered across sessions ($.store, a local file), newest last. Each kind of work has its own key
// (processes `wait-samples`, subagents `agent-samples`), so their summaries never mix.
export const WAIT_SAMPLES_KEY = 'wait-samples'
export const AGENT_SAMPLES_KEY = 'agent-samples'
const REMEMBERED = 50
// Word overlap (Jaccard) from which a stored summary counts as the same kind of work.
export const SIMILARITY_MIN = 0.5
// Summaries offered to Haiku when no stored one is similar enough.
const PICK_CANDIDATES = 20
// A run shorter than this teaches nothing (a command that failed at once).
export const MIN_SAMPLE_MS = 1000

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
          typeof item === 'object' && item !== null && typeof item.summary === 'string' && typeof item.durationMs === 'number',
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

/**
 * Asks Haiku (one call) which of the latest summaries are the same kind of work as this one; the median of their
 * durations, or undefined when it picks none or does not answer. `context` (a brief) helps it judge the size.
 */
export async function askSimilar(
  $: EngineInterface,
  subject: string,
  samples: readonly WaitSample[],
  context?: string,
): Promise<number | undefined> {
  const latest = samples.slice(-PICK_CANDIDATES)
  const reply = await $.model.complete({
    model: 'haiku',
    prompt:
      'Cuál de estas tareas anteriores es el mismo tipo de trabajo que la nueva (misma operación, tamaño parecido). ' +
      `Responde solo con los números separados por comas, o none.\n\nNueva: ${subject.slice(0, 300)}\n\n` +
      (context === undefined || context.trim() === '' ? '' : `Encargo de la nueva:\n${context.slice(0, 600)}\n\n`) +
      `Anteriores:\n${latest.map((sample, index) => `${index + 1}. ${sample.summary}`).join('\n')}`,
    maxTokens: 20,
    timeoutMs: 15000,
  })
  if (!reply.isAnswered) {
    return undefined
  }
  const picked = (reply.text.match(/\d+/g) ?? []).map(Number).filter(n => n >= 1 && n <= latest.length)
  return median(picked.map(n => latest[n - 1]?.durationMs ?? 0).filter(ms => ms > 0))
}
