import type { EngineInterface } from 'claude-code'

import type { WaitSample } from '../types'

import { MAX_PERCENT, OVERDUE_GRACE_MS, REESTIMATE_GAP_MS, logReestimate, wordsOf } from './estimates'

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
// The current step is checked at these fractions of its estimated duration.
export const CHECK_FRACTIONS = [0.5, 0.8, 0.95] as const
// Two checks are never closer than this, and a step goes at most this long without a step-count check.
const CHECK_GAP_MS = 60_000
const CHECK_MAX_MS = 5 * 60_000
const FACTOR_MIN = 0.5
const FACTOR_MAX = 3

export type PlanStep = {
  title: string
  /** Estimated duration (ms), unscaled: the factor applies to the steps still to run. */
  estMs: number
  /** Real duration once finished. */
  realMs?: number
  /** Minutes come from a replan (already informed by real times): the factor does not scale them again. */
  fixed?: boolean
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
  /** The current step's estimated duration when it began (or was lengthened), the base of its 50% / 80% / 95% checks. */
  stepEstMs: number
  /** How many of the 50% / 80% / 95% checks the current step has had (0 to 3). */
  fired: number
  /** The bar never shows less than this percent. */
  anchor: number
  /** Clock time of the latest check of any kind / of the latest step-count check. */
  askedAt: number
  /** Clock time a call's words last pointed at a later step: the next tick asks the count (see `callPointsAhead`). */
  hintAt?: number
  countAt: number
  /** The latest check's number, so an older answer is dropped. */
  seq: number
  /** The run's activity counts when the current step began (G7): the "since the current step" summary is the difference. */
  countsAtStep?: Record<string, number>
  /** Calls the run had finished at the latest check (G1: a step only advances if calls were added since). */
  callsAtCheck?: number
  /** The `done` a replan without a step change was asked at: a stuck step is replanned once, not at every overdue check. */
  replannedDone?: number
}

/** Whether a first estimate switches a plan on: only the first answer (`askSeq` 1) and only when it is long. */
export const shouldPlan = (askSeq: number | undefined, etaMs: number, enabled: boolean = PLAN_ENABLED): boolean =>
  enabled && askSeq === 1 && etaMs > PLAN_MIN_MS

/** The steps of a plan reply: one `N. <title> — M min` line each, 3 to 6, numbered in order; undefined for anything else (a cut reply included). */
export function parsePlan(reply: string): { title: string; minutes: number }[] | undefined {
  const lines = reply.replaceAll('**', '').split('\n').map(line => line.trim()).filter(line => line !== '')
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

/**
 * Haiku's reply to a plan check: `paso: N` and `falta: M`, each found by key over the first 3 non-empty lines (bold, `~`
 * and `min` ignored, any order). `step` only when 1 <= N <= total; each part is absent when it does not read.
 */
export function parseStepReply(text: string, total: number): { step?: number; leftMin?: number } {
  const lines = text
    .replaceAll('**', '')
    .replaceAll('~', '')
    .replace(/\bmin(?:utos?)?\b\.?/gi, '')
    .split('\n')
    .map(line => line.trim())
    .filter(line => line !== '')
    .slice(0, 3)
  const read = (key: string): string | undefined => {
    for (const line of lines) {
      const found = new RegExp(`^${key}\\s*:\\s*(\\d+(?:[.,]\\d+)?)\\b`, 'i').exec(line)?.[1]
      if (found !== undefined) {
        return found.replace(',', '.')
      }
    }
    return undefined
  }
  const step = Number.parseInt(read('paso') ?? '', 10)
  const left = Number.parseFloat(read('falta') ?? '')
  return {
    ...(step >= 1 && step <= total ? { step } : {}),
    ...(Number.isFinite(left) ? { leftMin: left } : {}),
  }
}

/**
 * The lines of a replan reply: `ninguno` alone gives []; else 1 to `max` lines in `parsePlan`'s format, numbered
 * consecutively from `from` (the 1-based number after the current step) or from 1 (Haiku often restarts at 1; the
 * numbers are dropped, only the order counts). `ninguno` may carry case and a final period. Anything else, `ninguno` mixed with lines included, is undefined.
 */
export function parseReplan(reply: string, from: number, max: number): { title: string; minutes: number }[] | undefined {
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
  const steps: { title: string; minutes: number }[] = []
  for (const [index, line] of lines.entries()) {
    const found = /^(\d+)[.)]\s+(.{1,120}?)\s+[—–-]\s+(\d+(?:[.,]\d+)?)\s*min\.?$/i.exec(line)
    const minutes = Number.parseFloat((found?.[3] ?? '').replace(',', '.'))
    if (found === null || Number.parseInt(found[1] ?? '', 10) !== first + index || !(minutes > 0) || minutes > MAX_STEP_MIN) {
      return undefined
    }
    steps.push({ title: (found[2] ?? '').slice(0, TITLE_CHARS), minutes })
  }
  return steps
}

const clamp = (value: number, low: number, high: number): number => Math.min(high, Math.max(low, value))

/** A step's duration to plan with: replanned (`fixed`) minutes stay, the others follow the factor. One home, so no path scales a fixed step twice. */
export const scaledMs = (step: PlanStep, factor: number): number => (step.fixed === true ? step.estMs : step.estMs * factor)

/** Time of the steps still to run after the current one, scaled by the factor (replanned steps unscaled). */
export const restMs = (plan: PlanState): number => plan.steps.slice(plan.done + 1).reduce((sum, step) => sum + scaledMs(step, plan.factor), 0)

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
const clipTitle = (title: string): string => (title.length <= STEP_TITLE_CHARS ? title : `${title.slice(0, STEP_TITLE_CHARS - 1).trimEnd()}…`)

/** What a card with a plan shows: the whole-run percent (the bar's), the current step's title and the time left; undefined without a plan or with `enabled` false. */
export function planView(
  run: { plan?: PlanState; startedAt: number },
  now: number,
  enabled: boolean = PLAN_ENABLED,
): { percent: number; step?: string; isWrappingUp: boolean; leftMs: number } | undefined {
  const { plan } = run
  if (!enabled || plan === undefined) {
    return undefined
  }
  const elapsed = now - run.startedAt
  // All steps done while the run still runs: no time left to state, only that it is wrapping up (the bar stays under 100%).
  const isLast = plan.done >= plan.steps.length
  return {
    percent: planBar(plan, elapsed),
    ...(isLast ? {} : { step: clipTitle(plan.steps[plan.done]?.title ?? '') }),
    isWrappingUp: isLast,
    leftMs: isLast ? 0 : planLeftMs(plan, elapsed),
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
  const next = steps[done]
  const stepEstMs = next === undefined ? 0 : Math.round(scaledMs(next, factor))
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
 * The plan after Haiku named step `step` (1-based) as the current one; undefined when it does not advance. It advances
 * only when calls were added since the last check (`historyGrew`), and the count never decreases. Jumps of several steps
 * are accepted (fast steps happen; owner, 2026-11-03: the +1 cap of G1 may come back later); `applyCount` splits the time
 * across them. The caller stamps `countsAtStep` (G7).
 */
export function applyStep(plan: PlanState, step: number, elapsedMs: number, now: number, historyGrew: boolean): PlanState | undefined {
  const done = step - 1
  if (!historyGrew || done <= plan.done) {
    return undefined
  }
  return applyCount(plan, done, elapsedMs, now)
}

/**
 * The plan with the current step's end moved by Haiku's `leftMin`. G3: clamped to 0.5 min .. 3x the step estimate,
 * blended 50/50 with the remaining time, never shortening it more than 30% per check. G4: the anchor is the bar shown
 * first; then the step estimate and the 50% / 80% / 95% `fired` follow the new end, as in `applyOverdue`.
 */
export function applyLeft(plan: PlanState, leftMin: number, elapsedMs: number): PlanState {
  const remaining = Math.max(0, plan.stepEndAt - elapsedMs)
  const asked = clamp(leftMin * 60_000, 30_000, Math.max(30_000, 3 * plan.stepEstMs))
  const blended = Math.max((remaining + asked) / 2, remaining * 0.7)
  const stepEndAt = elapsedMs + Math.round(blended)
  const stepEstMs = Math.max(1000, stepEndAt - plan.stepAt)
  const fired = CHECK_FRACTIONS.filter(fraction => elapsedMs - plan.stepAt >= stepEstMs * fraction).length
  return { ...plan, stepEndAt, stepEstMs, fired, anchor: planBar(plan, elapsedMs) }
}

/**
 * The plan with its pending steps (those after the current one) replaced by a replan's `steps`, marked `fixed`; done
 * and current steps stay. The caller reads `elapsedMs` when the answer arrives, so the anchor is the bar shown now.
 * The new minutes are scaled so they add up to 0.5 to 2 times the old rest: a short round answer cannot make the
 * percent jump. `[]` (no step after the current one) is believed only when at most one step was pending; otherwise
 * the plan is returned unchanged (the same object), like a reply that did not parse.
 */
export function applyReplan(plan: PlanState, steps: readonly { title: string; minutes: number }[], elapsedMs: number): PlanState {
  const pending = plan.steps.length - plan.done - 1
  // `[]` drops at most one pending step; with none pending there is no rest to clamp new steps against, so they are not added.
  if ((steps.length === 0 && pending > 1) || (steps.length > 0 && pending <= 0)) {
    return plan
  }
  const fresh = steps.slice(0, Math.max(0, MAX_TOTAL_STEPS - plan.done - 1))
  const wanted = fresh.reduce((sum, step) => sum + step.minutes * 60_000, 0)
  const old = restMs(plan)
  const scale = old <= 0 || wanted <= 0 ? 1 : clamp(wanted, old * 0.5, old * 2) / wanted
  const replaced = fresh.map(step => ({ title: step.title, estMs: Math.max(1000, Math.round(step.minutes * 60_000 * scale)), fixed: true }))
  return { ...plan, steps: [...plan.steps.slice(0, plan.done + 1), ...replaced], anchor: planBar(plan, elapsedMs) }
}

/**
 * Whether a check that was just applied also replans the pending steps: when the step advanced, when it was overdue, or
 * when this check is the one that fired the last fraction (95%). A 50% / 80% check, or a hint after the 95% one, does not (cost).
 */
export const shouldReplan = (kind: 'progress' | 'overdue', firedBefore: number, firedNow: number, advanced: boolean): boolean =>
  advanced || kind === 'overdue' || (firedBefore < CHECK_FRACTIONS.length && firedNow === CHECK_FRACTIONS.length)

/**
 * Whether the plan is checked now, and how: `overdue` (the step is past its estimate plus the grace: ask its remaining
 * minutes) or `progress` (50% / 80% / 95% of the step's estimated duration, or 5 min without a count: ask how many steps are
 * done), also when a call hinted a later step (`hintAt`). None once every step is done. Never closer than 1 min to the last check (30 s when overdue).
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
  // The latest fraction reached that has not fired yet; reaching two at once (a long gap) counts as the later one.
  for (let index = CHECK_FRACTIONS.length - 1; index >= 0; index -= 1) {
    if (plan.fired <= index && into >= plan.stepEstMs * (CHECK_FRACTIONS[index] ?? 1)) {
      return { kind: 'progress', fired: index + 1 }
    }
  }
  // A call that reads like a later step, or 5 min without a count.
  const isHinted = plan.hintAt !== undefined && plan.hintAt > plan.askedAt
  return isHinted || now - plan.countAt >= CHECK_MAX_MS ? { kind: 'progress', fired: plan.fired } : undefined
}

/**
 * True when a call's text (its description, or Haiku's reading of the command) shares more words with a later step's
 * title than with the current one's: a free hint that the agent moved on, which Haiku then confirms. Never decides alone.
 */
export function callPointsAhead(plan: PlanState, text: string): boolean {
  if (plan.done >= plan.steps.length - 1) {
    return false
  }
  const words = wordsOf(text)
  const shared = (title: string): number => [...wordsOf(title)].filter(word => words.has(word)).length
  const now = shared(plan.steps[plan.done]?.title ?? '')
  const ahead = Math.max(...plan.steps.slice(plan.done + 1).map(step => shared(step.title)))
  return ahead >= 1 && ahead > now
}

const fmtMin = (ms: number): string => `${Math.round((ms / 60000) * 10) / 10} min`

/** Asks Haiku (one call) to split the work into 3 to 6 steps with minutes; undefined (and logged) when the reply is not a valid plan. */
export async function askPlan($: EngineInterface, ask: { text: string; totalMs: number; id: string; similar: readonly WaitSample[] }): Promise<{ title: string; minutes: number }[] | undefined> {
  const runs = ask.similar.length === 0 ? 'none' : `\n${ask.similar.map((run, index) => `${index + 1}. ${run.summary} — ${fmtMin(run.durationMs)}`).join('\n')}`
  const prompt =
    'Divide en 3 a 6 pasos, en orden, el trabajo de un agente de programación y estima los minutos de cada paso; la suma debe ser parecida a duracion_total. ' +
    'Si hay tareas_parecidas, imita su reparto de tiempo. ' +
    'Cada paso es una fase con resultado visible (leer, planificar, editar, probar, informar), no un archivo ni un comando; omite las fases que la tarea no necesita. ' +
    'Responde solo con una línea por paso, con el formato N. <título de hasta 6 palabras> — M min, sin texto extra ni negritas.\n' +
    '<example>Con la tarea "corregir el error de paginación" y 6 min en total, la respuesta es:\n1. Localizar la causa — 2 min\n2. Corregir y probar — 3 min\n3. Informar del resultado — 1 min</example>\n' +
    '<example>Con la tarea "migrar la base de datos" y 25 min en total, la respuesta es:\n1. Leer el esquema actual — 3 min\n2. Planificar la migración — 3 min\n3. Escribir los scripts — 8 min\n4. Probar con datos reales — 9 min\n5. Informar — 2 min</example>\n\n' +
    `<tarea>${ask.text.slice(0, 1500)}</tarea>\n<duracion_total>${fmtMin(ask.totalMs)}</duracion_total>\n<tareas_parecidas>${runs}</tareas_parecidas>`
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 200, timeoutMs: 15000 })
  const steps = reply.isAnswered ? parsePlan(reply.text) : undefined
  logReestimate(
    steps === undefined
      ? `${ask.id} plan failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'}`
      : `${ask.id} plan ok steps=${steps.length} total=${fmtMin(ask.totalMs)}`,
  )
  return steps
}

/** Asks Haiku (one call) for the current step and the minutes left in it (`paso: N`, `falta: M`); undefined (and logged) when neither reads. */
export async function askStepCheck(
  $: EngineInterface,
  ask: { mission: string; plan: PlanState; elapsedMs: number; activity: string; calls: string; thinking?: string; id: string },
): Promise<{ step?: number; leftMin?: number } | undefined> {
  const { plan } = ask
  const total = plan.steps.length
  const into = ask.elapsedMs - plan.stepAt
  const lineOf = (step: PlanStep, index: number): string => {
    if (index < plan.done) {
      return `${index + 1}. ${step.title} · previsto ${fmtMin(step.estMs)} · real ${fmtMin(step.realMs ?? 0)}`
    }
    if (index === plan.done) {
      return `${index + 1}. ${step.title} · previsto ${fmtMin(plan.stepEstMs)} · en curso ${fmtMin(into)}`
    }
    return `${index + 1}. ${step.title} · previsto ${fmtMin(scaledMs(step, plan.factor))}`
  }
  const prompt =
    'Un agente de programación sigue un plan de pasos en orden. Indica en qué paso está ahora y cuántos minutos le faltan para terminarlo. Responde solo con dos líneas, sin nada más:\npaso: N\nfalta: M\n\n' +
    'Reglas:\n' +
    '- paso es el número (desde 1) del paso cuyo tipo de trabajo describe mejor lo que muestran <actividad> y <llamadas>. Un paso ya es el actual en cuanto empezó su tipo de trabajo; no esperes a que acabe el anterior. Nunca devuelvas un número menor que <paso_anterior>.\n' +
    '- Si <paso_anterior> aún encaja con la actividad, repítelo; si la actividad ya es de otro paso, avanza, aunque sea por poco.\n' +
    '- falta son minutos enteros desde ahora hasta acabar ese paso, según el trabajo que queda, no según el plan. Si está casi terminado o ya pasó de lo previsto, responde el tiempo real que ves que queda (mínimo 1), no 0.\n' +
    '- <referencia_calendario> es solo referencia, no es una prueba: no decide el paso.\n\n' +
    '<example>El agente lleva 6 pasos; hasta ahora leyó y editó módulos del paso 3 y acaba de lanzar las pruebas que lo cubren, con un solo fallo pendiente. Respuesta:\npaso: 3\nfalta: 2</example>\n' +
    '<example>Plan de 4 pasos; el agente acaba de crear los archivos nuevos del paso 4 y aún no ha ejecutado nada, y el paso suele durar bastante. Respuesta:\npaso: 4\nfalta: 9</example>\n' +
    '<example>Plan de 5 pasos; sigue leyendo código del paso 2, ya pasó de lo previsto y no ha editado nada. Respuesta:\npaso: 2\nfalta: 6</example>\n\n' +
    `<mision>${ask.mission.slice(0, 1500)}</mision>\n` +
    `<pasos>\n${plan.steps.map(lineOf).join('\n')}\n</pasos>\n` +
    `<paso_anterior>${Math.min(plan.done + 1, total)}</paso_anterior>\n` +
    `<actividad>\n${ask.activity}\n</actividad>\n` +
    `<referencia_calendario>según el calendario van ${fmtMin(ask.elapsedMs)} de ${fmtMin(planEndAt(plan))} (solo referencia, no es una prueba)</referencia_calendario>\n` +
    `<llamadas>\n${ask.calls}\n</llamadas>\n` +
    (ask.thinking === undefined ? '' : `<pensando>${ask.thinking}</pensando>\n`) +
    '\nResponde solo con las dos líneas paso: N y falta: M.'
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 40, timeoutMs: 15000 })
  const parsed = reply.isAnswered ? parseStepReply(reply.text, total) : {}
  if (parsed.step === undefined || parsed.leftMin === undefined) {
    logReestimate(`${ask.id} plan check ${parsed.step === undefined && parsed.leftMin === undefined ? 'failed' : 'partial'}: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'} elapsed=${fmtMin(ask.elapsedMs)}`)
  }
  return parsed.step === undefined && parsed.leftMin === undefined ? undefined : parsed
}

/** Asks Haiku (one call) for the steps after the current one, from the steps done, the run's history and the plan so far; undefined (and logged) when the reply does not parse. */
export async function askReplan(
  $: EngineInterface,
  ask: { mission: string; plan: PlanState; elapsedMs: number; history: string; id: string },
): Promise<{ title: string; minutes: number }[] | undefined> {
  const { plan } = ask
  const into = ask.elapsedMs - plan.stepAt
  const done = plan.steps
    .slice(0, plan.done)
    .map((step, index) => `${index + 1}. ${step.title} · previsto ${fmtMin(step.estMs)} · real ${fmtMin(step.realMs ?? 0)}`)
  const current = plan.steps[plan.done]
  const pending = plan.steps.slice(plan.done + 1).map((step, index) => `${plan.done + index + 2}. ${step.title} · previsto ${fmtMin(scaledMs(step, plan.factor))}`)
  const max = MAX_TOTAL_STEPS - plan.done - 1
  const prompt =
    'Un agente de programación sigue un plan de pasos. Reescribe solo los pasos que faltan después del paso actual, según lo que muestra <historial> y lo que tardaron los pasos hechos. ' +
    `Responde solo con una línea por paso, con el formato N. <título de hasta 6 palabras> — M min, numeradas desde ${plan.done + 2}, sin texto extra ni negritas.\n\n` +
    'Reglas:\n' +
    `- Como máximo ${max} líneas. Si el paso actual es el último, responde solo la palabra ninguno.\n` +
    '- Cada paso es una fase con resultado visible (leer, editar, probar, informar), no un archivo ni un comando.\n' +
    '- Los minutos son lo que crees que tardará cada paso, según el ritmo real de los pasos hechos; <pasos_pendientes> es solo referencia: corrígelo si el historial lo contradice. No repitas el paso actual ni pasos ya hechos.\n\n' +
    '<example>El paso actual es el 2 de 4 (corregir el error) y quedan por hacer probar e informar. Respuesta:\n3. Probar con los casos reales — 4 min\n4. Informar del resultado — 1 min</example>\n' +
    '<example>El paso actual es informar y es el último. Respuesta:\nninguno</example>\n\n' +
    `<mision>${ask.mission.slice(0, 1500)}</mision>\n` +
    `<pasos_hechos>\n${done.length === 0 ? 'ninguno' : done.join('\n')}\n</pasos_hechos>\n` +
    `<paso_actual>${plan.done + 1}. ${current?.title ?? ''} · previsto ${fmtMin(plan.stepEstMs)} · llevas ${fmtMin(into)} · quedan ${fmtMin(Math.max(0, plan.stepEndAt - ask.elapsedMs))}</paso_actual>\n` +
    `<pasos_pendientes>\n${pending.length === 0 ? 'ninguno' : pending.join('\n')}\n</pasos_pendientes>\n` +
    `<historial>\n${ask.history}\n</historial>\n` +
    '\nResponde solo con las líneas N. título — M min, o la palabra ninguno si el paso actual es el último.'
  const reply = await $.model.complete({ model: 'haiku', prompt, maxTokens: 250, timeoutMs: 15000 })
  const steps = reply.isAnswered ? parseReplan(reply.text, plan.done + 2, max) : undefined
  logReestimate(
    steps === undefined
      ? `${ask.id} plan replan failed: ${reply.isAnswered ? `reply ${JSON.stringify(reply.text.slice(0, 60))}` : 'no answer'}`
      : `${ask.id} plan replan ok steps=${steps.length}${steps.length > 0 && !new RegExp(`^\\s*\\**${plan.done + 2}[.)]`).test(reply.text) ? ' renumbered' : ''}`,
  )
  return steps
}

/** Log line of an applied (or ignored) plan check, for `/agents-debug`. */
export const logPlanCheck = (id: string, kind: string, from: PlanState, to: PlanState | undefined): void =>
  logReestimate(`${id} plan ${kind} ${to === undefined ? `kept done=${from.done}/${from.steps.length}` : `ok done=${from.done}→${to.done}/${to.steps.length}`} factor=${(to ?? from).factor.toFixed(2)}`)
