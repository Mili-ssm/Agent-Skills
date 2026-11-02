import { expect, mock, test } from 'claude-code/testing'

import { estimateOf } from '../hooks/agents'
import {
  PLAN_ENABLED,
  PLAN_MIN_MS,
  applyCount,
  applyOverdue,
  newPlan,
  nextPlanCheck,
  parsePlan,
  planBar,
  planView,
  shouldPlan,
  stepsLine,
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
})

test('a new plan adds up to the estimate and `pasos: N` reads the first line only', () => {
  const plan = fresh()
  expect(plan.steps.reduce((sum, step) => sum + step.estMs, 0)).toBe(10 * MIN)
  expect(plan.stepEndAt).toBe(2 * MIN)
  expect(stepsLine('pasos: 3\nporque')).toBe(3)
  expect(stepsLine('hay 3')).toBeUndefined()
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

test('a count that jumps splits the time evenly and the factor stays in 0.5 to 3', () => {
  const plan = fresh()
  // Steps 1-2 (7 min estimated) done in 7 min at once: 3.5 min each, factor 1.
  const jump = applyCount(plan, 2, 7 * MIN, 0)
  expect(jump?.steps.map(step => step.realMs)).toEqual([3.5 * MIN, 3.5 * MIN, undefined, undefined])
  expect(jump?.factor).toBe(1)
  expect(applyCount(plan, 2, 60 * MIN, 0)?.factor).toBe(3)
  expect(applyCount(plan, 1, 10_000, 0)?.factor).toBe(0.5)
  // The count only grows.
  expect(applyCount(jump as PlanState, 2, 8 * MIN, 0)).toBeUndefined()
  expect(applyCount(jump as PlanState, 1, 8 * MIN, 0)).toBeUndefined()
})

test('done may reach y/y while running: "finalizando", never 0 min, bar under 100%, no more checks', () => {
  const plan = applyCount(fresh(), 9, 8 * MIN, 0) as PlanState
  expect(plan.done).toBe(4)
  const view = planView({ plan, startedAt: 0 }, 9 * MIN)
  expect(view).toMatchObject({ text: '4/4 pasos', isWrappingUp: true, leftMs: 0 })
  expect(view?.percent).toBe(99)
  expect(nextPlanCheck(plan, 60 * MIN, 60 * MIN)).toBeUndefined()
})

test('checks come at 50% and 80% of the step, 1 min apart, and at most 20 min apart', () => {
  const plan = fresh()
  // Step 1 lasts 2 min: 50% is 1 min, 80% 1.6 min.
  expect(nextPlanCheck(plan, 50_000, 50_000)).toBeUndefined()
  expect(nextPlanCheck(plan, MIN, MIN)).toEqual({ kind: 'progress', fired: 1 })
  expect(nextPlanCheck({ ...plan, fired: 1, askedAt: MIN }, 1.6 * MIN, 1.6 * MIN)).toBeUndefined()
  expect(nextPlanCheck({ ...plan, fired: 1, askedAt: MIN }, 2 * MIN, 2 * MIN)).toEqual({ kind: 'progress', fired: 2 })
  // Overdue: estimate + 15 s.
  expect(nextPlanCheck({ ...plan, fired: 2, askedAt: 0 }, 2 * MIN + 14_000, 2 * MIN + 14_000)).toBeUndefined()
  expect(nextPlanCheck({ ...plan, fired: 2, askedAt: 0 }, 2 * MIN + 15_000, 2 * MIN + 15_000)).toEqual({ kind: 'overdue', fired: 2 })
  // A long step with both checks done still gets one every 20 min.
  const long = { ...plan, stepEndAt: 90 * MIN, stepEstMs: 90 * MIN, fired: 2, countAt: 0, askedAt: 0 }
  expect(nextPlanCheck(long, 19 * MIN, 19 * MIN)).toBeUndefined()
  expect(nextPlanCheck(long, 20 * MIN, 20 * MIN)).toEqual({ kind: 'progress', fired: 2 })
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

// --- Integration: a long agent's card says `x/y pasos`. ---

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
    const text = prompt.includes('<duracion_total>') ? planReply : prompt.includes('<tareas_parecidas>') ? 'minutos: 10' : prompt.includes('<pasos>') ? 'pasos: 2' : '?'
    return { value: { isAnswered: true, text, usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } }
  })
  return mock.clock(on)
}

test('a long agent card shows x/y pasos with the time left, and a step check moves it', async ($, on) => {
  const prompts: string[] = []
  const clock = engine(on, GOOD, prompts)
  await $.agent.spawn(SPAWN)
  await new Promise(resolve => setTimeout(resolve, 20))
  await clock.advance(10_000)
  const pane = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  expect((await pane.find({ type: 'Text', text: /pasos/ }))?.text).toBe('0/4 pasos · ~10 min')
  await pane.unmount()
  // Step 1 lasts 2 min: the check at 1 min asks the count and Haiku says 2 are done.
  await clock.advance(60_000)
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(prompts.some(prompt => prompt.includes('<pasos>'))).toBe(true)
  const later = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  expect((await later.find({ type: 'Text', text: /pasos/ }))?.text).toMatch(/^2\/4 pasos · /)
  expect(await later.find({ type: 'Text', text: /%/ })).toBeUndefined()
  await later.unmount()
})

test('an invalid plan reply falls back silently to the plain percent', async ($, on) => {
  const clock = engine(on, 'no sé', [])
  await $.agent.spawn(SPAWN)
  await new Promise(resolve => setTimeout(resolve, 20))
  await clock.advance(30_000)
  const pane = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  expect(await pane.find({ type: 'Text', text: /pasos/ })).toBeUndefined()
  expect(await pane.find({ type: 'Text', text: /%/ })).toBeDefined()
  await pane.unmount()
})
