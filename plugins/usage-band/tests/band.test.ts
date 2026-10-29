import { expect, mock, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

import { activity, bar, formatCycle, formatDuration, formatLine, formatTally, formatTokens } from '../hooks/register'
import type { Cycle } from '../types'

// Token usage as a turn reports it.
const usage = (model: string, input: number, output: number) => ({
  model,
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: 0,
  cache_creation_input_tokens: 0,
})

test('formatters', () => {
  expect(formatTokens(950)).toBe('950')
  expect(formatTokens(12345)).toBe('12k')
  expect(formatTokens(1234567)).toBe('1.2M')
  expect(formatDuration(8400)).toBe('8s')
  expect(formatDuration(75000)).toBe('1m15s')
  expect(formatDuration(3725000)).toBe('1h02m')
  expect(formatTally({})).toBe('no tokens')
  expect(bar(50, 100)).toBe('▇▇▇▁▁')
  expect(bar(100, 100)).toBe('▇▇▇▇▇')
  expect(bar(1, 100)).toBe('▇▁▁▁▁')
})

test('cycle formatters', () => {
  const cycle: Cycle = {
    byModel: { opus: { total: 1_200_000, output: 20_000 }, sonnet: { total: 257_000, output: 7000 } },
    startedAt: 0,
    activeMs: 0,
    busySince: 0,
    logged: false,
    doing: null,
    conclusion: null,
    calls: 62,
    skills: 2,
    agents: 3,
  }
  // Busy: counts, then what Claude does now; tokens stay out of the live line.
  expect(formatCycle(cycle, 192_000)).toBe('⏱ 3m12s · 62 calls · 2 skills · 3 agents')
  expect(formatCycle({ ...cycle, doing: 'Run the e2e suite' }, 192_000)).toBe('⏱ 3m12s · 62 calls · 2 skills · 3 agents · ▸ Run the e2e suite')
  // Idle: a check mark and the conclusion; the printed line adds the session's time and tokens.
  const idle = { ...cycle, busySince: null, doing: 'stale', conclusion: 'login works; 2 e2e tests fail' }
  expect(formatLine(idle, 192_000, { durationMs: 2_290_000, turns: 9, byModel: { opus: { total: 41_700_000, output: 0 } } })).toBe(
    '✓ 3m12s · 62 calls · 2 skills · 3 agents — login works; 2 e2e tests fail │ Σ 38m10s · 41.7M',
  )
  // Zero counts are left out and a single one is singular.
  expect(formatCycle({ ...cycle, calls: 1, skills: 0, agents: 0 }, 4000)).toBe('⏱ 4s · 1 call')
})

test('a call in a few words', () => {
  expect(activity('Bash', { command: 'npm test', description: 'Run the unit tests' })).toBe('Run the unit tests')
  expect(activity('Bash', { command: 'ls -la\necho hi' })).toBe('ls -la')
  expect(activity('Read', { file_path: '/repo/src/app.ts' })).toBe('Read app.ts')
  expect(activity('Skill', { skill: 'plan' })).toBe('Skill plan')
  expect(activity('Agent', { description: 'Explore the auth code', prompt: 'long brief' })).toBe('Explore the auth code')
  expect(activity('TodoWrite', {})).toBe('TodoWrite')
  expect(activity('Bash', { description: 'A description long enough to need a cut. '.repeat(4) })).toBe(
    'A description long enough to need a cut. A description long enough to need a cut. A description long enough to need a cut. A description lo…',
  )
})

type On = Parameters<TestBody>[1]

// A turn ending as the engine reports it.
const complete = (init: { agentId?: string; durationMs: number; turnId: string; model: string; input: number; output: number }) => ({
  ...(init.agentId === undefined ? {} : { agentId: init.agentId }),
  answer: 'done',
  durationMs: init.durationMs,
  isAborted: false,
  turnId: init.turnId,
  reason: 'answer' as const,
  usage: usage(init.model, init.input, init.output),
})

// A submitted prompt as the engine raises it, `origin` saying who it came from.
const prompt = (text: string, origin: { kind: string; [key: string]: unknown } = { kind: 'composer' }, extra: object = {}) =>
  ({ text, wait: false, origin, ...extra }) as never

// The engine beneath the mod, recording the log rows and status lines it is asked to draw; time stands still until the
// test moves it. `agents` is what `$.agent.list()` answers.
function engine(on: On) {
  const lines: string[] = []
  const statuses: (string | undefined)[] = []
  const agents: { id: string; status: string }[] = []
  // The surfaces the session draws on, as \`$.session.surfaces()\` answers.
  const surfaces: string[] = ['vscode']
  // What Haiku answers for the conclusion (`reply`) and for the live description (`doing`); `null` gives no answer.
  // `described` counts the description requests.
  const haiku: { reply: string | null; doing: string | null; described: number } = {
    reply: '«Plan ready.»',
    doing: '«Revisa las notas.»',
    described: 0,
  }
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('tool.call', () => ({ result: {} }))
  on('agent.list', () => ({ value: agents }) as never)
  on('session.surfaces', () => ({ value: surfaces }) as never)
  on('model.complete', (_, e) => {
    const isDescription = e.prompt.startsWith('An AI coding assistant')
    haiku.described += isDescription ? 1 : 0
    const text = isDescription ? haiku.doing : haiku.reply
    return {
      value: text === null ? { isAnswered: false, text: '' } : { isAnswered: true, text, usage: usage('claude-haiku-5-5', 50, 8) },
    } as never
  })
  on('ui.log', (_, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  return { lines, statuses, agents, haiku, surfaces, clock: mock.clock(on) }
}

// Long enough for the idle check after a turn's end.
const SETTLE = 2000

test('the clock runs while Claude works, agents included, and stops with a printed line when all is done', async ($, on) => {
  const { lines, statuses, clock } = engine(on)

  // The person's first prompt: nothing to close yet; the clock starts.
  await $.prompt.submit(prompt('Plan the login feature'))
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('⏱ 0s')

  // First main turn: the line moves once a second.
  await $.turn.start({ text: 'Plan the login feature', turnId: 't1' })
  await clock.advance(3000)
  expect(statuses.at(-1)).toBe('⏱ 3s')
  await $.tool.call({ tool: 'Bash', command: 'ls', description: 'List files' })
  await $.tool.call({ tool: 'Bash', command: 'pwd' })
  await $.tool.call({ tool: 'Skill', skill: 'plan' })
  await $.tool.call({ tool: 'Agent', description: 'Explore', prompt: 'Look around', subagent_type: 'Explore' })
  await $.tool.call({ tool: 'Agent', description: 'Review', prompt: 'Review it', subagent_type: 'Explore' })
  // A background agent starts its run; its own calls count too.
  await $.turn.start({ text: 'Review it', turnId: 's1', agentId: 'a1' })
  await $.tool.call({ tool: 'Bash', command: 'cat a', description: 'Read the notes', agentId: 'a1' })
  expect(statuses.at(-1)).toBe('⏱ 3s · 6 calls · 1 skill · 2 agents · ▸ Revisa las notas')
  await clock.advance(117_000)
  await $.turn.complete(complete({ durationMs: 120_000, turnId: 't1', model: 'claude-opus-5-5', input: 700_000, output: 10_000 }))
  expect(statuses.at(-1)).toBe('⏱ 2m00s · 6 calls · 1 skill · 2 agents · ▸ Revisa las notas')

  // The main loop is done but the agent still works: the clock goes on and nothing is printed.
  await clock.advance(600_000)
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('⏱ 12m00s · 6 calls · 1 skill · 2 agents · ▸ Revisa las notas')

  // The agent ends: nothing works any more, so the clock stops at its end; Haiku sums up the answer and the line is printed.
  await $.turn.complete(complete({ agentId: 'a1', durationMs: 597_000, turnId: 's1', model: 'claude-sonnet-5-5', input: 250_000, output: 7000 }))
  await clock.advance(SETTLE)
  expect(lines).toEqual(['✓ 12m00s · 6 calls · 1 skill · 2 agents — Plan ready │ Σ 12m00s · 967k'])
  expect(statuses.at(-1)).toBe('✓ 12m00s · 6 calls · 1 skill · 2 agents — Plan ready')

  // The person is away: the frozen line stays as it is.
  await clock.advance(600_000)
  expect(statuses.at(-1)).toBe('✓ 12m00s · 6 calls · 1 skill · 2 agents — Plan ready')

  // A hand-back wakes the model: machine-made prompts open no cycle, but the work resumes the same one.
  const machine = [
    prompt('<task-notification>agent done</task-notification>', { kind: 'task-notification' }),
    prompt('wake up', { kind: 'scheduled-trigger' }),
    prompt('hello from a peer', { kind: 'peer' }),
    prompt('from a plugin', { kind: 'plugin', name: 'other', asUser: true }),
    prompt('queued by the engine', { kind: 'unclassified' }),
    prompt('not shown as typed', { kind: 'composer' }, { isMeta: true }),
    prompt('/usage-band', { kind: 'composer' }, { command: { name: 'usage-band', args: '' } }),
  ]
  for (const submission of machine) {
    await $.prompt.submit(submission)
  }
  expect(lines).toHaveLength(1)
  await $.turn.start({ text: '', turnId: 't2' })
  expect(statuses.at(-1)).toBe('⏱ 12m00s · 6 calls · 1 skill · 2 agents')
  await clock.advance(72_000)
  await $.tool.call({ tool: 'Read', file_path: '/tmp/a.ts' })
  await $.turn.complete(complete({ durationMs: 72_000, turnId: 't2', model: 'claude-opus-5-5', input: 480_000, output: 10_000 }))
  await clock.advance(SETTLE)
  // The idle pause is not counted; the new idle moment prints the updated line.
  expect(lines).toEqual([
    '✓ 12m00s · 6 calls · 1 skill · 2 agents — Plan ready │ Σ 12m00s · 967k',
    '✓ 13m12s · 7 calls · 1 skill · 2 agents — Plan ready │ Σ 13m12s · 1.5M',
  ])

  // /usage-band: the current cycle on top, then the session.
  const { text } = await $.command.run({ command: 'usage-band' } as never)
  expect(text).toBe(
    [
      'Current cycle: ✓ 13m12s · 7 calls · 1 skill · 2 agents — Plan ready',
      'Cycle tokens: opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k',
      'Session: 13m12s over 2 answers · 1.5M tokens',
      'opus     ▇▇▇▇▇  1.2M (20k out) 82%',
      'sonnet   ▇▁▁▁▁  257k (7k out) 18%',
    ].join('\n'),
  )

  // The person's next prompt: the line is already printed, so only the new cycle starts.
  await $.prompt.submit(prompt('Now implement it'))
  expect(lines).toHaveLength(2)
  expect(statuses.at(-1)).toBe('⏱ 0s')

  // The second cycle, short: its line carries the session's running total.
  await $.turn.start({ text: 'Now implement it', turnId: 't3' })
  await clock.advance(5000)
  await $.turn.complete(complete({ durationMs: 5000, turnId: 't3', model: 'claude-opus-5-5', input: 40_000, output: 2000 }))
  expect(statuses.at(-1)).toBe('⏱ 5s')
  await clock.advance(SETTLE)
  expect(lines[2]).toBe('✓ 5s — Plan ready │ Σ 13m17s · 1.5M')
  await $.prompt.submit(prompt('Thanks', { kind: 'bridge' }))
  expect(lines).toHaveLength(3)
})

test('an agent the engine still lists as working keeps the clock running', async ($, on) => {
  const { lines, statuses, agents, clock } = engine(on)

  await $.prompt.submit(prompt('Go'))
  await $.turn.start({ text: 'Go', turnId: 't1' })
  await clock.advance(10_000)
  // A teammate works in a pane of its own: no turn of it was heard, but the roster says it runs.
  agents.push({ id: 'mate@team', status: 'running' })
  await $.turn.complete(complete({ durationMs: 10_000, turnId: 't1', model: 'claude-opus-5-5', input: 1000, output: 100 }))
  await clock.advance(SETTLE)
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('⏱ 12s')
  // It goes idle; the next turn end finds nothing working and stops the clock there.
  agents[0] = { id: 'mate@team', status: 'idle' }
  await $.turn.start({ text: '', turnId: 't2' })
  await clock.advance(3000)
  await $.turn.complete(complete({ durationMs: 3000, turnId: 't2', model: 'claude-opus-5-5', input: 1000, output: 100 }))
  await clock.advance(SETTLE)
  expect(lines).toEqual(['✓ 15s — Plan ready │ Σ 15s · 2k'])
})

test('a cycle without tokens logs no line', async ($, on) => {
  const { lines, clock } = engine(on)

  await $.prompt.submit(prompt('Just a question'))
  await $.turn.start({ text: 'Just a question', turnId: 't1' })
  await $.turn.complete({ answer: '', durationMs: 0, isAborted: true, turnId: 't1', reason: 'aborted' } as never)
  await clock.advance(SETTLE)
  await $.prompt.submit(prompt('Another'))
  expect(lines).toEqual([])
})

test('a prompt typed over a running turn closes the old cycle and starts the new one at that moment', async ($, on) => {
  const { lines, statuses, haiku, clock } = engine(on)
  haiku.reply = null

  await $.prompt.submit(prompt('Start'))
  await $.turn.start({ text: 'Start', turnId: 't1' })
  await clock.advance(10_000)
  await $.prompt.submit(prompt('Actually, do this instead'))
  // Nothing finished yet, so no line; the new cycle's time counts from its prompt.
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('⏱ 0s')
  await clock.advance(4000)
  expect(statuses.at(-1)).toBe('⏱ 4s')
  await $.turn.complete(complete({ durationMs: 14_000, turnId: 't1', model: 'claude-haiku-5-5', input: 1000, output: 200 }))
  expect(statuses.at(-1)).toBe('⏱ 4s')
  await clock.advance(SETTLE)
  // Haiku gave no answer: the line goes out without a conclusion.
  expect(lines).toEqual(['✓ 4s │ Σ 14s · 1k'])
})

test('a subagent-only turn end before any prompt shows in the status line and logs nothing', async ($, on) => {
  const { lines, statuses, clock } = engine(on)

  await $.turn.complete(complete({ agentId: 'a1', durationMs: 5000, turnId: 's1', model: 'claude-haiku-5-5', input: 1000, output: 100 }))
  await clock.advance(SETTLE)
  expect(lines).toEqual([])
  expect(statuses.at(-1)).toBe('✓ 0s')
})

test('work seen with no cycle open (after a reload or an update) opens one, so a running task never shows as done', async ($, on) => {
  const { lines, statuses, agents, clock } = engine(on)

  // An agent started before the reload keeps working: only its calls and its roster entry are seen.
  agents.push({ id: 'a1', status: 'running' })
  await $.tool.call({ tool: 'Bash', command: 'sed -i x a.js', description: 'Migrate the scripts', agentId: 'a1' })
  // The call's own description shows at once; Haiku's plain-words version replaces it when it lands.
  expect(statuses.at(-1)).toBe('⏱ 0s · 1 call · ▸ Migrate the scripts')
  await clock.advance(30_000)
  expect(statuses.at(-1)).toBe('⏱ 30s · 1 call · ▸ Revisa las notas')

  // Its run ends and the roster says it is done: the clock stops and the line is printed.
  agents[0] = { id: 'a1', status: 'completed' }
  await $.turn.complete(complete({ agentId: 'a1', durationMs: 30_000, turnId: 's1', model: 'claude-sonnet-5-5', input: 5000, output: 500 }))
  await clock.advance(SETTLE)
  // No main-loop answer was seen since the reload, so there is nothing for Haiku to sum up.
  expect(lines).toEqual(['✓ 30s · 1 call │ Σ 30s · 6k'])
})

test('Haiku describes the work in plain words at most every 30 s, and only after new calls', async ($, on) => {
  const { statuses, haiku, clock } = engine(on)
  haiku.doing = null

  await $.prompt.submit(prompt('Resuelve la deuda técnica del frontend'))
  await $.turn.start({ text: 'Resuelve la deuda técnica del frontend', turnId: 't1' })
  // No description from Haiku yet: the raw call shows meanwhile.
  await $.tool.call({ tool: 'Bash', command: "sed -i 's/engine/store/g' test/a.js" })
  expect(statuses.at(-1)).toBe("⏱ 0s · 1 call · ▸ sed -i 's/engine/store/g' test/a.js")
  expect(haiku.described).toBe(1)

  // Haiku answers from now on; calls inside the 30 s gap wait for one description at its end.
  haiku.doing = '«Cambia engine por store en los tests»'
  await clock.advance(5000)
  await $.tool.call({ tool: 'Bash', command: 'npm run e2e', description: 'Run the e2e suite' })
  await $.tool.call({ tool: 'Read', file_path: '/repo/test/a.js' })
  expect(haiku.described).toBe(1)
  expect(statuses.at(-1)).toBe('⏱ 5s · 3 calls · ▸ Read a.js')
  await clock.advance(25_000)
  expect(haiku.described).toBe(2)
  expect(statuses.at(-1)).toBe('⏱ 30s · 3 calls · ▸ Cambia engine por store en los tests')

  // Its words stay while new calls come; no new call, no new request.
  await $.tool.call({ tool: 'Edit', file_path: '/repo/test/b.js', old_string: 'engine', new_string: 'store' })
  expect(statuses.at(-1)).toBe('⏱ 30s · 4 calls · ▸ Cambia engine por store en los tests')
  await clock.advance(30_000)
  expect(haiku.described).toBe(3)
  await clock.advance(60_000)
  expect(haiku.described).toBe(3)
})

test('Desktop draws the cycle in the band above the prompt instead of its small status line', async ($, on) => {
  const { statuses, surfaces, clock } = engine(on)
  surfaces.splice(0, surfaces.length, 'desktop')
  // The engine beneath draws an empty band.
  on('ui.render', ($, e) => $.ui.resolve(e).Box({}))
  const band = (surface: string) =>
    $.ui.mount({
      plugin: 'usage-band',
      component: 'AbovePrompt',
      requestId: 'band',
      surface,
      props: { hasSurvey: false, isWorking: true, maxRows: 20, bodyColumns: 80, scroll: { offset: 0, bodyRows: 20 } },
    } as never)

  await $.prompt.submit(prompt('Go'))
  await $.turn.start({ text: 'Go', turnId: 't1' })
  await $.tool.call({ tool: 'Bash', command: 'npm test', description: 'Run the unit tests' })
  await clock.advance(3000)
  // Desktop is the only surface: the footer status line stays empty.
  expect(statuses.filter(status => status !== undefined)).toEqual([])
  const busy = await band('desktop')
  expect((await busy.find({ type: 'Text', text: /^⏱/ }))?.text).toBe('⏱ 3s')
  expect((await busy.find({ type: 'Text', text: /call/ }))?.text).toBe('1 call')
  expect((await busy.find({ type: 'Text', text: /^▸/ }))?.text).toBe('▸ Revisa las notas')
  // The first cycle is the whole session: no session total yet.
  expect(await busy.find({ type: 'Text', text: /Σ/ })).toBeUndefined()
  await busy.unmount()

  // Done: a check mark and Haiku's conclusion.
  await $.turn.complete(complete({ durationMs: 3000, turnId: 't1', model: 'claude-opus-5-5', input: 1000, output: 100 }))
  await clock.advance(SETTLE)
  const idle = await band('desktop')
  expect((await idle.find({ type: 'Text', text: /^✓/ }))?.text).toBe('✓ 3s')
  expect((await idle.find({ type: 'Text', text: /Plan ready/ }))?.text).toBe('Plan ready')
  await idle.unmount()

  // A second cycle: the session total shows on the right, with its tokens.
  await $.prompt.submit(prompt('Again'))
  await clock.advance(2000)
  const second = await band('desktop')
  expect((await second.find({ type: 'Text', text: /Σ/ }))?.text).toBe('Σ 5s · 1k')
  await second.unmount()

  // VS Code has no band: the hook draws nothing of its own there.
  const vscode = await band('vscode')
  expect(await vscode.find({ type: 'Text', text: /✓/ })).toBeUndefined()
  await vscode.unmount()

  // A terminal attached too: the status line comes back for it.
  surfaces.push('terminal')
  await $.tool.call({ tool: 'Read', file_path: '/repo/a.ts' })
  expect(statuses.at(-1)).toMatch(/^⏱ 2s · 1 call/)
})

test('on Desktop, /usage-band draws its bars as image bars', async ($, on) => {
  engine(on)
  on('ui.render', { component: 'CommandOutput' }, ($, e) => $.ui.resolve(e).Text({ children: e.props.text }))
  const output = await $.ui.mount({
    plugin: 'usage-band',
    component: 'CommandOutput',
    requestId: 'out',
    surface: 'desktop',
    props: { command: 'usage-band', args: '', text: 'opus     ▇▇▇▁▁  1.2M (20k out) 82%', isErrored: false },
  } as never)
  expect((await output.find({ type: 'Svg' })) !== undefined).toBe(true)
  expect((await output.find({ type: 'Text', text: /opus/ }))?.text).toBe('opus')
  expect(await output.find({ type: 'Text', text: /▇/ })).toBeUndefined()
  await output.unmount()
})
