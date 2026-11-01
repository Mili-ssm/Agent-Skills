import { atom, read, update } from 'claude-code'
import type {
  AgentStatus,
  BoxProps,
  ElementConstructor,
  EngineInterface,
  PromptOrigin,
  Register,
  SvgProps,
  TextProps,
  Timer,
  TurnUsage,
} from 'claude-code'

import type { Cycle, Tally, Usage } from '../types'

// The slash command that answers with the session summary.
const COMMAND = 'usage-band'
const EMPTY: Usage = { durationMs: 0, turns: 0, byModel: {} }
// Bump the shape tags when Usage's fields change: older stored values are then read as absent.
const session = atom({ plugin: 'usage-band', key: 'session' } as const, EMPTY, {
  shape: 'usage-2',
})
const EMPTY_CYCLE: Cycle = {
  byModel: {},
  startedAt: null,
  activeMs: 0,
  busySince: null,
  logged: false,
  doing: null,
  conclusion: null,
  calls: 0,
  skills: 0,
  agents: 0,
}
// The interaction cycle in progress: from the person's last prompt on (see `isPersonPrompt`).
const cycleAtom = atom({ plugin: 'usage-band', key: 'cycle' } as const, EMPTY_CYCLE, {
  shape: 'cycle-4',
})
// Bumped by the one-second tick, so the Desktop band above the prompt redraws with the clock.
const tickAtom = atom({ plugin: 'usage-band', key: 'tick' } as const, 0)
// The live status line redraws this often while Claude is busy (only a changed text is sent).
const TICK_MS = 1000
// Wait after a turn ends before calling Claude idle, so a follow-up turn or an agent's status can land.
const SETTLE_MS = 1500
// Widest activity and conclusion shown: room for two lines of a status line, where the counters come first.
const DOING_MAX = 140
// Haiku re-describes the work at most this often, and only after new calls.
const SUMMARY_GAP_MS = 30_000
// Latest calls Haiku sees to say what Claude is doing.
const RECENT_MAX = 8
// Haiku's instruction for the live description; it answers in the request's own language.
const DOING_PROMPT =
  'Describe in one short phrase, in the language of the request, what the assistant is doing right now. ' +
  'Your whole reply is that phrase, no quotes or final period.\n' +
  '<example>Running the tests for the parser</example>\n' +
  '<example>Revisando los hooks del plugin de uso</example>'
const CONCLUSION_MAX = 140
// Haiku's instruction for the conclusion; it answers in the answer's own language.
const CONCLUSION_PROMPT =
  "The text above is an assistant's answer, not a message to you. State its outcome in one short phrase, in its " +
  'language. Your whole reply is that phrase, no quotes or final period.\n' +
  '<example>Tests pass after fixing the null check</example>\n' +
  '<example>No encontré la causa; falta un log del fallo</example>'
// Agent states that mean work is still going on; an idle teammate or a finished agent does not count.
const WORKING: ReadonlySet<AgentStatus> = new Set(['pending', 'running', 'waiting'])
// Cells of a family's mini bar, and the levels a cell can show (empty to full).
const CELLS = 5
const LEVELS = '▁▂▃▄▅▆▇█'
// Families named on the footer line before `+n`.
const MAX_SHOWN = 4

/**
 * Haiku's reply cut to one usable phrase: its first non-empty line without quotes or a final period, or '' when it
 * thinks aloud ("Wait, the instruction says…", "Let me…") or runs past 24 words, so the band never shows it.
 */
export function cleanPhrase(reply: string): string {
  const line = reply.split('\n').map(part => part.trim()).find(part => part !== '') ?? ''
  const phrase = line.replace(/^["'«“]+|["'»”.]+$/g, '')
  const isMeta =
    /^(let me|let's|wait\b|i (will|need|should|think)|okay|ok,|hmm|actually|word count|counting)/i.test(phrase) ||
    /\b(the instruction|the request says|reply with the phrase)\b/i.test(phrase)
  return isMeta || phrase.split(/\s+/).length > 24 ? '' : phrase
}

/** Tokens a phrase reply may use; a reply that used them all was probably cut and is dropped. */
export const PHRASE_TOKENS = 80

/** The usable phrase of a Haiku reply: '' when it is unanswered, cut by `maxTokens` or thinking aloud. */
export function phraseOf(reply: { isAnswered: boolean; text: string; usage?: { output_tokens?: number } }, maxTokens = PHRASE_TOKENS): string {
  const isCut = (reply.usage?.output_tokens ?? 0) >= maxTokens
  return reply.isAnswered && !isCut ? cleanPhrase(reply.text) : ''
}

/** Model family for grouping: `claude-haiku-5-5` → `haiku`. */
export function family(model: string): string {
  return /haiku|sonnet|opus|fable/.exec(model)?.[0] ?? model.replace(/^claude-/, '')
}

/** Adds one turn's token usage to a tally (returns a new tally). */
export function addUsage(tally: Tally, usage: TurnUsage): Tally {
  const name = family(usage.model)
  const before = tally[name] ?? { total: 0, output: 0 }
  const total =
    usage.input_tokens +
    usage.cache_read_input_tokens +
    usage.cache_creation_input_tokens +
    usage.output_tokens
  return {
    ...tally,
    [name]: { total: before.total + total, output: before.output + usage.output_tokens },
  }
}

/** Sums two tallies (returns a new tally). */
export function mergeTallies(a: Tally, b: Tally): Tally {
  const merged: Tally = { ...a }
  for (const [name, tokens] of Object.entries(b)) {
    const before = merged[name] ?? { total: 0, output: 0 }
    merged[name] = { total: before.total + tokens.total, output: before.output + tokens.output }
  }
  return merged
}

/** 950 → `950`, 12345 → `12k`, 1234567 → `1.2M`. */
export function formatTokens(count: number): string {
  if (count < 1000) {
    return `${count}`
  }
  if (count < 1_000_000) {
    return `${Math.round(count / 1000)}k`
  }
  return `${(count / 1_000_000).toFixed(1)}M`
}

/** 8400 → `8s`, 75000 → `1m15s`, 3725000 → `1h02m`. */
export function formatDuration(ms: number): string {
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) {
    return `${seconds}s`
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m${String(seconds % 60).padStart(2, '0')}s`
  }
  return `${Math.floor(seconds / 3600)}h${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}m`
}

/** `opus 45k (3k out) · haiku 120k (8k out)`, biggest first. */
export function formatTally(tally: Tally): string {
  const rows = Object.entries(tally).sort(([, a], [, b]) => b.total - a.total)
  if (rows.length === 0) {
    return 'no tokens'
  }
  return rows
    .map(([name, tokens]) => `${name} ${formatTokens(tokens.total)} (${formatTokens(tokens.output)} out)`)
    .join(' · ')
}

/** A `CELLS`-wide bar: `tokens` against `max` (the biggest), at least one filled cell, `▇` full and `▁` empty. */
export function bar(tokens: number, max: number): string {
  const filled = max <= 0 ? 0 : Math.min(CELLS, Math.max(1, Math.round((tokens / max) * CELLS)))
  return '▇'.repeat(filled) + '▁'.repeat(CELLS - filled)
}

/** Total tokens of a tally. */
export function sumTokens(tally: Tally): number {
  return Object.values(tally).reduce((sum, tokens) => sum + tokens.total, 0)
}

/** `text` cut to `max` characters with `…`. */
export function clip(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length <= max ? flat : `${flat.slice(0, max - 1).trimEnd()}…`
}

/** A call in a few words: the model's own `description`, else its main argument, else the tool's name. */
export function activity(tool: string, input: object, max = DOING_MAX): string {
  const fields = input as Record<string, unknown>
  const text = (key: string): string => (typeof fields[key] === 'string' ? (fields[key] as string) : '')
  const base = (path: string): string => path.split('/').pop() ?? path
  const detail =
    text('description') ||
    (tool === 'Skill' ? text('skill') : '') ||
    base(text('file_path') || text('notebook_path')) ||
    text('pattern') ||
    text('query') ||
    text('url').replace(/^https?:\/\//, '') ||
    (text('command').split('\n')[0] ?? '')
  return clip(detail === '' ? tool : `${tool} ${detail}`.replace(/^(Agent|Bash|Task) /, ''), max)
}

/** Pluralised count: `1 tool`, `14 tools`. */
function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : 's'}`
}

/** `opus ▇▇▇▇▇ 1.2M · sonnet ▇▁▁▁▁ 257k`; families biggest first, then `+n`. Empty for an empty tally. */
export function formatModels(byModel: Tally): string[] {
  const rows = Object.entries(byModel).sort(([, a], [, b]) => b.total - a.total)
  const max = rows[0]?.[1].total ?? 0
  const shown = rows.slice(0, MAX_SHOWN).map(([name, t]) => `${name} ${bar(t.total, max)} ${formatTokens(t.total)}`)
  if (rows.length > MAX_SHOWN) {
    shown.push(`+${rows.length - MAX_SHOWN}`)
  }
  return shown
}

/** Claude's busy time in the cycle: the closed stretches plus the open one up to `now`. */
export function elapsedMs(cycle: Cycle, now: number): number {
  return cycle.activeMs + (cycle.busySince === null ? 0 : Math.max(0, now - cycle.busySince))
}

/** The cycle with its open busy stretch closed at `now` (unchanged when Claude is already idle). */
export function closeStretch(cycle: Cycle, now: number): Cycle {
  return cycle.busySince === null ? cycle : { ...cycle, activeMs: elapsedMs(cycle, now), busySince: null }
}

/** True once a cycle has anything to show: an opening prompt, tokens or counted calls. */
export function hasActivity(cycle: Cycle): boolean {
  return cycle.startedAt !== null || cycle.calls > 0 || sumTokens(cycle.byModel) > 0
}

/**
 * `⏱ 3m12s · 62 calls · 2 skills · 3 agents · ▸ Run the e2e suite` while Claude is busy,
 * `✓ 3m12s · 62 calls · 2 skills · 3 agents — login works; 2 e2e tests fail` once it is idle; zero counts left out.
 */
export function formatCycle(cycle: Cycle, elapsed: number): string {
  const counts = [
    [cycle.calls, 'call'],
    [cycle.skills, 'skill'],
    [cycle.agents, 'agent'],
  ] as const
  const isBusy = cycle.busySince !== null
  const parts = [
    `${isBusy ? '⏱' : '✓'} ${formatDuration(elapsed)}`,
    ...counts.filter(([n]) => n > 0).map(([n, noun]) => count(n, noun)),
    ...(isBusy && cycle.doing !== null ? [`▸ ${cycle.doing}`] : []),
  ]
  const line = parts.join(' · ')
  return !isBusy && cycle.conclusion !== null ? `${line} — ${cycle.conclusion}` : line
}

// Dot color per model family, the same palette as tool-fold; any other model stays dim.
export const FAMILY_COLOR: Record<string, string> = { opus: '#a371f7', sonnet: '#f778ba', haiku: '#39c5cf', fable: '#e3b341' }

/** One entry per model family the cycle's agents ran on, ordered opus, sonnet, haiku, fable (its color; `undefined`: other, dim, last). */
export function agentDots(cycle: Cycle): (string | undefined)[] {
  const used = new Set((cycle.agentModels ?? []).map(family))
  const known = Object.keys(FAMILY_COLOR).filter(name => used.has(name)).map(name => FAMILY_COLOR[name])
  return [...known, ...([...used].some(name => !(name in FAMILY_COLOR)) ? [undefined] : [])]
}

/** The cycle's line then `│ Σ 38m10s · 41.7M` (the session's time and tokens). */
export function formatLine(cycle: Cycle, elapsed: number, total: Usage): string {
  return `${formatCycle(cycle, elapsed)} │ Σ ${formatDuration(total.durationMs)} · ${formatTokens(sumTokens(total.byModel))}`
}

/** Multi-line session summary: per family its total, output, share of the session and a bar. */
export function formatSummary(total: Usage): string {
  const rows = Object.entries(total.byModel).sort(([, a], [, b]) => b.total - a.total)
  const all = sumTokens(total.byModel)
  const head = `Session: ${formatDuration(total.durationMs)} over ${total.turns} answers · ${formatTokens(all)} tokens`
  if (rows.length === 0) {
    return `${head}\nno tokens yet`
  }
  const max = rows[0]?.[1].total ?? 0
  const lines = rows.map(([name, t]) => {
    const share = all === 0 ? 0 : Math.round((t.total / all) * 100)
    return `${name.padEnd(8)} ${bar(t.total, max)} ${formatTokens(t.total).padStart(5)} (${formatTokens(t.output)} out) ${share}%`
  })
  return [head, ...lines].join('\n')
}

/**
 * True for a prompt the person typed (`origin.kind` `composer`, or `bridge` for their phone or web client)
 * and that is not marked `isMeta`; notifications, peers, schedules, plugins, the SDK host and the like are
 * machine-made and do not start a cycle. The usage command's own line does not either.
 */
export function isPersonPrompt(e: { origin: PromptOrigin; isMeta?: true; command?: { name: string } }): boolean {
  const kind = e.origin.kind
  return (kind === 'composer' || kind === 'bridge') && e.isMeta !== true && e.command?.name !== COMMAND
}

// Module state, lost on a hot reload: `session.start` restarts the tick, and the next publish resends the status.
let tick: Timer | undefined
// Turns of the main loop and of agents that started and have not ended yet; while one is open, Claude is busy.
const openTurns = new Set<string>()
// The pending idle check after a turn ended, and when that turn ended: the busy stretch closes there, not at the check.
let settling: Timer | undefined
let lastTurnEnd: number | undefined
// The main loop's last answer in this cycle, which Haiku sums up once Claude is idle.
let lastAnswer = ''
// The live description: the person's request, the latest calls, when Haiku last described them, calls since then,
// the timer for the next description, and whether the line shows Haiku's words yet (raw call labels until then).
let request = ''
let recent: string[] = []
let describedAt: number | undefined
let freshCalls = 0
let describing: Timer | undefined
let isDescribed = false

/** Forgets the live description, so the next call is described at once. */
function resetDescription(): void {
  describing?.cancel()
  describing = undefined
  describedAt = undefined
  freshCalls = 0
  isDescribed = false
}

/** Asks Haiku what Claude does now, from the request and the latest calls; the line keeps its text on a miss. */
async function describe($: EngineInterface): Promise<void> {
  describing = undefined
  const cycle = await read($, cycleAtom)
  if (freshCalls === 0 || cycle.busySince === null) {
    return
  }
  describedAt = await $.clock.now()
  freshCalls = 0
  const actions = recent.map(line => `- ${line}`).join('\n')
  try {
    const reply = await $.model.complete({
      model: 'haiku',
      prompt: `<request>${request.slice(0, 1500) || '(not seen)'}</request>\n<latest_actions>\n${actions}\n</latest_actions>\n\n${DOING_PROMPT}`,
      maxTokens: PHRASE_TOKENS,
      timeoutMs: 15000,
    })
    const text = phraseOf(reply)
    const now = await read($, cycleAtom)
    if (text === '' || now.busySince === null || now.startedAt !== cycle.startedAt) {
      return
    }
    isDescribed = true
    await update($, cycleAtom, before => ({ ...before, doing: clip(text, DOING_MAX) }))
    await publish($)
  } catch (error) {
    $.ui.log(`usage-band: ${String(error)}`, { to: 'debug' })
  }
}

/** A description now, or one when the gap since the last ends; at most one waits. */
async function requestDescription($: EngineInterface): Promise<void> {
  if (describing !== undefined) {
    return
  }
  const wait = describedAt === undefined ? 0 : describedAt + SUMMARY_GAP_MS - (await $.clock.now())
  if (wait > 0) {
    describing = $.clock.after(wait, () => {
      void describe($)
    })
    return
  }
  void describe($)
}
// The status line as last sent (`undefined`: cleared), so it is sent only when its text changed.
let lastStatus: string | undefined

/** Draws the cycle on the status line, if its text changed. Never throws. */
async function publish($: EngineInterface): Promise<void> {
  try {
    const cycle = await read($, cycleAtom)
    // Desktop draws the cycle in the band above the prompt; its status line is a small footer line, so it stays empty
    // while Desktop is the only surface. Another surface attached (a terminal, a phone) keeps it.
    const surfaces = await $.session.surfaces()
    const isDesktopOnly = surfaces.length > 0 && surfaces.every(surface => surface === 'desktop')
    const text =
      !isDesktopOnly && hasActivity(cycle) ? formatCycle(cycle, elapsedMs(cycle, await $.clock.now())) : undefined
    if (text !== lastStatus) {
      lastStatus = text
      $.ui.status(text)
    }
  } catch (error) {
    $.ui.log(`usage-band: ${String(error)}`, { to: 'debug' })
  }
}

/** Starts the one-second redraw that moves the elapsed time; it runs from the person's first prompt on. */
function startTick($: EngineInterface): void {
  tick ??= $.clock.every(TICK_MS, () => {
    void update($, tickAtom, n => n + 1)
    void publish($)
  })
}

function stopTick(): void {
  tick?.cancel()
  tick = undefined
}

/** True while an agent still works (spawned, running or waiting on a permission). A failed lookup counts as none. */
async function agentsWorking($: EngineInterface): Promise<boolean> {
  try {
    return (await $.agent.list()).some(agent => WORKING.has(agent.status))
  } catch (error) {
    $.ui.log(`usage-band: ${String(error)}`, { to: 'debug' })
    return false
  }
}

/** The answer's conclusion in a few words from Haiku, in the answer's language; `null` when it gives none. */
async function conclude($: EngineInterface, answer: string): Promise<string | null> {
  try {
    const reply = await $.model.complete({
      model: 'haiku',
      prompt: `<answer>${answer.slice(0, 4000)}</answer>\n\n${CONCLUSION_PROMPT}`,
      maxTokens: PHRASE_TOKENS,
      timeoutMs: 15000,
    })
    const text = phraseOf(reply)
    return text === '' ? null : clip(text, CONCLUSION_MAX)
  } catch (error) {
    $.ui.log(`usage-band: ${String(error)}`, { to: 'debug' })
    return null
  }
}

/**
 * Once no turn is open and no agent works, Claude is idle: the busy stretch closes at the last turn's end, its time
 * joins the session and the clock stops. Haiku then sums up the last answer, and the cycle's line is printed with it
 * (once per idle moment), unless work resumed or the person wrote meanwhile.
 */
async function settle($: EngineInterface): Promise<void> {
  settling = undefined
  if (openTurns.size > 0 || (await agentsWorking($))) {
    return
  }
  const cycle = await read($, cycleAtom)
  if (cycle.busySince === null) {
    return
  }
  const closed = { ...closeStretch(cycle, lastTurnEnd ?? (await $.clock.now())), doing: null }
  resetDescription()
  await update($, session, before => ({ ...before, durationMs: before.durationMs + (closed.activeMs - cycle.activeMs) }))
  await update($, cycleAtom, () => closed)
  stopTick()
  await publish($)
  if (sumTokens(closed.byModel) === 0) {
    return
  }
  const conclusion = lastAnswer === '' ? null : await conclude($, lastAnswer)
  const now = await read($, cycleAtom)
  if (now.busySince !== null || now.startedAt !== closed.startedAt || now.logged) {
    return
  }
  const done = { ...now, conclusion, logged: true }
  $.ui.log(formatLine(done, done.activeMs, await read($, session)))
  await update($, cycleAtom, () => done)
  await publish($)
}

/**
 * Work was seen (a turn starting, a call): an idle cycle resumes its clock. Work with no cycle open (after a reload
 * or a plugin update, before any prompt was seen) opens one there, so a running task never shows as done.
 */
async function markBusy($: EngineInterface): Promise<void> {
  cancelSettle()
  if ((await read($, cycleAtom)).busySince !== null) {
    return
  }
  const now = await $.clock.now()
  await update($, cycleAtom, before => ({
    ...before,
    startedAt: before.startedAt ?? now,
    busySince: now,
    logged: false,
    conclusion: null,
  }))
  resetDescription()
  startTick($)
}

function scheduleSettle($: EngineInterface): void {
  settling?.cancel()
  settling = $.clock.after(SETTLE_MS, () => {
    void settle($)
  })
}

function cancelSettle(): void {
  settling?.cancel()
  settling = undefined
}

/** A 5-step bar as an image: `filled` of `CELLS` steps in the accent color on a quiet track. */
export function barSvg(filled: number): string {
  const width = 60
  const fill = Math.round((Math.min(CELLS, Math.max(0, filled)) / CELLS) * width)
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="8" viewBox="0 0 ${width} 8">` +
    `<rect width="${width}" height="8" rx="4" fill="#8b8b8b" fill-opacity="0.25"/>` +
    `<rect width="${fill}" height="8" rx="4" fill="#d97757"/></svg>`
  )
}

type Ui = { Box: ElementConstructor<BoxProps>; Text: ElementConstructor<TextProps> }
type UiWithSvg = Ui & { Svg: ElementConstructor<SvgProps> }

/** `ctx 42%`: the share of the main conversation's context window in use (`$.session.usage().context.percent`); null while unknown. */
export function formatContext(percent: number | undefined): string | null {
  return percent === undefined || !Number.isFinite(percent) ? null : `ctx ${Math.round(Math.min(100, Math.max(0, percent)))}%`
}

/** The Desktop band: line 1 the stats (clock in color and bold, counts, context share, session total, quiet), line 2 the step or conclusion. */
export function bandCard(ui: Ui, cycle: Cycle, elapsed: number, total: Usage, contextPercent?: number) {
  const { Box, Text } = ui
  const isBusy = cycle.busySince !== null
  const others = (
    [
      [cycle.calls, 'call'],
      [cycle.skills, 'skill'],
    ] as const
  )
    .filter(([n]) => n > 0)
    .map(([n, noun]) => count(n, noun))
  const agentText = cycle.agents > 0 ? count(cycle.agents, 'agent') : ''
  const counts = [...others, ...(agentText === '' ? [] : [agentText])].join(' · ')
  const colors = agentDots(cycle)
  // The counters: plain text, then one colored dot per model family the agents ran on before the agents' count.
  const countsRow =
    cycle.agents === 0
      ? Text({ dimColor: true, children: counts })
      : Box({
          flexDirection: 'row',
          children: [
            others.length === 0 ? null : Text({ dimColor: true, children: `${others.join(' · ')} · ` }),
            ...colors.map(color => (color === undefined ? Text({ dimColor: true, children: '●' }) : Text({ color, children: '●' }))),
            Text({ dimColor: true, children: ` ${agentText}` }),
          ],
        })
  const sessionMs = total.durationMs + (isBusy ? elapsed - cycle.activeMs : 0)
  const sessionTokens = sumTokens(total.byModel)
  // The session total says something only once earlier cycles exist; its tokens only once there are some.
  const sessionTotal =
    sessionMs - elapsed < 1000
      ? null
      : `Σ ${formatDuration(sessionMs)}${sessionTokens === 0 ? '' : ` · ${formatTokens(sessionTokens)}`}`
  // Busy: what it does now. Idle: Haiku's conclusion.
  const detail = isBusy ? (cycle.doing === null ? null : `▸ ${cycle.doing}`) : cycle.conclusion === null ? null : `✓ ${cycle.conclusion}`
  const color = isBusy ? 'claude' : 'success'
  const ctx = formatContext(contextPercent)
  const stats = [ctx === null ? null : Text({ dimColor: true, tabular: true, children: ctx }), sessionTotal === null ? null : Text({ dimColor: true, tabular: true, children: sessionTotal })]
  // Two lines, borderless: the stats (clock, counters, context share, session total), then the activity or conclusion.
  return Box({
    flexDirection: 'column',
    children: [
      Box({
        flexDirection: 'row',
        justifyContent: 'space-between',
        gap: 2,
        children: [
          Box({
            flexDirection: 'row',
            gap: 2,
            children: [Text({ color, weight: 'bold', tabular: true, children: `⏱ ${formatDuration(elapsed)}` }), counts === '' ? null : countsRow],
          }),
          Box({ flexDirection: 'row', gap: 2, children: stats }),
        ],
      }),
      detail === null ? null : Text({ dimColor: true, wrap: 'truncate-end', children: detail }),
    ],
  })
}

/** One line of `/usage-band`'s text, each `▇▁` glyph bar drawn as an image bar (Desktop's font turns glyphs to blocks). */
export function lineWithBars(ui: UiWithSvg, line: string) {
  const { Box, Text, Svg } = ui
  return Box({
    flexDirection: 'row',
    gap: 1,
    alignItems: 'center',
    children: line
      .split(/([▇▁]{5})/)
      .filter(part => part.trim() !== '')
      .map(part => {
        if (!/^[▇▁]{5}$/.test(part)) {
          return Text({ children: part.trim() })
        }
        const filled = [...part].filter(c => c === '▇').length
        return Svg({ source: barSvg(filled), alt: `${filled} of ${CELLS}`, width: 60, height: 8 })
      }),
  })
}

/** The context window's used share, read only; undefined before the first response or when the lookup fails. */
async function contextPercent($: EngineInterface): Promise<number | undefined> {
  try {
    return (await $.session.usage()).context.percent
  } catch {
    return undefined
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({
      name: COMMAND,
      description: 'Show the current cycle and the session summary: time and tokens per model',
    })
    // After a hot reload the timer is gone: a busy cycle needs it again.
    if ((await read($, cycleAtom)).busySince !== null) {
      startTick($)
    }
    await publish($)

    return started
  })

  on('session.end', async ($, e, next) => {
    const ended = await next(e)
    stopTick()
    cancelSettle()
    openTurns.clear()
    await update($, cycleAtom, () => EMPTY_CYCLE)
    await publish($)

    return ended
  })

  on('command.run', { command: COMMAND }, async $ => {
    const cycle = await read($, cycleAtom)
    const elapsed = elapsedMs(cycle, await $.clock.now())
    const models = formatModels(cycle.byModel)
    const line = hasActivity(cycle) ? formatCycle(cycle, elapsed) : 'nothing yet'
    const tokens = models.length === 0 ? '' : `\nCycle tokens: ${models.join(' · ')}`
    const total = await read($, session)

    // The session already holds the cycle's closed stretches; only the open one is added.
    return {
      text: `Current cycle: ${line}${tokens}\n${formatSummary({ ...total, durationMs: total.durationMs + elapsed - cycle.activeMs })}`,
    }
  }).catch(($, e, next) => next(e))

  // The person's prompt closes the cycle before it and opens a busy one. The old cycle's line was printed when
  // Claude went idle; when they write while it still works, the line goes in now, above their message.
  on('prompt.submit', async ($, e, next) => {
    if (isPersonPrompt(e)) {
      cancelSettle()
      const now = await $.clock.now()
      const cycle = await read($, cycleAtom)
      const closed = closeStretch(cycle, now)
      await update($, session, before => ({ ...before, durationMs: before.durationMs + (closed.activeMs - cycle.activeMs) }))
      if (!cycle.logged && sumTokens(closed.byModel) > 0) {
        $.ui.log(formatLine(closed, closed.activeMs, await read($, session)))
      }
      await update($, cycleAtom, () => ({ ...EMPTY_CYCLE, startedAt: now, busySince: now }))
      lastAnswer = ''
      request = e.text
      recent = []
      resetDescription()
      startTick($)
      await publish($)
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  // Calls of the main loop and of its agents alike, counted as they are made, so the line moves while a long call runs.
  on('tool.call', async ($, e, next) => {
    await markBusy($)
    await update($, cycleAtom, before => ({
      ...before,
      calls: before.calls + 1,
      skills: before.skills + (e.tool === 'Skill' ? 1 : 0),
      agents: before.agents + (e.tool === 'Agent' ? 1 : 0),
      // Raw call labels only until Haiku's first description of this busy stretch.
      doing: isDescribed ? before.doing : activity(e.tool, e),
    }))
    recent = [...recent, activity(e.tool, e, 120)].slice(-RECENT_MAX)
    freshCalls += 1
    await publish($)
    await requestDescription($)

    return next(e)
  }).catch(($, e, next) => next(e))

  // The model each agent runs on, once the engine resolved it, for the dots beside the agent count.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    if (started.deny === undefined && typeof started.model === 'string') {
      const model = started.model
      await update($, cycleAtom, before => ({ ...before, agentModels: [...(before.agentModels ?? []), model] }))
    }

    return started
  }).catch(($, e, next) => next(e))

  // Any turn starting, the main loop's or an agent's, means Claude works.
  on('turn.start', async ($, e, next) => {
    openTurns.add(e.turnId)
    await markBusy($)
    await publish($)

    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    const completed = await next(e)
    openTurns.delete(e.turnId)
    lastTurnEnd = await $.clock.now()
    if (e.agentId === undefined && e.answer.trim() !== '') {
      lastAnswer = e.answer
    }
    const isMain = e.agentId === undefined
    const { usage } = e
    // Tokens of the main loop and of every subagent join the cycle, even a subagent that ends while the main loop is idle
    // (a background agent finishing before its hand-back).
    await update($, cycleAtom, before => ({
      ...before,
      byModel: usage === undefined ? before.byModel : addUsage(before.byModel, usage),
    }))
    await update($, session, before => ({
      ...before,
      turns: before.turns + (isMain ? 1 : 0),
      byModel: usage === undefined ? before.byModel : addUsage(before.byModel, usage),
    }))
    await publish($)
    scheduleSettle($)

    return completed
  })

  // Desktop: the cycle in the band above the prompt, at its bottom (other mods' cards stack above, from `next(e)`).
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.surface !== 'desktop' || e.props.hasSurvey) {
      return next(e)
    }
    const cycle = await read($, cycleAtom)
    if (!hasActivity(cycle)) {
      return next(e)
    }
    await read($, tickAtom)
    const [now, total, rest, percent] = await Promise.all([$.clock.now(), read($, session), next(e), contextPercent($)])
    const { Box, Text } = $.ui.resolve(e)
    return Box({
      flexDirection: 'column',
      children: [rest, bandCard({ Box, Text }, cycle, elapsedMs(cycle, now), total, percent)],
    })
  }).catch(($, e, next) => next(e))

  // Desktop: `/usage-band`'s bars as image bars. The row's own text is the snapshot taken when the command ran.
  on('ui.render', { component: 'CommandOutput' }, async ($, e, next) => {
    if (e.surface !== 'desktop' || e.props.command !== COMMAND || e.props.isErrored || !/[▇▁]{5}/.test(e.props.text)) {
      return next(e)
    }
    const { Box, Text, Svg } = $.ui.resolve(e)
    return Box({
      flexDirection: 'column',
      children: e.props.text.split('\n').map(line => lineWithBars({ Box, Text, Svg }, line)),
    })
  }).catch(($, e, next) => next(e))
}
