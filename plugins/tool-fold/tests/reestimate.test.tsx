import { expect, mock, test } from 'claude-code/testing'

import { estimateOf, progressText, realPercent } from '../hooks/agents'
import {
  askMinutes,
  nextReask,
  percentAt,
  periodicGapMs,
  reanchor,
  reestimateLog,
  settleEstimate,
} from '../hooks/estimates'

const MIN = 60_000

/** A fake engine whose Haiku answers `text` and records the prompts. */
const fake = (text: string, prompts: string[] = []) =>
  ({
    model: {
      complete: async ({ prompt }: { prompt: string }) => {
        prompts.push(prompt)
        return { isAnswered: true, text, usage: { output_tokens: 0 } }
      },
    },
  }) as never

test('a re-ask asks for the minutes that remain and the total is elapsed + remaining, capped', async () => {
  const again = { elapsedMs: 10 * MIN, previousMs: 8 * MIN, kind: 'overdue' as const }
  expect(await askMinutes(fake('minutos: 5'), { text: 't', similar: [], again, id: 'x' })).toBe(15 * MIN)
  // Remaining 0 or prose: no answer, no clamp.
  expect(await askMinutes(fake('minutos: 0'), { text: 't', similar: [], again })).toBeUndefined()
  expect(await askMinutes(fake('unos 5'), { text: 't', similar: [], again })).toBeUndefined()
  // The first ask stays the total.
  expect(await askMinutes(fake('minutos: 5'), { text: 't', similar: [] })).toBe(5 * MIN)
  // The cap (24 h) applies to the total.
  expect(await askMinutes(fake('minutos: 1435'), { text: 't', similar: [], again })).toBe(24 * 60 * MIN)
  expect(reestimateLog.at(-1)).toContain('overdue old=8 min haiku-remaining=1435 min')
})

test('three re-ask wordings: progress with a real percent, progress blind, overdue; a wait never gets a percent', async () => {
  const prompts: string[] = []
  const $ = fake('minutos: 3', prompts)
  const base = { text: 't', similar: [], progress: 'Tareas: 2/5' }
  await askMinutes($, { ...base, again: { elapsedMs: 6 * MIN, previousMs: 10 * MIN, kind: 'progress', percent: 40 } })
  await askMinutes($, { text: 'bash', similar: [], again: { elapsedMs: 6 * MIN, previousMs: 10 * MIN, kind: 'periodic' } })
  await askMinutes($, { ...base, again: { elapsedMs: 12 * MIN, previousMs: 8 * MIN, kind: 'overdue', percent: 99 } })
  const [real, blind, overdue] = prompts as [string, string, string]
  expect(real.startsWith('Una tarea en segundo plano de un agente de programación lleva 6 min y va por 40%.')).toBe(true)
  expect(real).toContain('<porcentaje>40%</porcentaje>')
  expect(real).toContain('<progreso>Tareas: 2/5</progreso>')
  expect(real).toContain('<ya_transcurrido>6 min</ya_transcurrido>')
  expect(real.indexOf('Estima cuántos minutos FALTAN')).toBeLessThan(real.indexOf('<tarea>'))
  expect(blind.startsWith('Una tarea en segundo plano (sin información de avance) lleva 6 min.')).toBe(true)
  expect(blind).not.toContain('<porcentaje>')
  expect(blind).not.toContain('<progreso>Tareas')
  expect(blind.endsWith('Responde solo con la línea minutos: N (minutos restantes, número entero).')).toBe(true)
  expect(blind).toContain('<example>Con 6 min transcurridos, la respuesta es:\nminutos: 7</example>')
  expect(blind).toContain('<ya_transcurrido>6 min</ya_transcurrido>')
  expect(overdue).toContain('ya superó su estimación anterior (8 min) y lleva 12 min')
  expect(overdue).not.toContain('<porcentaje>')
  expect(overdue).toContain('<ya_transcurrido>12 min</ya_transcurrido>')
})

test('<progreso> is cut to its own 600 characters, apart from the 1500 of <tarea>', async () => {
  const prompts: string[] = []
  await askMinutes(fake('minutos: 3', prompts), {
    text: 'x'.repeat(2000),
    similar: [],
    progress: 'p'.repeat(900),
    again: { elapsedMs: MIN, previousMs: 2 * MIN, kind: 'progress', percent: 50 },
  })
  expect(prompts[0]).toContain(`<tarea>${'x'.repeat(1500)}</tarea>`)
  expect(prompts[0]).toContain(`<progreso>${'p'.repeat(600)}</progreso>`)
})

test('schedule: 50%, 80%, periodic gap clamped to 5-20 min, 30 s throttle, overdue after the grace', () => {
  const eta = 20 * MIN
  const at = (elapsedMs: number, over: Partial<Parameters<typeof nextReask>[0]> = {}) =>
    nextReask({ elapsedMs, etaMs: eta, lastAskAt: elapsedMs - MIN, ...over }, elapsedMs)
  expect(at(9 * MIN)).toBeUndefined()
  expect(at(10 * MIN)).toEqual({ kind: 'progress', step: 1 })
  expect(at(10 * MIN, { step: 1 })).toBeUndefined()
  expect(at(16 * MIN, { step: 1, lastAskAt: 10 * MIN })).toEqual({ kind: 'progress', step: 2 })
  // Both thresholds passed at once: one ask, both marked done.
  expect(at(17 * MIN)).toEqual({ kind: 'progress', step: 2 })
  expect(at(17 * MIN, { step: 2 })).toBeUndefined()
  // Overdue: the first tick past the estimate + 15 s even right after another ask, then every 30 s.
  expect(nextReask({ elapsedMs: eta + 15_000, etaMs: eta, lastAskAt: eta + 14_000, step: 2 }, eta + 15_000)?.kind).toBe('overdue')
  expect(at(eta + 14_000, { step: 2 })).toBeUndefined()
  expect(at(eta + 15_000, { step: 2 })).toEqual({ kind: 'overdue', step: 2 })
  expect(nextReask({ elapsedMs: eta + 40_000, etaMs: eta, lastAskAt: eta + 15_000, step: 2 }, eta + 40_000)).toBeUndefined()
  expect(nextReask({ elapsedMs: eta + 45_000, etaMs: eta, lastAskAt: eta + 15_000, step: 2 }, eta + 45_000)?.kind).toBe('overdue')
  // Throttle: never within 30 s of the last ask.
  expect(nextReask({ elapsedMs: 10 * MIN, etaMs: eta, lastAskAt: 10 * MIN - 29_000 }, 10 * MIN)).toBeUndefined()
  // Periodic: a tenth of the estimate, within 5 and 20 minutes.
  expect(periodicGapMs(20 * MIN)).toBe(5 * MIN)
  expect(periodicGapMs(120 * MIN)).toBe(12 * MIN)
  expect(periodicGapMs(600 * MIN)).toBe(20 * MIN)
  const long = 120 * MIN
  expect(nextReask({ elapsedMs: 100 * MIN, etaMs: long, lastAskAt: 88.1 * MIN, step: 2 }, 100 * MIN)).toBeUndefined()
  expect(nextReask({ elapsedMs: 100 * MIN, etaMs: long, lastAskAt: 88 * MIN, step: 2 }, 100 * MIN)?.kind).toBe('periodic')
  expect(nextReask({ elapsedMs: 11 * MIN, etaMs: 100 * MIN, lastAskAt: 0.5 * MIN, step: 0 }, 11 * MIN)?.kind).toBe('periodic')
})

test('stated and message estimates skip progress and periodic re-asks, not the overdue one', () => {
  for (const source of ['stated', 'message']) {
    const item = { etaMs: 20 * MIN, source, lastAskAt: 0, step: 0 }
    expect(nextReask({ ...item, elapsedMs: 17 * MIN }, 17 * MIN)).toBeUndefined()
    expect(nextReask({ ...item, elapsedMs: 40 * MIN, step: 2 }, 40 * MIN)?.kind).toBe('overdue')
  }
  expect(nextReask({ etaMs: 20 * MIN, source: 'guess', lastAskAt: 0, elapsedMs: 17 * MIN }, 17 * MIN)?.kind).toBe('progress')
})

test('damping: progress answers under 20% apart are ignored, others blend 50/50 (up or down); overdue only lengthens', () => {
  expect(settleEstimate('progress', 10 * MIN, 11.9 * MIN, 5 * MIN)).toBeUndefined()
  expect(settleEstimate('periodic', 10 * MIN, 8.1 * MIN, 5 * MIN)).toBeUndefined()
  expect(settleEstimate('progress', 10 * MIN, 14 * MIN, 5 * MIN)).toBe(12 * MIN)
  expect(settleEstimate('progress', 10 * MIN, 6 * MIN, 5 * MIN)).toBe(8 * MIN)
  expect(settleEstimate('overdue', 10 * MIN, 12 * MIN, 10.5 * MIN)).toBe(12 * MIN)
  expect(settleEstimate('overdue', 10 * MIN, 10 * MIN, 10 * MIN)).toBeUndefined()
})

test('percent never goes down when the estimate grows: an anchor, then a line to 99% at the new end', () => {
  const run = { startedAt: 0, etaMs: 10 * MIN, estimate: undefined } as never
  expect(estimateOf(run, 8 * MIN)).toBe(80)
  // At 8 min the estimate grows to 20 min: 8/20 = 40% would be a step back.
  const anchor = reanchor({ etaMs: 10 * MIN }, 20 * MIN, 8 * MIN)
  expect(anchor).toEqual({ at: 8 * MIN, pct: 80 })
  const grown = { startedAt: 0, etaMs: 20 * MIN, anchor } as never
  expect(estimateOf(grown, 8 * MIN)).toBe(80)
  const shown = [8, 10, 14, 19, 20, 25].map(min => estimateOf(grown, min * MIN) as number)
  expect(shown).toEqual([...shown].sort((a, b) => a - b))
  expect(percentAt(20 * MIN, 20 * MIN, anchor)).toBe(99)
  // Half way from the anchor to the end: 80 + 19/2.
  expect(percentAt(14 * MIN, 20 * MIN, anchor)).toBe(90)
  // A second change anchors at what is shown; an unchanged estimate keeps its anchor.
  expect(reanchor({ etaMs: 20 * MIN, anchor }, 20 * MIN, 14 * MIN)).toEqual(anchor)
  expect(reanchor({ etaMs: 20 * MIN, anchor }, 12 * MIN, 14 * MIN)).toEqual({ at: 14 * MIN, pct: 90 })
  expect(reanchor({}, 5 * MIN, MIN)).toBeUndefined()
})

test('an agent percent comes from a task list or the %-estimator, never from elapsed / estimate; <progreso> keeps the newest calls', () => {
  expect(realPercent({ todo: { done: 2, total: 5, completed: [] } })).toBe(40)
  expect(realPercent({ estimate: 35 })).toBe(35)
  expect(realPercent({})).toBeUndefined()
  const history = Array.from({ length: 40 }, (_, i) => ({ what: `Read file-${i}.ts`, ms: 1000, ok: true }))
  const text = progressText({ todo: { done: 1, total: 3, completed: [] }, history, current: [] } as never, 0)
  expect(text.length).toBeLessThanOrEqual(600)
  expect(text.startsWith('Tareas: 1/3')).toBe(true)
  expect(text).toContain('file-39.ts')
  expect(text).not.toContain('file-0.ts')
  const long = progressText({ history: [{ what: `Bash ${'x\n'.repeat(350)}`, ms: 1000, ok: true }], current: [] } as never, 0)
  expect(long.split('\n').filter(Boolean).length).toBeGreaterThanOrEqual(1)
  expect(long.length).toBeLessThanOrEqual(121)
})

const USAGE = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
const SPAWN = {
  tool_use_id: 'tu1',
  prompt: 'Build it',
  description: 'Find session creation',
  subagentType: 'Explore',
  provider: { plugin: 'engine', tier: 'core' },
  parentModel: 'claude-opus-5-5',
  background: true,
  fork: false,
} as never
const PANE = { plugin: 'tool-fold', component: 'Pane', requestId: 'agents', surface: 'vscode', props: { title: 'Agentes', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 12 }, view: {} } } as never

function engine(on: Parameters<Parameters<typeof test>[1]>[1], saved: Record<string, unknown>, answer: (prompt: string) => Promise<string> | string) {
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))
  on('store.get', (_, e) => ({ value: saved[e.key] }))
  on('store.set', (_, e) => {
    saved[e.key] = e.value
    return { value: undefined }
  })
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('model.complete', async (_, e) => {
    const prompt = String((e as { prompt?: string }).prompt)
    const text = prompt.includes('<tareas_parecidas>') ? await answer(prompt) : '?'
    return { value: { isAnswered: true, text, usage: USAGE } }
  })
  return mock.clock(on)
}

test('a stale answer is dropped: the first ask answering after a re-estimate does not overwrite it', async ($, on) => {
  const saved = { 'agent-samples': [{ summary: 'Explore: Find session creation', durationMs: 90_000, at: 1 }] }
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => {
    release = resolve
  })
  const clock = engine(on, saved, async prompt => {
    if (!prompt.includes('<ya_transcurrido>')) {
      await gate
      return 'minutos: 10'
    }
    // 45 s + 1 min = 105 s: within 20% of 90 s, so the re-estimate is ignored (and still the latest ask).
    return 'minutos: 1'
  })
  await $.agent.spawn(SPAWN)
  await clock.advance(46_000)
  release?.()
  await new Promise(resolve => setTimeout(resolve, 20))
  await clock.advance(1000)
  const pane = await $.ui.mount(PANE)
  // Had the 10-minute first answer landed, 47 s would be 8%.
  expect((await pane.find({ type: 'Text', text: /%/ }))?.text).toMatch(/^≈5\d%/)
  await pane.unmount()
})

test('an agent whose estimate is stated is re-asked only once overdue', async ($, on) => {
  const prompts: string[] = []
  const clock = engine(on, {}, prompt => {
    prompts.push(prompt)
    return 'minutos: 2'
  })
  await $.agent.spawn({ ...(SPAWN as object), description: 'Wait 2 minutes for the build' } as never)
  await clock.advance(119_000)
  expect(prompts.filter(prompt => prompt.includes('<ya_transcurrido>'))).toHaveLength(0)
  await clock.advance(20_000)
  const again = prompts.filter(prompt => prompt.includes('<ya_transcurrido>'))
  expect(again).toHaveLength(1)
  expect(again[0]).toContain('ya superó su estimación anterior')
})
