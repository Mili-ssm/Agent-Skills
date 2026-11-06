import type { EngineInterface } from 'claude-code'

import type { WaitSample } from '../types'

import { MAX_PERCENT, OVERDUE_GRACE_MS, logReestimate, wordsOf } from './estimates'

// Step-based progress for long agent cards. Isolated: agents.tsx calls it behind `PLAN_ENABLED`; rollback is that constant
// set to false, or deleting this file and its call sites. Every function here is pure or asks Haiku; none writes state.

/** The one switch: false and the cards behave exactly as before this module. */
export const PLAN_ENABLED = true
/** Kill switch for the replan call only: false keeps the plan and its checks, but pending steps are never rewritten. */
export const REPLAN_ENABLED = true
/** An agent whose first estimate is longer than this gets a step plan (may become 10 min). */
export const PLAN_MIN_MS = 5 * 60_000
const MIN_STEPS = 3
const MAX_STEPS = 6
/** Steps of a plan after replans may add some; the first build stays 3 to 6. */
export const MAX_TOTAL_STEPS = 8
const MAX_STEP_MIN = 24 * 60
const TITLE_CHARS = 80
// Two event checks are never closer than this; with no event and no overdue step, a check still comes after the ceiling.
const CHECK_GAP_MS = 60_000
const CHECK_MAX_MS = 5 * 60_000
// An overdue step is asked again after these gaps (index = overdue checks so far, capped at the last).
const OVERDUE_GAPS_MS = [30_000, 60_000, 120_000, 240_000] as const
// A step overrunning its estimate grows by at least this, or by half the time it has been running.
const GROW_MIN_MS = 60_000
// Real over estimated time only ever lengthens what remains: a fast start says little about a long testing step.
const FACTOR_MIN = 1
const FACTOR_MAX = 3
const CRITERION_CHARS = 100
// A replan within this long of the previous advance is skipped (cost: fast steps would replan every minute).
export const REPLAN_MIN_GAP_MS = 2 * 60_000

export type PlanStep = {
  title: string
  /** Estimated duration (ms), unscaled: the factor applies to the steps still to run. */
  estMs: number
  /** Real duration once finished. */
  realMs?: number
  /** What a tool call can show when the step is done ("listo cuando"): the yes/no check judges against it. */
  criterion?: string
}

/** The plan stored on a run. Times `...At` of the run are elapsed ms (since the spawn); `askedAt` is a clock time. */
export type PlanState = {
  steps: PlanStep[]
  /** Real over estimated time of the finished steps, 1 to 3: lengthens the steps still to run, never shortens them. */
  factor: number
  /** Steps finished (the count can only grow). */
  done: number
  /** When the current step began / is expected to end. */
  stepAt: number
  stepEndAt: number
  /** The current step's planned duration when it began (or was lengthened): what Haiku is told was planned. */
  stepEstMs: number
  /** The bar never shows less than this percent. */
  anchor: number
  /** Clock time of the latest check. */
  askedAt: number
  /** Clock time an event pointed at a later step (a call, thinking, the agent's text): the next tick may check (see `nextPlanCheck`). */
  hintAt?: number
  /** The latest check's number, so an older answer is dropped. */
  seq: number
  /** The run's activity counts when the current step began (G7): the "since the current step" summary is the difference. */
  countsAtStep?: Record<string, number>
  /** Calls the run had finished at the latest check (G1: a step only advances if calls were added since). */
  callsAtCheck?: number
  /** Overdue checks the current step has had (absent = 0): picks the backoff gap; reset when the step advances. */
  overdueChecks?: number
  /** Clock time of the latest advance, so a replan right after another is skipped (M7). */
  advancedAt?: number
}

/** Whether a first estimate switches a plan on: only the first answer (`askSeq` 1) and only when it is long. */
export const shouldPlan = (askSeq: number | undefined, etaMs: number, enabled: boolean = PLAN_ENABLED): boolean =>
  enabled && askSeq === 1 && etaMs > PLAN_MIN_MS

/** One parsed plan line: minutes are a split of the total, `criterion` is what a tool call must show for the step to be done. */
export type ParsedStep = { title: string; minutes: number; criterion?: string }

// `N. <title> — M min`, optionally `— listo cuando: <criterion>`; the dash may be em, en or a hyphen.
// `min`, `min.`, `minuto(s)`: Haiku writes the Spanish word often enough that one such line must not void the plan.
const STEP_LINE = /^(\d+)[.)]\s+(.{1,120}?)\s+[—–-]\s+(\d+(?:[.,]\d+)?)\s*min(?:\.|utos?)?(?:\s+[—–-]\s+listo cuando\s*:\s*(.+?))?$/i

/** The line's number and step, or undefined when it does not read. */
function parseStepLine(line: string): { number: number; step: ParsedStep } | undefined {
  const found = STEP_LINE.exec(line)
  const minutes = Number.parseFloat((found?.[3] ?? '').replace(',', '.'))
  if (found === null || !(minutes > 0) || minutes > MAX_STEP_MIN) {
    return undefined
  }
  const criterion = (found[4] ?? '').trim().slice(0, CRITERION_CHARS).trim()
  return {
    number: Number.parseInt(found[1] ?? '', 10),
    step: { title: (found[2] ?? '').slice(0, TITLE_CHARS), minutes, ...(criterion === '' ? {} : { criterion }) },
  }
}

/** The steps of a plan reply: one `N. <title> — M min [— listo cuando: <criterion>]` line each, 3 to 6, numbered in order; undefined for anything else (a cut reply included). */
export function parsePlan(reply: string): ParsedStep[] | undefined {
  const lines = reply.replaceAll('**', '').split('\n').map(line => line.trim()).filter(line => line !== '')
  if (lines.length < MIN_STEPS || lines.length > MAX_STEPS) {
    return undefined
  }
  const steps: ParsedStep[] = []
  for (const [index, line] of lines.entries()) {
    const parsed = parseStepLine(line)
    if (parsed === undefined || parsed.number !== index + 1) {
      return undefined
    }
    steps.push(parsed.step)
  }
  return steps
}

/**
 * Haiku's reply to a step check: `evidencia: <quote>` and `terminado: sí|no`, each found by key over the first 4
 * non-empty lines (bold ignored, any order). `done` only when the verdict reads as sí/si/yes or no; each part is
 * absent when it does not read.
 */
export function parseVerdict(text: string): { done?: boolean; evidence?: string } {
  const lines = text
    .replaceAll('**', '')
    .split('\n')
    .map(line => line.trim())
    .filter(line => line !== '')
    .slice(0, 4)
  let done: boolean | undefined
  let evidence: string | undefined
  for (const line of lines) {
    // The word only: a reason or a mark after it (`sí (se editó parser.ts)`, `no ✓`) does not void the verdict.
    const verdict = /^terminado\s*:\s*(s[ií]|yes|no)(?![\p{L}\d])/iu.exec(line)?.[1]
    if (verdict !== undefined && done === undefined) {
      done = verdict.toLowerCase() !== 'no'
    }
    const quote = /^evidencia\s*:\s*(.+)$/i.exec(line)?.[1]
    if (quote !== undefined && evidence === undefined) {
      evidence = quote.trim().slice(0, 160)
    }
  }
  return { ...(done === undefined ? {} : { done }), ...(evidence === undefined ? {} : { evidence }) }
}

/**
 * Whether a verdict's evidence rests on the calls: not `ninguna`/empty, and sharing a word (3+ letters) with the
 * `<llamadas>` text. The agent's opening narration ("leeré, editaré y probaré") is no evidence (M3).
 */
export function isGrounded(evidence: string | undefined, calls: string): boolean {
  if (evidence === undefined || /^\W*ninguna?\W*$/i.test(evidence.trim())) {
    return false
  }
  const seen = wordsOf(calls)
  return [...wordsOf(evidence)].some(word => seen.has(word))
}

/**
 * The lines of a replan reply: `ninguno` alone gives []; else 1 to `max` lines in `parsePlan`'s format, numbered
 * consecutively from `from` (the 1-based number after the current step) or from 1 (Haiku often restarts at 1; the
 * numbers are not kept, the steps take their places in order). `ninguno` may carry case and a final period. Anything else, `ninguno` mixed with lines included, is undefined.
 */
export function parseReplan(reply: string, from: number, max: number): ParsedStep[] | undefined {
  if (/^ninguno\.?$/i.test(reply.replaceAll('**', '').trim())) {
    return []
  }
  const lines = reply.replaceAll('**', '').split('\n').map(line => line.trim()).filter(line => line !== '')
  if (lines.length < 1 || lines.length > max) {
    return undefined
  }
  const first = Number.parseInt(/^(\d+)[.)]/.exec(lines[0] ?? '')?.[1] ?? '', 10)
  if (first !== from && first !== 1) {
    return undefined
  }
  const steps: ParsedStep[] = []
  for (const [index, line] of lines.entries()) {
    const parsed = parseStepLine(line)
    if (parsed === undefined || parsed.number !== first + index) {
      return undefined
    }
    steps.push(parsed.step)
  }
  return steps
}

const clamp = (value: number, low: number, high: number): number => Math.min(high, Math.max(low, value))

/** Time of the steps still to run after the current one, scaled by the factor. */
export const restMs = (plan: PlanState): number => plan.steps.slice(plan.done + 1).reduce((sum, step) => sum + step.estMs * plan.factor, 0)

/** Elapsed ms at which the plan expects to end. */
export const planEndAt = (plan: PlanState): number => plan.stepEndAt + restMs(plan)

/** The bar, 0 to 99: step time done over plan time, never under the anchor. */
export function planBar(plan: PlanState, elapsedMs: number): number {
  const end = planEndAt(plan)
  const computed = end <= 0 ? 0 : Math.round((clamp(Math.min(elapsedMs, plan.stepEndAt), 0, end) / end) * 100)
  return Math.min(MAX_PERCENT, Math.max(plan.anchor, computed))
}

/** Ms to the plan's end: what remains of the current step (none once overdue) plus the scaled steps after it. */
export const planLeftMs = (plan: PlanState, elapsedMs: number): number => Math.max(0, plan.stepEndAt - elapsedMs) + restMs(plan)

/** Room for a step title in the card header: surfaces wrap rather than cut, so the cut (with …) is done here. */
export const STEP_TITLE_CHARS = 26
/** The most a step title may take when the header has room: a little more than the default, never the whole line. */
export const STEP_TITLE_MAX_CHARS = 38
export const clipTitle = (title: string, chars: number = STEP_TITLE_CHARS): string => (title.length <= chars ? title : `${title.slice(0, chars - 1).trimEnd()}…`)

/** What a card with a plan shows: the whole-run percent (the bar's), the current step's title and the time left; undefined without a plan or with `enabled` false. */
export function planView(
  run: { plan?: PlanState; startedAt: number },
  now: number,
  enabled: boolean = PLAN_ENABLED,
): { percent: number; step?: string; title?: string; isWrappingUp: boolean; leftMs: number } | undefined {
  const { plan } = run
  if (!enabled || plan === undefined) {
    return undefined
  }
  const elapsed = now - run.startedAt
  // All steps done while the run still runs: no time left to state, only that it is wrapping up (the bar stays under 100%).
  const isLast = plan.done >= plan.steps.length
  return {
    percent: planBar(plan, elapsed),
    // `step` is cut to the default room; `title` is whole, for a header that knows its width (`stepTitleChars`).
    ...(isLast ? {} : { step: clipTitle(plan.steps[plan.done]?.title ?? ''), title: plan.steps[plan.done]?.title ?? '' }),
    isWrappingUp: isLast,
    leftMs: isLast ? 0 : planLeftMs(plan, elapsed),
  }
}

/** A new plan from parsed steps, their minutes scaled so they add up to the estimate `etaMs`; the bar starts at `anchorPct`. */
export function newPlan(parsed: readonly ParsedStep[], etaMs: number, anchorPct: number, now: number): PlanState {
  const sum = parsed.reduce((total, step) => total + step.minutes, 0)
  const steps = parsed.map(step => ({ title: step.title, estMs: Math.max(1000, Math.round((step.minutes / sum) * etaMs)), ...(step.criterion === undefined ? {} : { criterion: step.criterion }) }))
  const first = steps[0]?.estMs ?? etaMs
  return { steps, factor: 1, done: 0, stepAt: 0, stepEndAt: first, stepEstMs: first, anchor: clamp(anchorPct, 0, MAX_PERCENT), askedAt: now, seq: 1 }
}

/**
 * The plan after `count` steps are done at `elapsedMs`; undefined when the count does not grow. While the run
 * runs done may reach y (the card then says it is finishing). Several steps at once split the time since the current one began evenly;
 * the factor is the real over estimated time of every finished step, 1 to 3: it only lengthens what remains. The bar's anchor keeps what was shown.
 */
export function applyCount(plan: PlanState, count: number, elapsedMs: number, now: number): PlanState | undefined {
  const done = Math.min(count, plan.steps.length)
  if (done <= plan.done) {
    return undefined
  }
  const slice = Math.max(1000, (elapsedMs - plan.stepAt) / (done - plan.done))
  const steps = plan.steps.map((step, index) => (index >= plan.done && index < done ? { ...step, realMs: slice } : step))
  const finished = steps.filter(step => step.realMs !== undefined)
  const real = finished.reduce((sum, step) => sum + (step.realMs ?? 0), 0)
  const estimated = finished.reduce((sum, step) => sum + step.estMs, 0)
  const factor = estimated <= 0 ? 1 : clamp(real / estimated, FACTOR_MIN, FACTOR_MAX)
  // With every step done there is no current step: it ends where it is.
  const next = steps[done]
  const stepEstMs = next === undefined ? 0 : Math.round(next.estMs * factor)
  return { ...plan, steps, factor, done, stepAt: elapsedMs, stepEstMs, stepEndAt: elapsedMs + stepEstMs, anchor: planBar(plan, elapsedMs) }
}

/**
 * The plan after Haiku judged the current step done: exactly one step, and only when calls were added since the last
 * check (`historyGrew`, G1). One binary verdict judges one step; a fast following step is caught by the hint, which
 * asks again after the event gap. Undefined without new calls or when every step is done. The caller stamps `countsAtStep` (G7).
 */
export function applyDone(plan: PlanState, elapsedMs: number, now: number, historyGrew: boolean): PlanState | undefined {
  if (!historyGrew || plan.done >= plan.steps.length) {
    return undefined
  }
  const next = applyCount(plan, plan.done + 1, elapsedMs, now)
  return next === undefined ? undefined : { ...next, overdueChecks: 0, hintAt: now, advancedAt: now }
}

/**
 * Ms an overdue step waits before it is asked again: 30 s, 1, 2, then 4 min, by how many overdue checks it has had.
 * After a growth the step's new end plus the grace (at least 75 s away) comes first, so in practice the 2 and 4 min
 * entries are the ones that bind; the short ones only matter when a check left the end where it was.
 */
export const overdueGapMs = (checks: number): number => OVERDUE_GAPS_MS[clamp(Math.floor(checks), 0, OVERDUE_GAPS_MS.length - 1)] ?? 240_000

/**
 * The plan with its overdue step lengthened: it ends `max(1 min, half the time already in the step)` after now, so the
 * time left never sits at "~1 min" while the step overruns. The anchor is the bar shown first, so the percent holds.
 */
export function growOverdue(plan: PlanState, elapsedMs: number): PlanState {
  const grown = Math.max(GROW_MIN_MS, Math.round(0.5 * Math.max(0, elapsedMs - plan.stepAt)))
  const stepEndAt = Math.max(plan.stepEndAt, elapsedMs + grown)
  return { ...plan, stepEndAt, stepEstMs: Math.max(1000, stepEndAt - plan.stepAt), overdueChecks: (plan.overdueChecks ?? 0) + 1, anchor: planBar(plan, elapsedMs) }
}

/**
 * The plan with its pending steps (those after the current one) rewritten by a replan's `steps`: titles, criteria and
 * the split change, the total does not. The new minutes are scaled to the old pending `estMs` sum (unscaled), so the
 * plan's end and the percent do not jump and the factor still applies once. Done and current steps stay. `[]`, or no
 * pending step to rewrite, returns the same object. The caller reads `elapsedMs` when the answer arrives, so the anchor is the bar shown now.
 */
export function applyReplan(plan: PlanState, steps: readonly ParsedStep[], elapsedMs: number): PlanState {
  const pending = plan.steps.slice(plan.done + 1)
  if (steps.length === 0 || pending.length === 0) {
    return plan
  }
  const fresh = steps.slice(0, Math.max(0, MAX_TOTAL_STEPS - plan.done - 1))
  const wanted = fresh.reduce((sum, step) => sum + step.minutes, 0)
  const old = pending.reduce((sum, step) => sum + step.estMs, 0)
  const replaced = fresh.map(step => ({
    title: step.title,
    estMs: Math.max(1000, Math.round(old > 0 && wanted > 0 ? (step.minutes / wanted) * old : step.minutes * 60_000)),
    ...(step.criterion === undefined ? {} : { criterion: step.criterion }),
  }))
  return { ...plan, steps: [...plan.steps.slice(0, plan.done + 1), ...replaced], anchor: planBar(plan, elapsedMs) }
}

/** Whether an applied check also replans the pending steps: only after an advance, and only when a step follows the new current one. */
export const shouldReplan = (plan: PlanState, advanced: boolean): boolean => advanced && plan.done + 1 < plan.steps.length

/**
 * Whether the plan is checked now, and why: `overdue` (the step is past its end plus the grace and its backoff gap since
 * the last check passed), `event` (a hint after the last check, at least 1 min after it) or `ceiling` (5 min without
 * a check). None once every step is done, and none within 1 min of the last check unless the step is overdue.
 */
export function nextPlanCheck(plan: PlanState, elapsedMs: number, now: number): { kind: 'overdue' | 'event' | 'ceiling' } | undefined {
  // Every step done: no more checks, only the run's end closes it.
  if (plan.done >= plan.steps.length) {
    return undefined
  }
  const since = now - plan.askedAt
  if (elapsedMs >= plan.stepEndAt + OVERDUE_GRACE_MS && since >= overdueGapMs(plan.overdueChecks ?? 0)) {
    return { kind: 'overdue' }
  }
  if (since < CHECK_GAP_MS) {
    return undefined
  }
  if (plan.hintAt !== undefined && plan.hintAt > plan.askedAt) {
    return { kind: 'event' }
  }
  return since >= CHECK_MAX_MS ? { kind: 'ceiling' } : undefined
}

/**
 * True when text (a call's description, Haiku's reading of a command, the agent's own words) shares more words with a
 * later step's title and criterion than with the current one's: a free hint that the agent moved on, which Haiku then
 * confirms. Never decides alone.
 */
export function callPointsAhead(plan: PlanState, text: string): boolean {
  if (plan.done >= plan.steps.length - 1) {
    return false
  }
  const words = wordsOf(text)
  const shared = (step: PlanStep | undefined): number => [...wordsOf(`${step?.title ?? ''} ${step?.criterion ?? ''}`)].filter(word => words.has(word)).length
  const now = shared(plan.steps[plan.done])
  const ahead = Math.max(...plan.steps.slice(plan.done + 1).map(shared))
  return ahead >= 1 && ahead > now
}

/** The steps of a run for memory: finished ones with their real time, the current one ending at `endElapsedMs`; unstarted ones are left out. */
export function stepTimes(plan: PlanState, endElapsedMs: number): { title: string; estMs: number; ms: number }[] {
  const times: { title: string; estMs: number; ms: number }[] = []
  for (const [index, step] of plan.steps.entries()) {
    const ms = index < plan.done ? step.realMs : index === plan.done ? endElapsedMs - plan.stepAt : undefined
    if (ms !== undefined) {
      times.push({ title: step.title, estMs: Math.round(step.estMs), ms: Math.max(0, Math.round(ms)) })
    }
  }
  return times
}

const fmtMin = (ms: number): string => `${Math.round((ms / 60000) * 10) / 10} min`

/** A similar run as Haiku sees it: summary, duration and, when stored, its real steps (`Leer 2 · Probar 5`, minutes rounded). */
function similarLine(run: WaitSample, index: number): string {
  const steps = run.steps === undefined || run.steps.length === 0 ? '' : ` (pasos reales: ${run.steps.map(step => `${clipTitle(step.title, 30)} ${Math.max(1, Math.round(step.ms / 60000))}`).join(' · ')})`
  return `${index + 1}. ${run.summary} — ${fmtMin(run.durationMs)}${steps}`
}

/** Asks Haiku (one call) to split the work into 3 to 6 steps with minutes and a criterion; undefined (and logged) when the reply is not a valid plan. */
export async function askPlan($: EngineInterface, ask: { text: string; totalMs: number; id: string; similar: readonly WaitSample[] }): Promise<ParsedStep[] | undefined> {
  const runs = ask.similar.length === 0 ? 'none' : `\n${ask.similar.map(similarLine).join('\n')}`
  const prompt =
    'Divide en 3 a 6 pasos, en orden, el trabajo de un agente de programación; estima los minutos de cada paso (la suma debe ser parecida a duracion_total) y di cuándo está terminado. ' +
    'Si hay tareas_parecidas, imita su reparto de tiempo y sus pasos reales. ' +
    'Cada paso es una fase con resultado visible (leer, planificar, editar, probar, informar), no un archivo ni un comando; omite las fases que la tarea no necesita. ' +
    'El criterio "listo cuando" debe poder verse en las llamadas de herramientas: un archivo editado o creado, un comando o una prueba ejecutados con éxito, un informe escrito; nunca una intención ni un estado interno. ' +
    'Responde solo con una línea por paso, con el formato N. <título de hasta 6 palabras> — M min — listo cuando: <criterio de hasta 12 palabras>, sin texto extra ni negritas.\n' +
    '<example>Con la tarea "corregir el error de paginación" y 6 min en total, la respuesta es:\n1. Localizar la causa — 2 min — listo cuando: se leyó el código de paginación\n2. Corregir y probar — 3 min — listo cuando: se editó el archivo y las pruebas pasaron\n3. Informar del resultado — 1 min — listo cuando: el informe final está escrito</example>\n' +
    '<example>Con la tarea "migrar la base de datos" y 25 min en total, la respuesta es:\n1. Leer el esquema actual — 3 min — listo cuando: se leyeron los archivos del esquema\n2. Planificar la migración — 3 min — listo cuando: se creó el documento del plan\n3. Escribir los scripts — 8 min — listo cuando: se crearon los scripts de migración\n4. Probar con datos reales — 9 min — listo cuando: el comando de migración terminó con éxito\n5. Informar — 2 min — listo cuando: el informe final está escrito</example>\n\n' +
    `<tarea>${ask.text.slice(0, 1500)}</tarea>\n<duracion_total>${fmtMin(ask.totalMs)}</duracion_total>\n<tareas_parecidas>${runs}</tareas_parecidas>`
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 400, timeoutMs: 15000 })
  const steps = reply.isAnswered ? parsePlan(reply.text) : undefined
  logReestimate(
    steps === undefined
      ? `${ask.id} plan failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'}`
      : `${ask.id} plan ok steps=${steps.length} total=${fmtMin(ask.totalMs)} criteria=${steps.every(step => step.criterion !== undefined) ? 'yes' : steps.some(step => step.criterion !== undefined) ? 'some' : 'no'}`,
  )
  return steps
}

/**
 * Asks Haiku (one call) whether the current step is done: evidence first, then `terminado: sí|no`. No minutes, no
 * previous answer and no calendar are shown (they anchored the judge in v2). Undefined (and logged) when neither part reads.
 */
export async function askDone(
  $: EngineInterface,
  ask: { mission: string; plan: PlanState; elapsedMs: number; activity: string; calls: string; said?: string; thinking?: string; id: string },
): Promise<{ done?: boolean; evidence?: string } | undefined> {
  const { plan } = ask
  const current = plan.steps[plan.done]
  const following = plan.steps[plan.done + 1]
  const lineOf = (step: PlanStep | undefined, index: number): string =>
    step === undefined ? 'ninguno' : `${index + 1}. ${step.title}${step.criterion === undefined ? '' : ` · listo cuando: ${step.criterion}`}`
  const prompt =
    'Un agente de programación sigue un plan de pasos en orden. Decide si el paso actual ya está terminado, según lo que muestran <llamadas> y <actividad>. ' +
    'Responde solo con dos líneas, la evidencia primero:\nevidencia: <cita corta de <llamadas>, o de <dice_el_agente> si <llamadas> la respalda, o ninguna>\nterminado: sí|no\n\n' +
    'Reglas:\n' +
    '- terminado es sí solo si puedes citar en evidencia una llamada de <llamadas> que cumple lo que dice "listo cuando" del paso actual, o que ya es trabajo propio de <paso_siguiente> (entonces el actual acabó). Sin esa cita, terminado es no.\n' +
    '- <dice_el_agente> es lo que el agente afirma, no una prueba. Un plan anunciado ("leeré, editaré y probaré") no es evidencia.\n' +
    '- Si dudas o no hay evidencia, responde no. No des minutos ni números.\n\n' +
    '<example>Paso actual: Editar el módulo · listo cuando: se editó el archivo y se ejecutaron las pruebas. <llamadas> termina con "✓ Edita parser.ts" y "✓ Ejecuta las pruebas del parser". Respuesta:\nevidencia: ✓ Ejecuta las pruebas del parser\nterminado: sí</example>\n' +
    '<example>Paso actual: Leer el código · listo cuando: se leyeron los archivos de pagos. <llamadas> solo tiene "✓ Lee config.ts" y <dice_el_agente> dice "voy a leer todo el módulo de pagos". Respuesta:\nevidencia: ninguna\nterminado: no</example>\n\n' +
    `<mision>${ask.mission.slice(0, 1500)}</mision>\n` +
    `<paso_actual>${lineOf(current, plan.done)}</paso_actual>\n` +
    `<paso_siguiente>${lineOf(following, plan.done + 1)}</paso_siguiente>\n` +
    `<actividad>\n${ask.activity}\n</actividad>\n` +
    `<llamadas>\n${ask.calls}\n</llamadas>\n` +
    (ask.said === undefined || ask.said === '' ? '' : `<dice_el_agente>\n${ask.said}\n</dice_el_agente>\n`) +
    (ask.thinking === undefined ? '' : `<pensando>${ask.thinking}</pensando>\n`) +
    '\nResponde solo con las dos líneas evidencia: y terminado:.'
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 120, timeoutMs: 15000 })
  const parsed = reply.isAnswered ? parseVerdict(reply.text) : {}
  if (parsed.done === undefined) {
    logReestimate(`${ask.id} plan check failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'} elapsed=${fmtMin(ask.elapsedMs)}`)
  }
  return parsed.done === undefined && parsed.evidence === undefined ? undefined : parsed
}

/** Asks Haiku (one call) to rewrite the steps after the current one (titles, criteria and split), from the steps done and the run's history; undefined (and logged) when the reply does not parse. */
export async function askReplan(
  $: EngineInterface,
  ask: { mission: string; plan: PlanState; elapsedMs: number; history: string; id: string },
): Promise<ParsedStep[] | undefined> {
  const { plan } = ask
  const into = ask.elapsedMs - plan.stepAt
  const done = plan.steps
    .slice(0, plan.done)
    .map((step, index) => `${index + 1}. ${step.title} · previsto ${fmtMin(step.estMs)} · real ${fmtMin(step.realMs ?? 0)}`)
  const current = plan.steps[plan.done]
  const pending = plan.steps
    .slice(plan.done + 1)
    .map((step, index) => `${plan.done + index + 2}. ${step.title} · reparto ${fmtMin(step.estMs)}${step.criterion === undefined ? '' : ` · listo cuando: ${step.criterion}`}`)
  const max = MAX_TOTAL_STEPS - plan.done - 1
  const prompt =
    'Un agente de programación sigue un plan de pasos. Reescribe solo los pasos que faltan después del paso actual (títulos, criterios y reparto de minutos), según lo que muestra <historial> y lo que tardaron los pasos hechos. ' +
    `Responde solo con una línea por paso, con el formato N. <título de hasta 6 palabras> — M min — listo cuando: <criterio visible en llamadas de herramientas>, numeradas desde ${plan.done + 2}, sin texto extra ni negritas.\n\n` +
    'Reglas:\n' +
    `- Como máximo ${max} líneas. Si el paso actual es el último, responde solo la palabra ninguno.\n` +
    '- Cada paso es una fase con resultado visible (leer, editar, probar, informar), no un archivo ni un comando.\n' +
    '- Los minutos son un reparto entre los pasos, no un total: el programa los ajusta para que la suma no cambie. <pasos_pendientes> es solo referencia: corrígelo si el historial lo contradice. No repitas el paso actual ni pasos ya hechos.\n\n' +
    '<example>El paso actual es el 2 de 4 (corregir el error) y quedan por hacer probar e informar. Respuesta:\n3. Probar con los casos reales — 4 min — listo cuando: el comando de pruebas terminó con éxito\n4. Informar del resultado — 1 min — listo cuando: el informe final está escrito</example>\n' +
    '<example>El paso actual es informar y es el último. Respuesta:\nninguno</example>\n\n' +
    `<mision>${ask.mission.slice(0, 1500)}</mision>\n` +
    `<pasos_hechos>\n${done.length === 0 ? 'ninguno' : done.join('\n')}\n</pasos_hechos>\n` +
    `<paso_actual>${plan.done + 1}. ${current?.title ?? ''} · previsto ${fmtMin(plan.stepEstMs)} · llevas ${fmtMin(into)} · quedan ${fmtMin(Math.max(0, plan.stepEndAt - ask.elapsedMs))}</paso_actual>\n` +
    `<pasos_pendientes>\n${pending.length === 0 ? 'ninguno' : pending.join('\n')}\n</pasos_pendientes>\n` +
    `<historial>\n${ask.history}\n</historial>\n` +
    '\nResponde solo con las líneas N. título — M min — listo cuando: criterio, o la palabra ninguno si el paso actual es el último.'
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 400, timeoutMs: 15000 })
  const steps = reply.isAnswered ? parseReplan(reply.text, plan.done + 2, max) : undefined
  logReestimate(
    steps === undefined
      ? `${ask.id} plan replan failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'}`
      : `${ask.id} plan replan ok steps=${steps.length}${steps.length > 0 && !new RegExp(`^\\s*\\**${plan.done + 2}[.)]`).test(reply.text) ? ' renumbered' : ''}`,
  )
  return steps
}

/**
 * Log line of a plan check, for `/agents-debug`: `plan check <kind> terminado=sí|no|? evidencia="…" said=N → advanced|kept|grown`.
 * `said` is how many of the agent's text blocks the prompt carried (0 across planned runs means the host sends none).
 */
export const logPlanCheck = (
  id: string,
  kind: string,
  verdict: { done?: boolean; evidence?: string } | undefined,
  outcome: 'advanced' | 'kept' | 'grown',
  plan: PlanState,
  said: number,
  extra: string = '',
): void =>
  logReestimate(
    `${id} plan check ${kind} terminado=${verdict?.done === undefined ? '?' : verdict.done ? 'sí' : 'no'} evidencia=${JSON.stringify((verdict?.evidence ?? '').slice(0, 60))} said=${said} → ${outcome} step=${Math.min(plan.done + 1, plan.steps.length)}/${plan.steps.length} factor=${plan.factor.toFixed(2)}${extra}`,
  )
