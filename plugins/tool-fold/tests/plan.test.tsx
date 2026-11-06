import { expect, mock, test } from 'claude-code/testing'

import { activitySummary, estimateOf, recentCalls, scriptOf, stepTitleChars } from '../hooks/agents'
import { phraseOf } from '../hooks/waiting'
import {
  PLAN_ENABLED,
  PLAN_MIN_MS,
  applyCount,
  applyDone,
  applyLeft,
  applyOverdue,
  applyReplan,
  applyStep,
  askDone,
  askPlan,
  askReplan,
  askStepCheck,
  callPointsAhead,
  growOverdue,
  isGrounded,
  newPlan,
  nextPlanCheck,
  nextProgressCheck,
  overdueGapMs,
  parsePlan,
  parseReplan,
  parseStepReply,
  parseVerdict,
  planBar,
  planLeftMs,
  restMs,
  planView,
  shouldPlan,
  shouldReplan,
  stepTimes,
} from '../hooks/plan'
import type { PlanState } from '../hooks/plan'

const MIN = 60_000
const GOOD = '1. Leer el código — 2 min\n2. Escribir el cambio — 5 min\n3. Probarlo — 2 min\n4. Documentar — 1 min'

/** A 4-step, 10 min plan started at 0. */
const fresh = (): PlanState => newPlan(parsePlan(GOOD) ?? [], 10 * MIN, 0, 0)

test('parsePlan accepts 3 to 6 numbered lines with minutes and nothing else', () => {
  expect(parsePlan(GOOD)?.map(step => step.minutes)).toEqual([2, 5, 2, 1])
  expect(parsePlan('1. A — 2 min\n2. B — 3,5 min\n3. C - 1 min')).toHaveLength(3)
  // Too few, too many, a cut last line, prose, a wrong number.
  expect(parsePlan('1. A — 2 min\n2. B — 3 min')).toBeUndefined()
  expect(parsePlan(Array.from({ length: 7 }, (_, i) => `${i + 1}. P — 1 min`).join('\n'))).toBeUndefined()
  expect(parsePlan('1. A — 2 min\n2. B — 3 min\n3. C — 1 min\n4. Docu')).toBeUndefined()
  expect(parsePlan(`Aquí va:\n${GOOD}`)).toBeUndefined()
  expect(parsePlan('1. A — 2 min\n3. B — 3 min\n4. C — 1 min')).toBeUndefined()
  expect(parsePlan('1. A — 0 min\n2. B — 3 min\n3. C — 1 min')).toBeUndefined()
  expect(parsePlan('**1. A — 2 min**\n\n2. **B** — 3 min\n\n3. C — 1 min')?.map(step => step.title)).toEqual(['A', 'B', 'C'])
})

test('a new plan adds up to the estimate', () => {
  const plan = fresh()
  expect(plan.steps.reduce((sum, step) => sum + step.estMs, 0)).toBe(10 * MIN)
  expect(plan.stepEndAt).toBe(2 * MIN)
})

test('parseStepReply reads paso and falta by key, in any order, with bold, ~ and min around', () => {
  expect(parseStepReply('paso: 3\nfalta: 4', 5)).toEqual({ step: 3, leftMin: 4 })
  expect(parseStepReply('**paso:** 2\n**falta:** ~3 min', 5)).toEqual({ step: 2, leftMin: 3 })
  expect(parseStepReply('falta: ~3 min', 5)).toEqual({ leftMin: 3 })
  expect(parseStepReply('paso: 2', 5)).toEqual({ step: 2 })
  expect(parseStepReply('falta: 7\npaso: 4', 5)).toEqual({ step: 4, leftMin: 7 })
  expect(parseStepReply('\n\nPaso: 1\nFalta: 2,5 minutos', 5)).toEqual({ step: 1, leftMin: 2.5 })
  // Out of range steps give no step; prose gives nothing; only the first 3 lines count.
  expect(parseStepReply('paso: 9\nfalta: 2', 5)).toEqual({ leftMin: 2 })
  expect(parseStepReply('paso: 0\nfalta: 2', 5)).toEqual({ leftMin: 2 })
  expect(parseStepReply('creo que va por el tres', 5)).toEqual({})
  expect(parseStepReply('a\nb\nc\npaso: 2', 5)).toEqual({})
})

test('applyStep accepts jumps, advances only if calls were added, and never goes back', () => {
  const plan = fresh()
  // Haiku says step 4 from done 0: three steps done at once (fast steps are accepted).
  expect(applyStep(plan, 4, 3 * MIN, 3 * MIN, true)?.done).toBe(3)
  const one = applyStep(plan, 2, 3 * MIN, 3 * MIN, true)
  expect(one?.done).toBe(1)
  // No new calls: no advance, whatever Haiku says.
  expect(applyStep(plan, 3, 3 * MIN, 3 * MIN, false)).toBeUndefined()
  // The same step, or an earlier one, changes nothing.
  expect(applyStep(plan, 1, 3 * MIN, 3 * MIN, true)).toBeUndefined()
  expect(applyStep(one as PlanState, 1, 4 * MIN, 4 * MIN, true)).toBeUndefined()
  expect(applyStep(one as PlanState, 2, 4 * MIN, 4 * MIN, true)).toBeUndefined()
  expect(applyStep(one as PlanState, 3, 4 * MIN, 4 * MIN, true)?.done).toBe(2)
})

test('applyLeft clamps to 0.5 min .. 3x the estimate, blends 50/50, shortens at most 30%, and the bar never drops (G3, G4)', () => {
  const plan = fresh()
  // Step 1: 2 min estimate, 1 min in, 1 min remaining. Haiku says 3 min: blend (1 + 3) / 2 = 2 min left.
  const longer = applyLeft(plan, 3, MIN)
  expect(longer.stepEndAt).toBe(MIN + 2 * MIN)
  expect(longer.stepEstMs).toBe(3 * MIN)
  // A huge answer is clamped to 3x the estimate (6 min): blend (1 + 6) / 2.
  expect(applyLeft(plan, 500, MIN).stepEndAt).toBe(MIN + 3.5 * MIN)
  // A tiny answer: remaining 1 min, asked 0.5 min (the floor), blend 0.75 min: 30% rule holds at 0.7 min.
  expect(applyLeft(plan, 0, MIN).stepEndAt).toBe(MIN + 45_000)
  const shrink = applyLeft({ ...plan, stepEndAt: 10 * MIN, stepEstMs: 10 * MIN }, 1, MIN)
  expect(shrink.stepEndAt).toBe(MIN + 6.3 * MIN)
  // The bar never drops when falta grows; the anchor is the bar shown before.
  expect(longer.anchor).toBe(planBar(plan, MIN))
  expect(planBar(longer, MIN)).toBeGreaterThanOrEqual(planBar(plan, MIN))
  // fired follows the new end like an overdue update: 1 min into a 3 min step is 33%.
  expect(longer.fired).toBe(0)
  // Overdue (no time left): the answer extends it from now.
  expect(applyLeft(plan, 2, 3 * MIN).stepEndAt).toBe(3 * MIN + MIN)
})

test('activitySummary counts since the start and since the step began; recentCalls keeps 8, newest last', () => {
  const run = { counts: { read: 5, list: 1, search: 2, edit: 4, run: 3 }, created: 1, testRuns: 2 }
  const plan = { ...fresh(), countsAtStep: { reads: 6, edits: 1, created: 0, commands: 1, tests: 0, calls: 8 } }
  expect(activitySummary(run, fresh())).toBe(
    'desde el inicio: 8 lecturas, 3 ediciones, 1 creados, 3 comandos, 2 pruebas\ndesde el paso actual: 8 lecturas, 3 ediciones, 1 creados, 3 comandos, 2 pruebas',
  )
  expect(activitySummary(run, plan)).toBe(
    'desde el inicio: 8 lecturas, 3 ediciones, 1 creados, 3 comandos, 2 pruebas\ndesde el paso actual: 2 lecturas, 2 ediciones, 1 creados, 2 comandos, 2 pruebas',
  )
  const history = Array.from({ length: 10 }, (_, i) => ({ what: `llamada ${i}`, ms: 2000, ok: i !== 9 }))
  const lines = recentCalls({ history }, 0).split('\n')
  expect(lines).toHaveLength(8)
  expect(lines[0]).toContain('llamada 2')
  expect(lines[7]).toMatch(/✗ llamada 9$/)
})

test('the bar never goes back when the factor changes or a step runs overdue', () => {
  let plan = fresh()
  let last = planBar(plan, 90_000)
  // Step 1 took 4 min instead of 2: the rest is scaled up, the bar holds.
  const next = applyCount(plan, 1, 4 * MIN, 4 * MIN)
  expect(next?.factor).toBe(2)
  expect(planBar(next as PlanState, 4 * MIN)).toBeGreaterThanOrEqual(planBar(plan, 4 * MIN))
  plan = next as PlanState
  last = planBar(plan, 4 * MIN)
  // Overdue: the step is lengthened, the bar holds.
  const overdue = applyOverdue(plan, 8 * MIN, 4 * MIN + 2 * MIN + 30_000)
  expect(overdue).toBeDefined()
  expect(planBar(overdue as PlanState, 6.5 * MIN)).toBeGreaterThanOrEqual(planBar(plan, 6.5 * MIN))
  expect(planBar(plan, 6.5 * MIN)).toBeGreaterThanOrEqual(last)
  // An answer that is not later changes nothing.
  expect(applyOverdue(plan, 1000, 5 * MIN)).toBeUndefined()
})

test('a count that jumps splits the time evenly and the factor stays in 1 to 3 (v3: it never shortens the rest)', () => {
  const plan = fresh()
  // Steps 1-2 (7 min estimated) done in 7 min at once: 3.5 min each, factor 1.
  const jump = applyCount(plan, 2, 7 * MIN, 0)
  expect(jump?.steps.map(step => step.realMs)).toEqual([3.5 * MIN, 3.5 * MIN, undefined, undefined])
  expect(jump?.factor).toBe(1)
  expect(applyCount(plan, 2, 60 * MIN, 0)?.factor).toBe(3)
  // v2 floored at 0.5; a fast step now leaves the rest as planned.
  expect(applyCount(plan, 1, 10_000, 0)?.factor).toBe(1)
  expect(restMs(applyCount(plan, 1, 10_000, 0) as PlanState)).toBe(plan.steps.slice(2).reduce((sum, step) => sum + step.estMs, 0))
  // The count only grows.
  expect(applyCount(jump as PlanState, 2, 8 * MIN, 0)).toBeUndefined()
  expect(applyCount(jump as PlanState, 1, 8 * MIN, 0)).toBeUndefined()
})

test('done may reach y/y while running: "finalizando", never 0 min, bar under 100%, no more checks', () => {
  const plan = applyCount(fresh(), 9, 8 * MIN, 0) as PlanState
  expect(plan.done).toBe(4)
  const view = planView({ plan, startedAt: 0 }, 9 * MIN)
  expect(view).toMatchObject({ isWrappingUp: true, leftMs: 0 })
  expect(view?.percent).toBe(99)
  expect(nextPlanCheck(plan, 60 * MIN, 60 * MIN)).toBeUndefined()
})

test('v2 schedule (removed with the wiring): checks come at 50%, 80% and 95% of the step, 1 min apart, and at most 5 min apart', () => {
  // A 10 min first step: 50% is 5 min, 80% 8 min, 95% 9.5 min.
  const plan = { ...fresh(), stepEndAt: 10 * MIN, stepEstMs: 10 * MIN }
  expect(nextProgressCheck(plan, 4 * MIN, 4 * MIN)).toBeUndefined()
  expect(nextProgressCheck(plan, 5 * MIN, 5 * MIN)).toEqual({ kind: 'progress', fired: 1 })
  expect(nextProgressCheck({ ...plan, fired: 1, askedAt: 5 * MIN, countAt: 5 * MIN }, 7.9 * MIN, 7.9 * MIN)).toBeUndefined()
  expect(nextProgressCheck({ ...plan, fired: 1, askedAt: 5 * MIN, countAt: 5 * MIN }, 8 * MIN, 8 * MIN)).toEqual({ kind: 'progress', fired: 2 })
  expect(nextProgressCheck({ ...plan, fired: 2, askedAt: 8 * MIN, countAt: 8 * MIN }, 9.4 * MIN, 9.4 * MIN)).toBeUndefined()
  expect(nextProgressCheck({ ...plan, fired: 2, askedAt: 8 * MIN, countAt: 8 * MIN }, 9.5 * MIN, 9.5 * MIN)).toEqual({ kind: 'progress', fired: 3 })
  // Two fractions reached at once (a long gap) count as the later one.
  expect(nextProgressCheck({ ...plan, askedAt: 0, countAt: 0 }, 9.6 * MIN, 9.6 * MIN)).toEqual({ kind: 'progress', fired: 3 })
  // Never closer than 1 min to the last check.
  expect(nextProgressCheck({ ...plan, fired: 2, askedAt: 9.2 * MIN, countAt: 9.2 * MIN }, 9.6 * MIN, 9.6 * MIN)).toBeUndefined()
  // Overdue: estimate + 15 s.
  expect(nextProgressCheck({ ...plan, fired: 3, askedAt: 0, countAt: 10 * MIN }, 10 * MIN + 14_000, 10 * MIN + 14_000)).toBeUndefined()
  expect(nextProgressCheck({ ...plan, fired: 3, askedAt: 0, countAt: 10 * MIN }, 10 * MIN + 15_000, 10 * MIN + 15_000)).toEqual({ kind: 'overdue', fired: 3 })
  // A long step with every check done still gets one every 5 min.
  const long = { ...plan, stepEndAt: 90 * MIN, stepEstMs: 90 * MIN, fired: 3, countAt: 0, askedAt: 0 }
  expect(nextProgressCheck(long, 4 * MIN, 4 * MIN)).toBeUndefined()
  expect(nextProgressCheck(long, 5 * MIN, 5 * MIN)).toEqual({ kind: 'progress', fired: 3 })
})

test('a plan only switches on from the first answer and when it is longer than the threshold', () => {
  expect(shouldPlan(1, PLAN_MIN_MS + 1)).toBe(true)
  expect(shouldPlan(1, PLAN_MIN_MS)).toBe(false)
  expect(shouldPlan(2, 20 * MIN)).toBe(false)
  expect(shouldPlan(undefined, 20 * MIN)).toBe(false)
})

test('PLAN_ENABLED false leaves today\'s behaviour: no plan view, no plan switch, the plain percent', () => {
  expect(PLAN_ENABLED).toBe(true)
  const run = { plan: fresh(), startedAt: 0, etaMs: 10 * MIN }
  expect(planView(run, 3 * MIN, false)).toBeUndefined()
  expect(shouldPlan(1, 20 * MIN, false)).toBe(false)
  expect(planView(run, 3 * MIN)).toBeDefined()
  // With the plan on, estimateOf reads the plan's bar.
  expect(estimateOf(run, 3 * MIN)).toBe(planView(run, 3 * MIN)?.percent)
})

// --- v3 pure logic: Haiku judges "done?", code owns the time. ---

const CRIT = '1. Leer el código — 2 min — listo cuando: se leyeron los archivos\n2. Escribir el cambio — 5 min — listo cuando: se editó el módulo\n3. Probarlo — 2 min — listo cuando: las pruebas pasaron\n4. Documentar — 1 min'
const critPlan = (): PlanState => newPlan(parsePlan(CRIT) ?? [], 10 * MIN, 0, 0)

test('parsePlan and parseReplan read an optional "listo cuando" criterion, cut at 100 characters', () => {
  const steps = parsePlan(CRIT)
  expect(steps?.map(step => step.criterion)).toEqual(['se leyeron los archivos', 'se editó el módulo', 'las pruebas pasaron', undefined])
  expect(steps?.map(step => step.minutes)).toEqual([2, 5, 2, 1])
  // Without criteria the format of v2 still reads.
  expect(parsePlan(GOOD)?.every(step => step.criterion === undefined)).toBe(true)
  const long = parsePlan(`1. A — 1 min — listo cuando: ${'x'.repeat(150)}\n2. B — 1 min\n3. C — 1 min`)
  expect(long?.[0]?.criterion).toHaveLength(100)
  expect(parsePlan('1. A — 1 min — listo cuando:\n2. B — 1 min\n3. C — 1 min')).toBeUndefined()
  expect(parseReplan('3. Probar — 4 min — listo cuando: pasaron las pruebas\n4. Informar — 1 min', 3, 6)).toEqual([
    { title: 'Probar', minutes: 4, criterion: 'pasaron las pruebas' },
    { title: 'Informar', minutes: 1 },
  ])
  expect(parseReplan('ninguno', 3, 6)).toEqual([])
  // The criterion reaches the plan's steps.
  expect(critPlan().steps.map(step => step.criterion)).toEqual(['se leyeron los archivos', 'se editó el módulo', 'las pruebas pasaron', undefined])
})

test('parseVerdict reads evidencia and terminado by key over the first 4 lines, in any order, bold ignored', () => {
  expect(parseVerdict('evidencia: ✓ Ejecuta las pruebas\nterminado: sí')).toEqual({ done: true, evidence: '✓ Ejecuta las pruebas' })
  expect(parseVerdict('**evidencia:** Edita a.ts\n**terminado:** Sí')).toEqual({ done: true, evidence: 'Edita a.ts' })
  expect(parseVerdict('terminado: no\nevidencia: ninguna')).toEqual({ done: false, evidence: 'ninguna' })
  expect(parseVerdict('Terminado: SI.')).toEqual({ done: true })
  expect(parseVerdict('terminado: yes')).toEqual({ done: true })
  expect(parseVerdict('evidencia: algo')).toEqual({ evidence: 'algo' })
  // Garbage, an unreadable verdict, or a verdict after the fourth line give no verdict.
  expect(parseVerdict('creo que ya terminó')).toEqual({})
  expect(parseVerdict('terminado: quizá')).toEqual({})
  expect(parseVerdict('a\nb\nc\nd\nterminado: sí')).toEqual({})
  expect(parseVerdict('')).toEqual({})
})

test('isGrounded: evidence needs a word shared with the calls; ninguna or empty never is (M3)', () => {
  const calls = '- 2s ✓ Ejecuta las pruebas del parser\n- 1s ✓ Edita parser.ts'
  expect(isGrounded('✓ Ejecuta las pruebas del parser', calls)).toBe(true)
  expect(isGrounded('Edita parser.ts', calls)).toBe(true)
  expect(isGrounded('ninguna', calls)).toBe(false)
  expect(isGrounded('Ninguna.', calls)).toBe(false)
  expect(isGrounded('', calls)).toBe(false)
  expect(isGrounded(undefined, calls)).toBe(false)
  // The agent's announced plan shares no word with the calls.
  expect(isGrounded('leeré, implementaré y probaré todo', calls)).toBe(false)
})

test('nextPlanCheck: overdue backoff 30/60/120/240 s, event needs a hint and 60 s, ceiling at 5 min, none when all done', () => {
  const plan = { ...fresh(), stepEndAt: 2 * MIN, askedAt: 0 }
  // Not overdue yet, no hint, under the ceiling.
  expect(nextPlanCheck(plan, MIN, MIN)).toBeUndefined()
  expect(nextPlanCheck(plan, 2 * MIN + 14_000, 2 * MIN + 14_000)).toBeUndefined()
  expect(nextPlanCheck(plan, 2 * MIN + 15_000, 2 * MIN + 15_000)).toEqual({ kind: 'overdue' })
  // The gap follows the overdue checks so far: 30 s, 60 s, 120 s, 240 s, then 240 s.
  expect([0, 1, 2, 3, 4, 9].map(overdueGapMs)).toEqual([30_000, 60_000, 120_000, 240_000, 240_000, 240_000])
  const late = 10 * MIN
  for (const [checks, gap] of [[0, 30_000], [1, 60_000], [2, 120_000], [3, 240_000], [6, 240_000]] as const) {
    const asked = { ...plan, overdueChecks: checks, askedAt: late }
    expect(nextPlanCheck({ ...asked, hintAt: undefined }, late + gap - 1000, late + gap - 1000)).toBeUndefined()
    expect(nextPlanCheck(asked, late + gap, late + gap)).toEqual({ kind: 'overdue' })
  }
  // Event: a hint after the last check, and at least 1 min after it.
  const open = { ...plan, stepEndAt: 30 * MIN, askedAt: 0 }
  expect(nextPlanCheck({ ...open, hintAt: 10_000 }, 59_000, 59_000)).toBeUndefined()
  expect(nextPlanCheck({ ...open, hintAt: 10_000 }, MIN, MIN)).toEqual({ kind: 'event' })
  // A hint older than the last check does not count.
  expect(nextPlanCheck({ ...open, askedAt: 20_000, hintAt: 10_000 }, 2 * MIN, 2 * MIN)).toBeUndefined()
  // Ceiling: 5 min without a check.
  expect(nextPlanCheck(open, 4.9 * MIN, 4.9 * MIN)).toBeUndefined()
  expect(nextPlanCheck(open, 5 * MIN, 5 * MIN)).toEqual({ kind: 'ceiling' })
  // Every step done: nothing, whatever the clock says.
  const finished = applyCount(fresh(), 4, 8 * MIN, 8 * MIN) as PlanState
  expect(nextPlanCheck({ ...finished, hintAt: 9 * MIN }, 60 * MIN, 60 * MIN)).toBeUndefined()
})

test('growOverdue: the end moves to max(1 min, half the time in the step) from now, the percent never drops, the counter grows', () => {
  const plan = fresh()
  // 2 min step overdue at 2:15: half the 135 s in the step is 67.5 s, over the 1 min floor.
  const first = growOverdue(plan, 2 * MIN + 15_000)
  expect(first.stepEndAt).toBe(2 * MIN + 15_000 + 67_500)
  expect(first.overdueChecks).toBe(1)
  expect(first.stepEstMs).toBe(first.stepEndAt - first.stepAt)
  // Short time in the step: the 1 min floor.
  expect(growOverdue({ ...plan, stepEndAt: 20_000 }, 40_000).stepEndAt).toBe(40_000 + MIN)
  // Long time in the step: half of it.
  const long = growOverdue({ ...plan, stepEndAt: 2 * MIN }, 20 * MIN)
  expect(long.stepEndAt).toBe(30 * MIN)
  expect(growOverdue(long, 30 * MIN + 20_000).overdueChecks).toBe(2)
  // The percent holds across every growth.
  let grown = plan
  let last = planBar(plan, 0)
  for (let elapsed = 2 * MIN + 15_000; elapsed < 40 * MIN; elapsed += 3 * MIN) {
    grown = growOverdue(grown, elapsed)
    expect(planBar(grown, elapsed)).toBeGreaterThanOrEqual(last)
    last = planBar(grown, elapsed)
    // The time left is never the "~1 min" floor of a stalled step once the step has run long.
    if (elapsed > 10 * MIN) {
      expect(planLeftMs(grown, elapsed)).toBeGreaterThan(MIN)
    }
  }
})

test('applyDone advances exactly one step, only with new calls (G1), hints the next check, resets the overdue counter', () => {
  const plan = { ...fresh(), overdueChecks: 3 }
  expect(applyDone(plan, 3 * MIN, 3 * MIN, false)).toBeUndefined()
  const next = applyDone(plan, 3 * MIN, 3 * MIN, true)
  expect(next?.done).toBe(1)
  expect(next?.overdueChecks).toBe(0)
  expect(next?.hintAt).toBe(3 * MIN)
  expect(next?.advancedAt).toBe(3 * MIN)
  expect(next?.steps[0]?.realMs).toBe(3 * MIN)
  expect(next?.stepAt).toBe(3 * MIN)
  // One verdict, one step: the next verdict advances once more.
  expect(applyDone(next as PlanState, 4 * MIN, 4 * MIN, true)?.done).toBe(2)
  // The hint set after an advance makes the next check due once the 1 min gap passes (catch-up of a fast step).
  const hinted = { ...(next as PlanState), askedAt: 3 * MIN - 1000 }
  expect(nextPlanCheck({ ...hinted, stepEndAt: 30 * MIN }, 3 * MIN + 58_000, 3 * MIN + 58_000)).toBeUndefined()
  expect(nextPlanCheck({ ...hinted, stepEndAt: 30 * MIN }, 3 * MIN + 59_000, 3 * MIN + 59_000)).toEqual({ kind: 'event' })
  // Nothing past the last step.
  expect(applyDone(applyCount(fresh(), 4, 8 * MIN, 8 * MIN) as PlanState, 9 * MIN, 9 * MIN, true)).toBeUndefined()
  // Percent never goes back.
  expect(planBar(next as PlanState, 3 * MIN)).toBeGreaterThanOrEqual(planBar(plan, 3 * MIN))
})

test('a step finished in half its estimate leaves the rest as planned (factor 1), a slow one lengthens it', () => {
  const plan = fresh()
  const fast = applyDone(plan, MIN, MIN, true) as PlanState
  expect(fast.factor).toBe(1)
  expect(restMs(fast)).toBe(restMs(plan) - plan.steps[1]!.estMs)
  const slow = applyDone(plan, 4 * MIN, 4 * MIN, true) as PlanState
  expect(slow.factor).toBe(2)
  expect(slow.stepEstMs).toBe(plan.steps[1]!.estMs * 2)
})

test('stepTimes lists finished steps with real ms, the current one up to the end, and leaves unstarted ones out', () => {
  const plan = applyDone(fresh(), 3 * MIN, 3 * MIN, true) as PlanState
  expect(stepTimes(plan, 9 * MIN)).toEqual([
    { title: 'Leer el código', estMs: 2 * MIN, ms: 3 * MIN },
    { title: 'Escribir el cambio', estMs: 5 * MIN, ms: 6 * MIN },
  ])
  const all = applyCount(fresh(), 4, 8 * MIN, 8 * MIN) as PlanState
  expect(stepTimes(all, 9 * MIN)).toHaveLength(4)
})

test('callPointsAhead matches a later step by its criterion words too', () => {
  const plan = critPlan()
  expect(callPointsAhead(plan, 'Ejecuta las pruebas del parser')).toBe(true)
  expect(callPointsAhead(plan, 'Lee los archivos del módulo')).toBe(false)
})

test('askDone: evidence-first prompt without the previous step or the calendar, said only when given, 120 tokens', async () => {
  let seen: { prompt: string; maxTokens: number; timeoutMs?: number } = { prompt: '', maxTokens: 0 }
  const $ = askerOf(ask => {
    seen = ask as typeof seen
    return 'evidencia: ✓ Read a.md\nterminado: sí'
  })
  const plan = critPlan()
  const out = await askDone($, { mission: 'Migrar', plan, elapsedMs: 3 * MIN, activity: 'A', calls: '- 1s ✓ Read a.md', id: 'a1' })
  expect(out).toEqual({ done: true, evidence: '✓ Read a.md' })
  expect(seen.maxTokens).toBe(120)
  expect(seen.timeoutMs).toBe(15000)
  expect(seen.prompt.startsWith('Un agente de programación')).toBe(true)
  expect(seen.prompt).not.toContain('<paso_anterior>')
  expect(seen.prompt).not.toContain('calendario')
  expect(seen.prompt).not.toMatch(/falta:|paso: N/)
  expect(seen.prompt).not.toContain('<dice_el_agente>\n')
  expect(seen.prompt).toContain('<paso_actual>1. Leer el código · listo cuando: se leyeron los archivos</paso_actual>')
  expect(seen.prompt).toContain('<paso_siguiente>2. Escribir el cambio · listo cuando: se editó el módulo</paso_siguiente>')
  expect(seen.prompt).toContain('terminado: sí</example>')
  expect(seen.prompt).toContain('terminado: no</example>')
  expect(seen.prompt).not.toContain('<pensando>')
  await askDone($, { mission: 'Migrar', plan, elapsedMs: 3 * MIN, activity: 'A', calls: '- B', said: 'Voy a editar', thinking: 'pensando desde hace 20s (sin herramientas)', id: 'a1' })
  expect(seen.prompt).toContain('<dice_el_agente>\nVoy a editar\n</dice_el_agente>')
  expect(seen.prompt).toContain('<pensando>pensando desde hace 20s (sin herramientas)</pensando>')
  // Unreadable and unanswered replies give undefined.
  expect(await askDone(askerOf(() => 'no sé'), { mission: 'M', plan, elapsedMs: 0, activity: 'A', calls: '-', id: 'a1' })).toBeUndefined()
})

test('askPlan asks for criteria a call can show, 400 tokens, and shows the real steps of similar runs', async () => {
  let seen: { prompt: string; maxTokens: number } = { prompt: '', maxTokens: 0 }
  const $ = askerOf(ask => {
    seen = ask
    return CRIT
  })
  const similar = [
    { summary: 'implementer: Migrar servicios', durationMs: 14 * MIN, at: 1, steps: [{ title: 'Leer', estMs: MIN, ms: 2 * MIN }, { title: 'Implementar', estMs: 5 * MIN, ms: 6 * MIN }, { title: 'Probar', estMs: 3 * MIN, ms: 5 * MIN }, { title: 'Informar', estMs: MIN, ms: MIN }] },
    { summary: 'implementer: Otra cosa', durationMs: 5 * MIN, at: 2 },
  ]
  const out = await askPlan($, { text: 'Migrar', totalMs: 12 * MIN, id: 'a1', similar })
  expect(out?.map(step => step.criterion)).toEqual(['se leyeron los archivos', 'se editó el módulo', 'las pruebas pasaron', undefined])
  expect(seen.maxTokens).toBe(400)
  expect(seen.prompt).toContain('listo cuando')
  expect(seen.prompt).toContain('1. implementer: Migrar servicios — 14 min (pasos reales: Leer 2 · Implementar 6 · Probar 5 · Informar 1)')
  expect(seen.prompt).toContain('2. implementer: Otra cosa — 5 min</tareas_parecidas>')
  expect(seen.prompt).toMatch(/<example>[^]*listo cuando[^]*<\/example>/)
})

// --- Integration: a long agent's card says `<step> N% · ~time`. ---

const PANE_PROPS = { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 12 }, view: {} }
const SPAWN = {
  tool_use_id: 'tu1',
  prompt: 'Migrate every service',
  description: 'Migrate services',
  subagentType: 'general-purpose',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'claude-opus-5-5',
  background: true,
  fork: false,
} as const

/** What the mock Haiku answers to a plan check; a test sets it. */
const checkReply = { text: 'paso: 2\nfalta: 3' }

function engine(on: Parameters<Parameters<typeof test>[1]>[1], planReply: string, prompts: string[]) {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    prompts.push(prompt)
    const text = prompt.includes('<duracion_total>') ? planReply : prompt.includes('<tareas_parecidas>') ? 'minutos: 10' : prompt.includes('<pasos>') ? checkReply.text : '?'
    return { value: { isAnswered: true, text, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  return mock.clock(on)
}

test('a long agent card shows the step, the whole-run percent and the time left, and a step check moves it', async ($, on) => {
  const prompts: string[] = []
  const clock = engine(on, GOOD, prompts)
  await $.agent.spawn(SPAWN)
  await new Promise(resolve => setTimeout(resolve, 20))
  await clock.advance(10_000)
  const pane = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  // `<step> N% · ~10 min`: the step title small, cut with … past STEP_TITLE_CHARS, no X/Y count.
  // One Text with nested spans (sibling Texts wrap on vscode): percent and time bold, the step title dim.
  const head = await pane.find({ type: 'Text', text: /^Leer el código \d+% · ~10 min$/ })
  expect(head?.props.bold).toBeUndefined()
  expect(await pane.find({ type: 'Text', text: /^\d\/\d/ })).toBeUndefined()
  expect((await pane.find({ type: 'Text', text: /^\d+% · ~10 min$/ }))?.props.bold).toBe(true)
  expect((await pane.find({ type: 'Text', text: /^Leer el código$/ }))?.props).toMatchObject({ dimColor: true, size: 'footnote' })
  await pane.unmount()
  // Step 1 lasts 2 min: the check at 1 min asks; a call came in, Haiku says step 2: one step done.
  checkReply.text = 'paso: 2\nfalta: 3'
  await $.tool.call(readCall('c1'))
  await settle()
  await clock.advance(60_000)
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(prompts.some(prompt => prompt.includes('<pasos>'))).toBe(true)
  const later = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  expect(await later.find({ type: 'Text', text: /^Escribir el cambio \d+% · / })).toBeDefined()
  expect(await later.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  await later.unmount()
})

test('an invalid plan reply falls back silently to the plain percent', async ($, on) => {
  const clock = engine(on, 'no sé', [])
  await $.agent.spawn(SPAWN)
  await new Promise(resolve => setTimeout(resolve, 20))
  await clock.advance(30_000)
  const pane = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  // The plain card: `≈N%`, and no step title (or plan percent) in front of the datum.
  expect(await pane.find({ type: 'Text', text: /≈\d+%/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /^(?!≈).*\d+% · / })).toBeUndefined()
  expect(await pane.find({ type: 'Text', text: /Leer el código|Escribir el cambio/ })).toBeUndefined()
  await pane.unmount()
})

test('a long step title is cut with … in the header, at 26 characters', () => {
  const plan = newPlan([{ title: 'Leer la conversión v7.4-pre completa con calma', minutes: 4 }, { title: 'Informar', minutes: 1 }, { title: 'Fin', minutes: 1 }], 6 * 60_000, 0, 0)
  const view = planView({ plan, startedAt: 0 }, 60_000, true)
  expect(view?.step).toBe('Leer la conversión v7.4-p…')
  expect(view?.step?.length).toBeLessThanOrEqual(26)
  expect(view).not.toHaveProperty('stepPct')
  expect(view).not.toHaveProperty('count')
})

test('v2 schedule: a call that reads like a later step hints a count check; the 5 min ceiling still asks without hints', () => {
  const plan = newPlan([{ title: 'Leer el esquema actual', minutes: 30 }, { title: 'Escribir los scripts de migración', minutes: 10 }, { title: 'Informar', minutes: 2 }], 42 * 60_000, 0, 0)
  expect(callPointsAhead(plan, 'Escribe el script de migración de usuarios')).toBe(true)
  expect(callPointsAhead(plan, 'Lee el esquema actual de la tabla')).toBe(false)
  expect(callPointsAhead(plan, 'Run sed -n 1,6p samples.txt')).toBe(false)
  // 2 min into a 30 min step: no check yet; a hint after the last ask makes one.
  expect(nextProgressCheck(plan, 2 * 60_000, 2 * 60_000)).toBeUndefined()
  expect(nextProgressCheck({ ...plan, hintAt: 2 * 60_000 }, 2 * 60_000, 2 * 60_000)).toMatchObject({ kind: 'progress' })
  // No hint: 5 min without a count asks anyway (was 20).
  expect(nextProgressCheck(plan, 5 * 60_000, 5 * 60_000)).toMatchObject({ kind: 'progress' })
})

// --- Call hints: word matching only ever runs on Spanish natural text. ---

// A 42 min plan whose first step is 30 min long: only a hint can make a count check in the first minutes.
const LONG = '1. Leer el esquema actual — 30 min\n2. Escribir los scripts de migración — 10 min\n3. Informar — 2 min'
const settle = () => new Promise(resolve => setTimeout(resolve, 20))

/** A planned run whose Haiku answers command prompts with `phrases` in turn ('' = unanswered); `prompts` collects every prompt. */
function plannedEngine(on: Parameters<Parameters<typeof test>[1]>[1], phrases: string[], prompts: string[]) {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    prompts.push(prompt)
    const usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
    if (/<comando>/.test(prompt)) {
      const text = phrases.shift() ?? ''
      return { value: { isAnswered: text !== '', text, usage } }
    }
    const text = prompt.includes('<duracion_total>') ? LONG : prompt.includes('<tareas_parecidas>') ? 'minutos: 42' : prompt.includes('<pasos>') ? checkReply.text : '?'
    return { value: { isAnswered: true, text, usage } }
  })
  return mock.clock(on)
}

const bash = (command: string, id: string) => ({ tool: 'Bash', command, agentId: 'a1', tool_use_id: id }) as never
const commandsOf = (prompts: string[]) => prompts.filter(prompt => prompt.includes('<comando>'))
const countChecks = (prompts: string[]) => prompts.filter(prompt => prompt.includes('<pasos>')).length

async function start($: Parameters<Parameters<typeof test>[1]>[0], clock: { advance(ms: number): Promise<void> }) {
  await $.agent.spawn(SPAWN)
  await settle()
  await clock.advance(10_000)
  await settle()
}

test('a failed translation is retried once ~5 s later and its phrase then hints by words', async ($, on) => {
  const prompts: string[] = []
  const clock = plannedEngine(on, ['', 'Escribe los scripts de migración'], prompts)
  await start($, clock)
  await $.tool.call(bash('cargo run --bin retry-me', 'r1'))
  await settle()
  expect(commandsOf(prompts)).toHaveLength(1)
  await clock.advance(5000)
  await settle()
  expect(commandsOf(prompts)).toHaveLength(2)
  await clock.advance(61_000)
  await settle()
  expect(countChecks(prompts)).toBeGreaterThan(0)
  expect((await $.command.run({ command: 'agents-debug' } as never)).text).toMatch(/translations: ok=[1-9]\d* retried=[1-9]\d* failed=\d+ cached=\d+/)
})

test('two failed tries hint the plan directly; a cached command asks Haiku no second time', async ($, on) => {
  const prompts: string[] = []
  const clock = plannedEngine(on, ['', '', 'Lee el esquema actual'], prompts)
  await start($, clock)
  await $.tool.call(bash('cargo run --bin fail-me', 'f1'))
  await settle()
  await clock.advance(5000)
  await settle()
  expect(commandsOf(prompts)).toHaveLength(2)
  await clock.advance(61_000)
  await settle()
  expect(countChecks(prompts)).toBeGreaterThan(0)
  await $.tool.call(bash('cargo run --bin cache-me', 'c1'))
  await settle()
  expect(commandsOf(prompts)).toHaveLength(3)
  await $.tool.call(bash('cargo run --bin cache-me', 'c2'))
  await settle()
  expect(commandsOf(prompts)).toHaveLength(3)
  expect((await $.command.run({ command: 'agents-debug' } as never)).text).toMatch(/failed=[1-9]\d* cached=[1-9]/)
})

test('a Read call and a raw Bash label never hint a count check', async ($, on) => {
  const prompts: string[] = []
  // The raw command and file name share words with step 2, but only a translation may be matched; this one matches step 1.
  const clock = plannedEngine(on, ['Lee el esquema actual'], prompts)
  await start($, clock)
  await $.tool.call({ tool: 'Read', file_path: 'Escribir_los_scripts_de_migración.md', agentId: 'a1', tool_use_id: 'x1' } as never)
  await settle()
  await $.tool.call(bash('echo Escribir los scripts de migración', 'x2'))
  await settle()
  expect(commandsOf(prompts)).toHaveLength(1)
  // A call every 5 s for over a minute: never thinking, so nothing hints either.
  for (let i = 0; i < 13; i += 1) {
    await clock.advance(5000)
    await $.tool.call({ tool: 'Read', file_path: `otra${i}.md`, agentId: 'a1', tool_use_id: `y${i}` } as never)
    await settle()
  }
  expect(countChecks(prompts)).toBe(0)
})

test('a phrase reply cut by maxTokens still gives its first line when that line ended', () => {
  // A cut is the reply reaching its real cap: maxTokens plus the 2048 thinking tokens the host adds for thinking models.
  const cut = { output_tokens: 80 + 2048 }
  expect(phraseOf({ isAnswered: true, text: 'Ejecuta un script de Python que mide memoria\nEl script importa tracemalloc y…', usage: cut })).toBe('Ejecuta un script de Python que mide memoria')
  expect(phraseOf({ isAnswered: true, text: 'Ejecuta un script de Python que mide la memoria de cada conv', usage: cut })).toBe('')
  expect(phraseOf({ isAnswered: false, text: 'x\ny', usage: cut })).toBe('')
  // Without thinking, a text that itself used the 80 tokens (about 3 chars each) is cut too.
  expect(phraseOf({ isAnswered: true, text: `Reescribe ${'el módulo de pruebas '.repeat(13)}y`, usage: { output_tokens: 80 } })).toBe('')
})

test('a one-line phrase is kept when output_tokens counts the thinking (2026-11-06: 14 of 22 translations lost)', () => {
  // The host keeps thinking on for current Haiku and output_tokens includes it: 412 tokens used, a whole 8-word answer.
  const thought = { output_tokens: 412 }
  expect(phraseOf({ isAnswered: true, text: 'Reescribe browser_focus_mode.js para comprobar el segmento activo', usage: thought })).toBe('Reescribe browser_focus_mode.js para comprobar el segmento activo')
  expect(phraseOf({ isAnswered: true, text: 'Prueba el contraste del modo foco', usage: { output_tokens: 80 } })).toBe('Prueba el contraste del modo foco')
})

test('a heredoc script hints the plan with the untagged phrase', async ($, on) => {
  const prompts: string[] = []
  const clock = plannedEngine(on, ['Escribe los scripts de migración'], prompts)
  await start($, clock)
  await $.tool.call(bash("python3 - <<'E'\nprint(1)\nE", 'h1'))
  await settle()
  expect(commandsOf(prompts)).toHaveLength(1)
  await clock.advance(61_000)
  await settle()
  expect(countChecks(prompts)).toBeGreaterThan(0)
})

test('scriptOf tells inline bodies, script files and plain commands apart', () => {
  expect(scriptOf("python3 - <<'E'\nx\nE")).toEqual({ inline: true })
  expect(scriptOf('cd a && node -e "1"')).toEqual({ inline: true })
  expect(scriptOf('python3 fix.py args')).toEqual({ file: 'fix.py' })
  expect(scriptOf('bash scripts/run.sh')).toEqual({ file: 'run.sh' })
  expect(scriptOf('cargo test')).toBeUndefined()
})

test('a plan card never says "más de lo previsto", even past the run estimate', async ($, on) => {
  const clock = engine(on, GOOD, [])
  await $.agent.spawn(SPAWN)
  await new Promise(resolve => setTimeout(resolve, 20))
  // The 10 min plan is long overdue.
  await clock.advance(15 * MIN)
  await new Promise(resolve => setTimeout(resolve, 20))
  const pane = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  expect(await pane.find({ type: 'Text', text: /\d+% · (~\d+ min|finalizando)$/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /más de lo previsto/ })).toBeUndefined()
  await pane.unmount()
})

const readCall = (id: string) => ({ tool: 'Read', file_path: `/tmp/${id}.md`, agentId: 'a1', tool_use_id: id }) as never
const paneOf = ($: Parameters<Parameters<typeof test>[1]>[0]) =>
  $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)

test('thinking: the card says pensando… after 10 s with no call, a new call replaces it, no calls yet shows none', async ($, on) => {
  const clock = plannedEngine(on, [], [])
  await start($, clock)
  // Never made a call: the usual detail, however long it waits.
  await clock.advance(30_000)
  const idle = await paneOf($)
  expect(await idle.find({ type: 'Text', text: /pensando/ })).toBeUndefined()
  await idle.unmount()
  await $.tool.call(readCall('t1'))
  await settle()
  await clock.advance(9000)
  const soon = await paneOf($)
  expect(await soon.find({ type: 'Text', text: /pensando/ })).toBeUndefined()
  await soon.unmount()
  await clock.advance(3000)
  await settle()
  const thinking = await paneOf($)
  expect((await thinking.find({ type: 'Text', text: /pensando/ }))?.text).toMatch(/^ *◐ pensando… 1\ds$/)
  await thinking.unmount()
  await $.tool.call(readCall('t2'))
  await settle()
  const after = await paneOf($)
  expect(await after.find({ type: 'Text', text: /pensando/ })).toBeUndefined()
  await after.unmount()
})

test('thinking: a planned run hints one count check per thinking episode and tells Haiku it is thinking', async ($, on) => {
  const prompts: string[] = []
  const clock = plannedEngine(on, [], prompts)
  await start($, clock)
  await $.tool.call(readCall('t1'))
  await settle()
  // Past 10 s of thinking the tick hints; the 1 min gap since the plan's start already passed.
  await clock.advance(61_000)
  await settle()
  expect(countChecks(prompts)).toBe(1)
  expect(prompts.filter(prompt => prompt.includes('<pasos>')).pop()).toMatch(/<pensando>pensando desde hace \d+s \(sin herramientas\)<\/pensando>/)
  // Same episode: no second check 1 min later, a new episode (a call, then thinking) asks again.
  await clock.advance(61_000)
  await settle()
  expect(countChecks(prompts)).toBe(1)
  await $.tool.call(readCall('t2'))
  await settle()
  await clock.advance(61_000)
  await settle()
  expect(countChecks(prompts)).toBe(2)
})

// --- Replays (diagnosis 2026-11-02): a 5-step plan of 120/15/10/5/5 min, a call every 20 s with a thinking gap each. ---

const FIVE = '1. Leer el código — 120 min\n2. Escribir el cambio — 15 min\n3. Probar — 10 min\n4. Corregir — 5 min\n5. Informar — 5 min'

/** A 5-step run whose Haiku answers plan checks with `answer(prompt)`; `prompts` collects the check prompts. */
function replayEngine(on: Parameters<Parameters<typeof test>[1]>[1], answer: (prompt: string) => string, prompts: string[]) {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    const usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
    if (prompt.includes('<paso_anterior>')) {
      prompts.push(prompt)
    }
    const text = prompt.includes('<duracion_total>')
      ? FIVE
      : prompt.includes('<tareas_parecidas>')
        ? 'minutos: 155'
        : prompt.includes('<paso_anterior>')
          ? answer(prompt)
          : '?'
    return { value: { isAnswered: true, text, usage } }
  })
  return mock.clock(on)
}

const FIVE_TITLES = ['Leer el código', 'Escribir el cambio', 'Probar', 'Corregir', 'Informar']

/** Steps done as the card shows them: the index of the shown step title (5 when every step is done), or undefined. */
async function shownCount($: Parameters<Parameters<typeof test>[1]>[0]): Promise<number | undefined> {
  const pane = await paneOf($)
  const head = await pane.find({ type: 'Text', text: new RegExp(`^(${FIVE_TITLES.join('|')}) \\d+% · `) })
  const wrapping = await pane.find({ type: 'Text', text: /^\d+% · finalizando$/ })
  await pane.unmount()
  if (wrapping !== undefined) {
    return FIVE_TITLES.length
  }
  const index = FIVE_TITLES.findIndex(title => (head?.text ?? '').startsWith(`${title} `))
  return index < 0 ? undefined : index
}

test('replay: a truthful Haiku follows the work to step 3 of 5 or later, one step per check', async ($, on) => {
  const prompts: string[] = []
  let calls = 0
  // The agent changes phase every 10 calls (~3 min): a truthful reader says so.
  const clock = replayEngine(on, () => `paso: ${Math.min(5, 1 + Math.floor(calls / 10))}\nfalta: 3`, prompts)
  await start($, clock)
  for (let i = 0; i < 48; i += 1) {
    calls += 1
    await $.tool.call(readCall(`r${i}`))
    await settle()
    await clock.advance(20_000)
    await settle()
  }
  expect(prompts.length).toBeGreaterThan(3)
  const count = (await shownCount($)) ?? 0
  expect(count).toBeGreaterThanOrEqual(3)
  expect(count).toBeLessThanOrEqual(prompts.length)
})

test('replay: frozen activity (no new calls, clock +10 min) never moves the step, whatever Haiku says', async ($, on) => {
  const prompts: string[] = []
  const clock = replayEngine(on, () => 'paso: 5\nfalta: 1', prompts)
  await start($, clock)
  for (let i = 0; i < 6; i += 1) {
    await clock.advance(MIN + 5000)
    await settle()
  }
  expect(prompts.length).toBeGreaterThan(0)
  expect(await shownCount($)).toBe(0)
  // One call arrives: the next check takes Haiku's step (jumps are accepted), then it freezes again.
  await $.tool.call(readCall('f1'))
  await settle()
  await clock.advance(MIN + 5000)
  await settle()
  expect(await shownCount($)).toBe(4)
  for (let i = 0; i < 6; i += 1) {
    await clock.advance(MIN + 5000)
    await settle()
  }
  expect(await shownCount($)).toBe(4)
})

const USAGE = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
/** A bare engine whose only call is `model.complete`, answered by `reply`. */
const askerOf = (reply: (ask: { prompt: string; maxTokens: number }) => string) =>
  ({ model: { complete: async (ask: { prompt: string; maxTokens: number }) => ({ isAnswered: true, text: reply(ask), usage: USAGE }) } }) as never

test('the calendar prior is labelled reference: 2/23 and 22/23 give the same step when Haiku echoes the previous one', async () => {
  const prompts: string[] = []
  const $ = askerOf(ask => {
    prompts.push(ask.prompt)
    return `paso: ${/<paso_anterior>(\d+)<\/paso_anterior>/.exec(ask.prompt)?.[1] ?? '1'}\nfalta: 4`
  })
  const plan = newPlan(parsePlan(GOOD) ?? [], 23 * MIN, 0, 0)
  const ask = (elapsedMs: number) => askStepCheck($, { mission: 'Migrar', plan, elapsedMs, activity: 'desde el inicio: 1 lecturas, 0 ediciones, 0 creados, 0 comandos, 0 pruebas', calls: '- 1s ✓ Read a.md', id: 'a1' })
  const early = await ask(2 * MIN)
  const late = await ask(22 * MIN)
  expect(early).toEqual(late)
  expect(prompts[0]).toContain('van 2 min de 23 min (solo referencia, no es una prueba)')
  expect(prompts[1]).toContain('van 22 min de 23 min (solo referencia, no es una prueba)')
  expect(prompts[0]).toContain('<paso_anterior>1</paso_anterior>')
  // Same evidence, same answer: the applied step does not depend on the calendar.
  expect(applyStep(plan, early?.step ?? 0, 2 * MIN, 0, true)).toEqual(applyStep(plan, late?.step ?? 0, 2 * MIN, 0, true))
})

test('the check prompt carries the plan with real and current minutes, the thinking state and a 40 token limit', async () => {
  let seen: { prompt: string; maxTokens: number } = { prompt: '', maxTokens: 0 }
  const $ = askerOf(ask => {
    seen = ask
    return 'paso: 2\nfalta: 3'
  })
  const done = applyCount(fresh(), 1, 3 * MIN, 3 * MIN) as PlanState
  const out = await askStepCheck($, { mission: 'Migrar', plan: done, elapsedMs: 5 * MIN, activity: 'A', calls: '- B', thinking: 'pensando desde hace 20s (sin herramientas)', id: 'a1' })
  expect(out).toEqual({ step: 2, leftMin: 3 })
  expect(seen.maxTokens).toBe(40)
  expect(seen.prompt).toMatch(/1\. Leer el código · previsto 2 min · real 3 min\n2\. Escribir el cambio · previsto \S+ min · en curso 2 min\n3\. Probarlo · previsto/)
  expect(seen.prompt).toContain('<paso_anterior>2</paso_anterior>')
  expect(seen.prompt).toContain('<pensando>pensando desde hace 20s (sin herramientas)</pensando>')
  const quiet = await askStepCheck($, { mission: 'Migrar', plan: done, elapsedMs: 5 * MIN, activity: 'A', calls: '- B', id: 'a1' })
  expect(quiet).toBeDefined()
  expect(seen.prompt).not.toContain('<pensando>')
})

test('parseReplan reads the steps after the current one, ninguno, and a list restarted at 1', () => {
  expect(parseReplan('3. Probar — 4 min\n4. Informar — 1 min', 3, 6)).toEqual([
    { title: 'Probar', minutes: 4 },
    { title: 'Informar', minutes: 1 },
  ])
  expect(parseReplan('ninguno', 3, 6)).toEqual([])
  expect(parseReplan('**Ninguno.**', 3, 6)).toEqual([])
  expect(parseReplan(' **Ninguno** \n', 3, 6)).toEqual([])
  // Numbering that is neither `from` nor 1, a gap, too many lines, ninguno with lines, prose.
  expect(parseReplan('3. Probar — 4 min\n4. Informar — 1 min', 2, 6)).toBeUndefined()
  expect(parseReplan('3. Probar — 4 min\n5. Informar — 1 min', 3, 6)).toBeUndefined()
  expect(parseReplan('3. A — 1 min\n4. B — 1 min\n5. C — 1 min', 3, 2)).toBeUndefined()
  expect(parseReplan('ninguno\n3. X — 1 min', 3, 6)).toBeUndefined()
  expect(parseReplan('Quedan estos:\n3. X — 1 min', 3, 6)).toBeUndefined()
  expect(parseReplan('', 3, 6)).toBeUndefined()
  // A6: Haiku numbers from 1.
  expect(parseReplan('1. A — 2 min\n2. B — 1 min', 3, 6)).toHaveLength(2)
  expect(parseReplan('1. A — 2 min\n3. B — 1 min', 3, 6)).toBeUndefined()
})

test('applyReplan keeps done and current steps and preserves the old pending sum: the split changes, the total does not', () => {
  const plan = applyCount(fresh(), 1, 3 * MIN, 3 * MIN) as PlanState
  const oldSum = plan.steps.slice(2).reduce((sum, step) => sum + step.estMs, 0)
  const out = applyReplan(plan, [{ title: 'Probar', minutes: 3, criterion: 'las pruebas pasaron' }, { title: 'Informar', minutes: 1 }], 3 * MIN)
  expect(out.steps.slice(0, 2)).toEqual(plan.steps.slice(0, 2))
  expect(out.steps.map(step => step.title)).toEqual(['Leer el código', 'Escribir el cambio', 'Probar', 'Informar'])
  // The criterion is kept, `fixed` is gone, and 3:1 of the old 3 min sum.
  expect(out.steps[2]).toEqual({ title: 'Probar', estMs: 0.75 * oldSum, criterion: 'las pruebas pasaron' })
  expect(out.steps.map(step => step.fixed)).toEqual([undefined, undefined, undefined, undefined])
  expect(out.steps.slice(2).reduce((sum, step) => sum + step.estMs, 0)).toBe(oldSum)
  // The factor still applies once to what remains.
  expect(restMs(out)).toBe(restMs(plan))
})

test('applyReplan: the percent never goes down, a long or short reply cannot move the total, [] and a last current step return the same object', () => {
  const plan = applyCount(fresh(), 1, 2 * MIN, 2 * MIN) as PlanState
  const before = planBar(plan, 4 * MIN)
  for (const minutes of [0.1, 100]) {
    const out = applyReplan(plan, [{ title: 'Probar', minutes }], 4 * MIN)
    expect(restMs(out)).toBe(restMs(plan))
    expect(planBar(out, 4 * MIN)).toBeGreaterThanOrEqual(before)
  }
  const longer = applyReplan(plan, [{ title: 'Probar', minutes: 9 }, { title: 'Informar', minutes: 3 }], 4 * MIN)
  expect(planBar(longer, 4 * MIN)).toBeGreaterThanOrEqual(before)
  // ninguno keeps the plan; with the last step current there is nothing to rewrite.
  expect(applyReplan(plan, [], 4 * MIN)).toBe(plan)
  const final = applyCount(fresh(), 3, 6 * MIN, 6 * MIN) as PlanState
  expect(applyReplan(final, [{ title: 'Extra', minutes: 30 }], 6 * MIN)).toBe(final)
  // The total never passes 8 steps.
  const many = Array.from({ length: 12 }, (_, i) => ({ title: `P${i}`, minutes: 1 }))
  expect(applyReplan(plan, many, 4 * MIN).steps).toHaveLength(8)
})

test('shouldReplan: only after an advance and only when a step follows the new current one', () => {
  const plan = fresh()
  expect(shouldReplan(plan, true)).toBe(true)
  expect(shouldReplan(plan, false)).toBe(false)
  expect(shouldReplan(applyCount(plan, 2, 5 * MIN, 0) as PlanState, true)).toBe(true)
  // Current step is the last one (done + 1 === length): nothing follows.
  expect(shouldReplan(applyCount(plan, 3, 6 * MIN, 0) as PlanState, true)).toBe(false)
  expect(shouldReplan(applyCount(plan, 4, 8 * MIN, 0) as PlanState, true)).toBe(false)
})

test('askReplan sends the history, the steps done and the criteria, says minutes are a split, with 400 tokens', async () => {
  let seen: { prompt: string; maxTokens: number; timeoutMs?: number } = { prompt: '', maxTokens: 0 }
  const $ = askerOf(ask => {
    seen = ask as typeof seen
    return '3. Probar — 4 min\n4. Informar — 1 min'
  })
  const plan = applyCount(fresh(), 1, 3 * MIN, 3 * MIN) as PlanState
  const out = await askReplan($, { mission: 'Migrar', plan, elapsedMs: 4 * MIN, history: '- 2s ✓ Read a.md', id: 'a1' })
  expect(out).toHaveLength(2)
  expect(seen.maxTokens).toBe(400)
  expect(seen.prompt).toContain('reparto')
  expect(seen.prompt).toContain('<historial>\n- 2s ✓ Read a.md\n</historial>')
  expect(seen.prompt).toMatch(/<pasos_hechos>\n1\. Leer el código · previsto 2 min · real 3 min\n<\/pasos_hechos>/)
  expect(seen.prompt).toContain('<paso_actual>2. Escribir el cambio')
  expect(seen.prompt).toMatch(/<pasos_pendientes>\n3\. Probarlo · reparto .* min\n4\. Documentar/)
  expect(seen.prompt.startsWith('Un agente de programación')).toBe(true)
  expect(seen.prompt).toContain('<example>')
  expect(seen.prompt).toContain('ninguno</example>')
  const bad = await askReplan(askerOf(() => 'no sé') , { mission: 'Migrar', plan, elapsedMs: 4 * MIN, history: '', id: 'a1' })
  expect(bad).toBeUndefined()
})

test('a falta that keeps growing never lowers the bar', () => {
  let plan = fresh()
  let last = planBar(plan, 0)
  for (let elapsed = MIN; elapsed <= 12 * MIN; elapsed += MIN) {
    plan = applyLeft(plan, 3 * (elapsed / MIN), elapsed)
    const bar = planBar(plan, elapsed)
    expect(bar).toBeGreaterThanOrEqual(last)
    last = bar
  }
})

// --- Replan wiring: a separate Haiku call after an applied check. ---

const REPLAN_OK = '3. Probar y corregir — 4 min\n4. Informar — 1 min'
const replanReply: { text: string; gate?: Promise<void> } = { text: REPLAN_OK }
const planReply = { text: GOOD }

/** A GOOD-plan run (10 min, 4 steps): plan checks answer `checkReply`, replan prompts (`<historial>`) answer `replanReply`; `kinds` logs C (check) and H (replan) in order. */
function replanEngine(on: Parameters<Parameters<typeof test>[1]>[1], prompts: string[], kinds: string[] = []) {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', async (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    const usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
    if (prompt.includes('<historial>')) {
      prompts.push(prompt)
      kinds.push('H')
      await replanReply.gate
      return { value: { isAnswered: true, text: replanReply.text, usage } }
    }
    if (prompt.includes('<pasos>')) {
      prompts.push(prompt)
      kinds.push('C')
    }
    const text = prompt.includes('<duracion_total>') ? planReply.text : prompt.includes('<tareas_parecidas>') ? 'minutos: 10' : prompt.includes('<pasos>') ? checkReply.text : '?'
    return { value: { isAnswered: true, text, usage } }
  })
  return mock.clock(on)
}

/** Resets the shared replies; a test sets what it needs. */
function resetReplies() {
  checkReply.text = 'paso: 2\nfalta: 3'
  replanReply.text = REPLAN_OK
  replanReply.gate = undefined
  planReply.text = GOOD
}

/** The plan header text of the first running card (`<step> N% · ~T`), or undefined. */
async function headerOf($: Parameters<Parameters<typeof test>[1]>[0]): Promise<string | undefined> {
  const pane = await paneOf($)
  const head = await pane.find({ type: 'Text', text: /\d+% · (~\d+ min|<1 min|finalizando)$/ })
  await pane.unmount()
  return head?.text
}

/** Advances in 30 s hops (a check per hop at most), settling after each. */
async function run(clock: { advance(ms: number): Promise<void> }, ms: number) {
  for (let spent = 0; spent < ms; spent += 30_000) {
    await clock.advance(30_000)
    await settle()
  }
}

test('a stuck step is replanned once: 50% and 80% checks never, the 95% check once, overdue checks answering falta 1 not again (A1)', async ($, on) => {
  resetReplies()
  const prompts: string[] = []
  const kinds: string[] = []
  const clock = replanEngine(on, prompts, kinds)
  checkReply.text = 'paso: 1\nfalta: 1'
  await start($, clock)
  await $.tool.call(readCall('s1'))
  await run(clock, 10 * MIN)
  const order = kinds.join('')
  expect(order).toMatch(/^CCH/)
  expect(order.split('H')).toHaveLength(2)
  expect(prompts.filter(prompt => prompt.includes('<historial>'))[0]).toMatch(/<historial>\n- \S+ ✓ Read s1\.md\n<\/historial>/)
})

test('a step change replans from the plan the check produced: the next pending step follows the current one, no duplicate (A3)', async ($, on) => {
  resetReplies()
  const prompts: string[] = []
  const kinds: string[] = []
  const clock = replanEngine(on, prompts, kinds)
  await start($, clock)
  await $.tool.call(readCall('c1'))
  await settle()
  await clock.advance(60_000)
  await settle()
  expect(kinds.join('')).toBe('CH')
  const replan = prompts.find(prompt => prompt.includes('<historial>')) ?? ''
  expect(replan).toContain('<paso_actual>2. Escribir el cambio')
  expect(replan).toMatch(/<pasos_hechos>\n1\. Leer el código · previsto 2 min · real 1 min\n<\/pasos_hechos>/)
  expect(replan).toMatch(/<pasos_pendientes>\n3\. Probarlo · reparto \S+ min\n4\. Documentar/)
  expect(await headerOf($)).toMatch(/^Escribir el cambio \d+% · /)
  // The next step shown is the replanned one.
  checkReply.text = 'paso: 3\nfalta: 2'
  await $.tool.call(readCall('c2'))
  await settle()
  await run(clock, 4 * MIN)
  expect(await headerOf($)).toMatch(/^Probar y corregir \d+% · /)
})

test('a replan answer that arrives after the step moved again is dropped (seq)', async ($, on) => {
  resetReplies()
  const prompts: string[] = []
  const kinds: string[] = []
  const clock = replanEngine(on, prompts, kinds)
  let release: () => void = () => undefined
  replanReply.gate = new Promise<void>(resolve => {
    release = resolve
  })
  await start($, clock)
  await $.tool.call(readCall('d1'))
  await settle()
  await clock.advance(60_000)
  await settle()
  expect(kinds.join('')).toBe('CH')
  // While the replan waits, another check advances the step to 3.
  checkReply.text = 'paso: 3\nfalta: 2'
  await $.tool.call(readCall('d2'))
  await settle()
  await run(clock, 4 * MIN)
  expect(kinds.filter(kind => kind === 'H')).toHaveLength(1)
  replanReply.text = '3. Zeta — 4 min'
  release()
  await settle()
  await settle()
  // The advance that landed while the replan was in flight gets its own replan once the first one ends.
  expect(kinds.filter(kind => kind === 'H')).toHaveLength(2)
  // The late answer is dropped: the step after "Probarlo" is still the plan's own "Documentar", not "Zeta".
  replanReply.text = 'ninguno'
  checkReply.text = 'paso: 4\nfalta: 1'
  await $.tool.call(readCall('d3'))
  await settle()
  await run(clock, 4 * MIN)
  expect(await headerOf($)).toMatch(/^Documentar \d+% · /)
})

test('a replan answer 15 s late never lowers the shown percent (A5)', async ($, on) => {
  resetReplies()
  const clock = replanEngine(on, [])
  let release: () => void = () => undefined
  replanReply.gate = new Promise<void>(resolve => {
    release = resolve
  })
  replanReply.text = '3. Probar — 0.2 min'
  await start($, clock)
  await $.tool.call(readCall('l1'))
  await settle()
  await clock.advance(60_000)
  await settle()
  await clock.advance(15_000)
  await settle()
  const before = Number(/(\d+)% /.exec((await headerOf($)) ?? '')?.[1])
  release()
  await settle()
  await settle()
  const after = Number(/(\d+)% /.exec((await headerOf($)) ?? '')?.[1])
  expect(before).toBeGreaterThan(0)
  expect(after).toBeGreaterThanOrEqual(before)
})

test('the header ends in the time left even with a 40-character step title (A7)', async ($, on) => {
  resetReplies()
  const clock = replanEngine(on, [])
  planReply.text = '1. Leer la conversión completa del repositorio entero — 2 min\n2. Escribir — 5 min\n3. Probar — 3 min'
  await start($, clock)
  const head = await headerOf($)
  // A 60-column vscode pane has no spare room: the default 26.
  expect(head).toMatch(/^Leer la conversión comple… \d+% · ~\d+ min$/)
  // An 80-column one gives the title a little more, never all of it, and keeps the time.
  const wide = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: { ...PANE_PROPS, bodyColumns: 80 } } as never)
  const wideHead = (await wide.find({ type: 'Text', text: /\d+% · ~\d+ min$/ }))?.text
  await wide.unmount()
  expect(wideHead).toMatch(/^Leer la conversión completa del repos… \d+% · ~\d+ min$/)
})

test('the step title takes a little of the free room: never under 26, never over 38, 26 without a width', () => {
  expect(stepTitleChars(undefined, 'x'.repeat(40))).toBe(26)
  // Narrow: the default.
  expect(stepTitleChars(50, 'x'.repeat(40))).toBe(26)
  // Some room: what is left less a margin of 10.
  expect(stepTitleChars(80, 'x'.repeat(40))).toBe(30)
  // Wide: capped.
  expect(stepTitleChars(200, 'x'.repeat(40))).toBe(38)
})

test('a replan whose reply does not parse keeps the plan', async ($, on) => {
  resetReplies()
  const kinds: string[] = []
  const clock = replanEngine(on, [], kinds)
  replanReply.text = 'creo que quedan dos pasos'
  await start($, clock)
  await $.tool.call(readCall('k1'))
  await settle()
  await clock.advance(60_000)
  await settle()
  expect(kinds.join('')).toBe('CH')
  checkReply.text = 'paso: 3\nfalta: 2'
  await $.tool.call(readCall('k2'))
  await settle()
  await run(clock, 4 * MIN)
  expect(await headerOf($)).toMatch(/^Probarlo \d+% · /)
})

