import type { EngineInterface } from 'claude-code'

import { MAX_PERCENT, OVERDUE_GRACE_MS, REESTIMATE_GAP_MS, logReestimate } from './estimates'

// Step-based progress for long agent cards. Isolated: agents.tsx calls it behind `PLAN_ENABLED`; rollback is that constant
// set to false, or deleting this file and its call sites. Every function here is pure or asks Haiku; none writes state.

/** The one switch: false and the cards behave exactly as before this module. */
export const PLAN_ENABLED = true
/** An agent whose first estimate is longer than this gets a step plan (may become 10 min). */
export const PLAN_MIN_MS = 5 * 60_000
const MIN_STEPS = 3
const MAX_STEPS = 6
const MAX_STEP_MIN = 24 * 60
const TITLE_CHARS = 80
// The current step is checked at these fractions of its estimated duration.
const CHECK_FRACTIONS = [0.5, 0.8] as const
// Two checks are never closer than this, and a step goes at most this long without a step-count check.
const CHECK_GAP_MS = 60_000
const CHECK_MAX_MS = 20 * 60_000
const FACTOR_MIN = 0.5
const FACTOR_MAX = 3

export type PlanStep = {
  title: string
  /** Estimated duration (ms), unscaled: the factor applies to the steps still to run. */
  estMs: number
  /** Real duration once finished. */
  realMs?: number
}

/** The plan stored on a run. Times `...At` of the run are elapsed ms (since the spawn); `askedAt`/`countAt` are clock times. */
export type PlanState = {
  steps: PlanStep[]
  /** Real over estimated time of the finished steps, 0.5 to 3: scales the steps still to run. */
  factor: number
  /** Steps finished (the count can only grow). */
  done: number
  /** When the current step began / is expected to end. */
  stepAt: number
  stepEndAt: number
  /** The current step's estimated duration when it began (or was lengthened), the base of its 50% / 80% checks. */
  stepEstMs: number
  /** How many of the 50% / 80% checks the current step has had (0 to 2). */
  fired: number
  /** The bar never shows less than this percent. */
  anchor: number
  /** Clock time of the latest check of any kind / of the latest step-count check. */
  askedAt: number
  countAt: number
  /** The latest check's number, so an older answer is dropped. */
  seq: number
}

/** Whether a first estimate switches a plan on: only the first answer (`askSeq` 1) and only when it is long. */
export const shouldPlan = (askSeq: number | undefined, etaMs: number, enabled: boolean = PLAN_ENABLED): boolean =>
  enabled && askSeq === 1 && etaMs > PLAN_MIN_MS

/** The steps of a plan reply: one `N. <title> — M min` line each, 3 to 6, numbered in order; undefined for anything else (a cut reply included). */
export function parsePlan(reply: string): { title: string; minutes: number }[] | undefined {
  const lines = reply.split('\n').map(line => line.trim()).filter(line => line !== '')
  if (lines.length < MIN_STEPS || lines.length > MAX_STEPS) {
    return undefined
  }
  const steps: { title: string; minutes: number }[] = []
  for (const [index, line] of lines.entries()) {
    const found = /^(\d+)[.)]\s+(.{1,120}?)\s+[—–-]\s+(\d+(?:[.,]\d+)?)\s*min\.?$/i.exec(line)
    const minutes = Number.parseFloat((found?.[3] ?? '').replace(',', '.'))
    if (found === null || Number.parseInt(found[1] ?? '', 10) !== index + 1 || !(minutes > 0) || minutes > MAX_STEP_MIN) {
      return undefined
    }
    steps.push({ title: (found[2] ?? '').slice(0, TITLE_CHARS), minutes })
  }
  return steps
}

/** The line `pasos: N` (first line only), as a count; undefined for anything else. */
export function stepsLine(reply: string): number | undefined {
  const found = /^\s*pasos:\s*(\d{1,2})\s*$/i.exec(reply.trim().split('\n')[0] ?? '')?.[1]
  return found === undefined ? undefined : Number.parseInt(found, 10)
}

const clamp = (value: number, low: number, high: number): number => Math.min(high, Math.max(low, value))

/** Time of the steps still to run after the current one, scaled by the factor. */
export const restMs = (plan: PlanState): number => plan.steps.slice(plan.done + 1).reduce((sum, step) => sum + step.estMs, 0) * plan.factor

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

/** What a card with a plan shows; undefined without one or with `enabled` false. */
export function planView(
  run: { plan?: PlanState; startedAt: number },
  now: number,
  enabled: boolean = PLAN_ENABLED,
): { percent: number; text: string; isWrappingUp: boolean; leftMs: number; shown: number; total: number } | undefined {
  const { plan } = run
  if (!enabled || plan === undefined) {
    return undefined
  }
  const elapsed = now - run.startedAt
  const total = plan.steps.length
  // All steps done while the run still runs: no time left to state, only that it is wrapping up (the bar stays under 100%).
  const isLast = plan.done >= total
  return {
    percent: planBar(plan, elapsed),
    text: `${plan.done}/${total} pasos`,
    isWrappingUp: isLast,
    leftMs: isLast ? 0 : planLeftMs(plan, elapsed),
    shown: plan.done,
    total,
  }
}

/** A new plan from parsed steps, their minutes scaled so they add up to the estimate `etaMs`; the bar starts at `anchorPct`. */
export function newPlan(parsed: readonly { title: string; minutes: number }[], etaMs: number, anchorPct: number, now: number): PlanState {
  const sum = parsed.reduce((total, step) => total + step.minutes, 0)
  const steps = parsed.map(step => ({ title: step.title, estMs: Math.max(1000, Math.round((step.minutes / sum) * etaMs)) }))
  const first = steps[0]?.estMs ?? etaMs
  return { steps, factor: 1, done: 0, stepAt: 0, stepEndAt: first, stepEstMs: first, fired: 0, anchor: clamp(anchorPct, 0, MAX_PERCENT), askedAt: now, countAt: now, seq: 1 }
}

/**
 * The plan after Haiku counted `count` steps done at `elapsedMs`; undefined when the count does not grow. While the run
 * runs done may reach y (the card then says it is finishing). Several steps at once split the time since the current one began evenly;
 * the factor is the real over estimated time of every finished step, 0.5 to 3. The bar's anchor keeps what was shown.
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
  const stepEstMs = Math.round((steps[done]?.estMs ?? 0) * factor)
  return { ...plan, steps, factor, done, stepAt: elapsedMs, stepEstMs, stepEndAt: elapsedMs + stepEstMs, fired: 0, anchor: planBar(plan, elapsedMs), countAt: now }
}

/** The plan with its overdue step lengthened to end `remainingMs` after `elapsedMs`; undefined when that is not later. */
export function applyOverdue(plan: PlanState, remainingMs: number, elapsedMs: number): PlanState | undefined {
  const stepEndAt = elapsedMs + remainingMs
  if (stepEndAt <= plan.stepEndAt) {
    return undefined
  }
  const stepEstMs = stepEndAt - plan.stepAt
  const fired = CHECK_FRACTIONS.filter(fraction => elapsedMs - plan.stepAt >= stepEstMs * fraction).length
  return { ...plan, stepEndAt, stepEstMs, fired, anchor: planBar(plan, elapsedMs) }
}

/**
 * Whether the plan is checked now, and how: `overdue` (the step is past its estimate plus the grace: ask its remaining
 * minutes) or `progress` (50% / 80% of the step's estimated duration, or 20 min without a count: ask how many steps are
 * done). None once every step is done. Never closer than 1 min to the last check (30 s when overdue).
 */
export function nextPlanCheck(plan: PlanState, elapsedMs: number, now: number): { kind: 'progress' | 'overdue'; fired: number } | undefined {
  // Every step done: no more checks, only the run's end closes it.
  if (plan.done >= plan.steps.length || now - plan.askedAt < REESTIMATE_GAP_MS) {
    return undefined
  }
  if (elapsedMs >= plan.stepEndAt + OVERDUE_GRACE_MS) {
    return { kind: 'overdue', fired: plan.fired }
  }
  if (now - plan.askedAt < CHECK_GAP_MS) {
    return undefined
  }
  const into = elapsedMs - plan.stepAt
  const [half, late] = CHECK_FRACTIONS
  if (plan.fired < 2 && into >= plan.stepEstMs * late) {
    return { kind: 'progress', fired: 2 }
  }
  if (plan.fired < 1 && into >= plan.stepEstMs * half) {
    return { kind: 'progress', fired: 1 }
  }
  return now - plan.countAt >= CHECK_MAX_MS ? { kind: 'progress', fired: plan.fired } : undefined
}

const fmtMin = (ms: number): string => `${Math.round((ms / 60000) * 10) / 10} min`

/** Asks Haiku (one call) to split the work into 3 to 6 steps with minutes; undefined (and logged) when the reply is not a valid plan. */
export async function askPlan($: EngineInterface, ask: { text: string; totalMs: number; id: string }): Promise<{ title: string; minutes: number }[] | undefined> {
  const prompt =
    'Divide en 3 a 6 pasos, en orden, el trabajo de un agente de programación y estima los minutos de cada paso; la suma debe ser parecida a duracion_total. ' +
    'Responde solo con una línea por paso, con el formato N. <título corto> — M min, sin texto extra.\n' +
    '<example>Con la tarea "migrar la base de datos" y 12 min en total, la respuesta es:\n1. Leer el esquema actual — 2 min\n2. Escribir la migración — 5 min\n3. Probarla con datos reales — 4 min\n4. Documentar el cambio — 1 min</example>\n\n' +
    `<tarea>${ask.text.slice(0, 1500)}</tarea>\n<duracion_total>${fmtMin(ask.totalMs)}</duracion_total>`
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 200, timeoutMs: 15000 })
  const steps = reply.isAnswered ? parsePlan(reply.text) : undefined
  logReestimate(
    steps === undefined
      ? `${ask.id} plan failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'}`
      : `${ask.id} plan ok steps=${steps.length} total=${fmtMin(ask.totalMs)}`,
  )
  return steps
}

/** Asks Haiku how many steps are done (`pasos: N`, first line only); undefined (and logged) when it does not answer well. */
export async function askStepCount(
  $: EngineInterface,
  ask: { mission: string; plan: PlanState; elapsedMs: number; progress: string; id: string },
): Promise<number | undefined> {
  const { plan } = ask
  const prompt =
    'Un agente de programación sigue un plan de pasos en orden. Según su misión y su actividad reciente, cuenta cuántos pasos están terminados (los primeros N del plan). Responde solo con esta línea:\npasos: N\n' +
    '<example>Con un plan de 4 pasos y el agente ya probando lo que construyó en el paso 3, la respuesta es:\npasos: 3</example>\n\n' +
    `<mision>${ask.mission.slice(0, 1500)}</mision>\n` +
    `<pasos>\n${plan.steps.map((step, index) => `${index + 1}. ${step.title}`).join('\n')}\n</pasos>\n` +
    `<ya_transcurrido>${fmtMin(ask.elapsedMs)}</ya_transcurrido>\n` +
    `<pasos_terminados_antes>${plan.done}</pasos_terminados_antes>\n` +
    (ask.progress === '' ? '' : `<progreso>${ask.progress}</progreso>\n`) +
    '\nResponde solo con la línea pasos: N (número entero).'
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 20, timeoutMs: 15000 })
  const count = reply.isAnswered ? stepsLine(reply.text) : undefined
  if (count === undefined || count > plan.steps.length) {
    logReestimate(`${ask.id} plan check failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'} elapsed=${fmtMin(ask.elapsedMs)}`)
    return undefined
  }
  return count
}

/** Log line of an applied (or ignored) plan check, for `/agents-debug`. */
export const logPlanCheck = (id: string, kind: string, from: PlanState, to: PlanState | undefined): void =>
  logReestimate(`${id} plan ${kind} ${to === undefined ? `kept done=${from.done}/${from.steps.length}` : `ok done=${from.done}→${to.done}/${to.steps.length}`} factor=${(to ?? from).factor.toFixed(2)}`)
