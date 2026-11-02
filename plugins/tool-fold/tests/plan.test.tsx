import { expect, mock, test } from 'claude-code/testing'

import { estimateOf, scriptOf } from '../hooks/agents'
import { phraseOf } from '../hooks/waiting'
import {
  PLAN_ENABLED,
  PLAN_MIN_MS,
  applyCount,
  applyOverdue,
  callPointsAhead,
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
  expect(parsePlan('**1. A — 2 min**\n\n2. **B** — 3 min\n\n3. C — 1 min')?.map(step => step.title)).toEqual(['A', 'B', 'C'])
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

test('checks come at 50% and 80% of the step, 1 min apart, and at most 5 min apart', () => {
  const plan = fresh()
  // Step 1 lasts 2 min: 50% is 1 min, 80% 1.6 min.
  expect(nextPlanCheck(plan, 50_000, 50_000)).toBeUndefined()
  expect(nextPlanCheck(plan, MIN, MIN)).toEqual({ kind: 'progress', fired: 1 })
  expect(nextPlanCheck({ ...plan, fired: 1, askedAt: MIN }, 1.6 * MIN, 1.6 * MIN)).toBeUndefined()
  expect(nextPlanCheck({ ...plan, fired: 1, askedAt: MIN }, 2 * MIN, 2 * MIN)).toEqual({ kind: 'progress', fired: 2 })
  // Overdue: estimate + 15 s.
  expect(nextPlanCheck({ ...plan, fired: 2, askedAt: 0 }, 2 * MIN + 14_000, 2 * MIN + 14_000)).toBeUndefined()
  expect(nextPlanCheck({ ...plan, fired: 2, askedAt: 0 }, 2 * MIN + 15_000, 2 * MIN + 15_000)).toEqual({ kind: 'overdue', fired: 2 })
  // A long step with both checks done still gets one every 5 min.
  const long = { ...plan, stepEndAt: 90 * MIN, stepEstMs: 90 * MIN, fired: 2, countAt: 0, askedAt: 0 }
  expect(nextPlanCheck(long, 4 * MIN, 4 * MIN)).toBeUndefined()
  expect(nextPlanCheck(long, 5 * MIN, 5 * MIN)).toEqual({ kind: 'progress', fired: 2 })
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
  // `0/4 <step> N% · ~10 min`: count, share and time bold; the step title small, cut with … past STEP_TITLE_CHARS.
  // One Text with nested spans (sibling Texts wrap on vscode): count and time bold, the step title dim, the share plain.
  const head = await pane.find({ type: 'Text', text: /^0\/4 Leer el código \d+% · ~10 min$/ })
  expect(head?.props.bold).toBeUndefined()
  expect((await pane.find({ type: 'Text', text: /^0\/4$/ }))?.props.bold).toBe(true)
  expect((await pane.find({ type: 'Text', text: /^Leer el código$/ }))?.props).toMatchObject({ dimColor: true, size: 'footnote' })
  expect((await pane.find({ type: 'Text', text: /^· ~10 min$/ }))?.props.bold).toBe(true)
  await pane.unmount()
  // Step 1 lasts 2 min: the check at 1 min asks the count and Haiku says 2 are done.
  await clock.advance(60_000)
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(prompts.some(prompt => prompt.includes('<pasos>'))).toBe(true)
  const later = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  expect(await later.find({ type: 'Text', text: /^2\/4 / })).toBeDefined()
  expect(await later.find({ type: 'Text', text: /≈/ })).toBeUndefined()
  await later.unmount()
})

test('an invalid plan reply falls back silently to the plain percent', async ($, on) => {
  const clock = engine(on, 'no sé', [])
  await $.agent.spawn(SPAWN)
  await new Promise(resolve => setTimeout(resolve, 20))
  await clock.advance(30_000)
  const pane = await $.ui.mount({ plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: PANE_PROPS } as never)
  expect(await pane.find({ type: 'Text', text: /^\d\/\d / })).toBeUndefined()
  expect(await pane.find({ type: 'Text', text: /≈\d+%/ })).toBeDefined()
  await pane.unmount()
})

test('a long step title is cut with … in the header; the share stays apart', () => {
  const plan = newPlan([{ title: 'Leer la conversión v7.4-pre completa con calma', minutes: 4 }, { title: 'Informar', minutes: 1 }, { title: 'Fin', minutes: 1 }], 6 * 60_000, 0, 0)
  const view = planView({ plan, startedAt: 0 }, 60_000, true)
  expect(view?.step).toBe('Leer la conversión v7…')
  expect(view?.step?.length).toBeLessThanOrEqual(22)
  expect(view?.stepPct).toBe('25%')
})

test('a call that reads like a later step hints a count check; the 5 min ceiling still asks without hints', () => {
  const plan = newPlan([{ title: 'Leer el esquema actual', minutes: 30 }, { title: 'Escribir los scripts de migración', minutes: 10 }, { title: 'Informar', minutes: 2 }], 42 * 60_000, 0, 0)
  expect(callPointsAhead(plan, 'Escribe el script de migración de usuarios')).toBe(true)
  expect(callPointsAhead(plan, 'Lee el esquema actual de la tabla')).toBe(false)
  expect(callPointsAhead(plan, 'Run sed -n 1,6p samples.txt')).toBe(false)
  // 2 min into a 30 min step: no check yet; a hint after the last ask makes one.
  expect(nextPlanCheck(plan, 2 * 60_000, 2 * 60_000)).toBeUndefined()
  expect(nextPlanCheck({ ...plan, hintAt: 2 * 60_000 }, 2 * 60_000, 2 * 60_000)).toMatchObject({ kind: 'progress' })
  // No hint: 5 min without a count asks anyway (was 20).
  expect(nextPlanCheck(plan, 5 * 60_000, 5 * 60_000)).toMatchObject({ kind: 'progress' })
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
    const text = prompt.includes('<duracion_total>') ? LONG : prompt.includes('<tareas_parecidas>') ? 'minutos: 42' : prompt.includes('<pasos>') ? 'pasos: 0' : '?'
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
  await clock.advance(61_000)
  await settle()
  expect(countChecks(prompts)).toBe(0)
})

test('a phrase reply cut by maxTokens still gives its first line when that line ended', () => {
  const cut = { output_tokens: 80 }
  expect(phraseOf({ isAnswered: true, text: 'Ejecuta un script de Python que mide memoria\nEl script importa tracemalloc y…', usage: cut })).toBe('Ejecuta un script de Python que mide memoria')
  expect(phraseOf({ isAnswered: true, text: 'Ejecuta un script de Python que mide la memoria de cada conv', usage: cut })).toBe('')
  expect(phraseOf({ isAnswered: false, text: 'x\ny', usage: cut })).toBe('')
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
