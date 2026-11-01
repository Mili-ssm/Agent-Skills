import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { AgentRun, EtaSource, TurnCard, WaitKind, WaitTask } from '../types'
import { commandOf, describeStep, isAgentRunning, isBackgroundAgent, retitleDock } from './agents'
import {
  REESTIMATE_GAP_MS,
  TURN_SAMPLES_KEY,
  WAIT_SAMPLES_KEY,
  askMinutes,
  loadSamples,
  recordSample,
  similarMedian,
  similarRuns,
  sourceOfAsk,
  statedDuration,
  LINGER_MS,
  MAX_PERCENT,
  OVERDUE_GRACE_MS,
} from './estimates'

// The background work the main loop launched and still waits on, oldest first. Written from events, read by the card.
// Bump the shape tag when WaitTask's fields change: an older stored list is then read as empty.
const waits = atom({ plugin: 'tool-fold', key: 'waits' } as const, [], { shape: 'waits-2' })
// Clock time the main loop's turn ended (null while a turn runs): only the card's label depends on it.
const idleAt = atom({ plugin: 'tool-fold', key: 'idleAt' } as const, null)
// Waits that ended with `completed`, kept for LINGER_MS so their card shows full and green. Drawn by the clock, swept on the tick.
const lingering = atom({ plugin: 'tool-fold', key: 'lingeringWaits' } as const, [])

// The main turn the main card follows (null while idle). Written from events, read by the card.
const turnCard = atom({ plugin: 'tool-fold', key: 'turnCard' } as const, null)

type Lingered = WaitTask & { endedAt: number }
// Bumped each second while the card shows, so its elapsed time moves (the render itself never writes).
const waitTick = atom({ plugin: 'tool-fold', key: 'waitTick' } as const, 0)

export { statedDuration }
// Progress never reaches 100% before the work is done.
const MAX_PROGRESS = MAX_PERCENT / 100
// Characters of a command's first line that name it for the estimate.
const KEY_CHARS = 80
// A guessed duration outside this range is Haiku misreading the question.
const MAX_GUESS_MIN = 24 * 60
// An owned wait outlives its estimate by at most this much (or twice the estimate, if longer) before it is dropped.
const STALE_EXTRA_MS = 10 * 60_000
// Statuses a notification states when a task is over.
const ENDED = new Set(['completed', 'failed', 'killed', 'stopped'])

/** Cuts `text` to `max` characters with an ellipsis. */
const clip = (text: string, max: number): string => (text.length <= max ? text : `${text.slice(0, max - 1)}…`)

/**
 * Haiku's reply cut to one usable phrase: its first non-empty line without quotes or a final period, or '' when it
 * thinks aloud or runs past 24 words (the same filter as usage-band's and plan-progress's, copied: mods cannot import each other).
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

type Reply = { isAnswered: boolean; text: string; usage?: { output_tokens?: number } }

/** True when the reply used all of `maxTokens`: it was probably cut mid-word. */
const isCut = (reply: Reply, maxTokens: number): boolean => (reply.usage?.output_tokens ?? 0) >= maxTokens

/** The usable phrase of a Haiku reply: '' when it is unanswered, cut by `maxTokens` or thinking aloud. */
export function phraseOf(reply: Reply, maxTokens = PHRASE_TOKENS): string {
  return reply.isAnswered && !isCut(reply, maxTokens) ? cleanPhrase(reply.text) : ''
}

/** Minutes in a reply: a bare number (`12`, `3,5`) as milliseconds; undefined for anything else, prose included. */
export function minutesOf(reply: string): number | undefined {
  const found = /^\s*(\d+(?:[.,]\d+)?)\s*$/.exec(reply)?.[1]
  const minutes = found === undefined ? Number.NaN : Number.parseFloat(found.replace(',', '.'))
  return Number.isFinite(minutes) && minutes > 0 && minutes <= MAX_GUESS_MIN ? Math.round(minutes * 60000) : undefined
}

/** `cargo bench -p x` (or its description) → `bash:run the bench`: what the estimate calls the same work. */
export function estimateKey(kind: WaitKind, input: Record<string, unknown>): string {
  const text = (name: string): string => (typeof input[name] === 'string' ? (input[name] as string) : '')
  if (kind === 'shell') {
    const line = (commandOf(text('command')).split('\n')[0] ?? '').trim().replace(/\s+/g, ' ')
    return `bash:${(text('description').trim().replace(/\s+/g, ' ') || line).toLowerCase().slice(0, KEY_CHARS)}`
  }
  if (kind === 'monitor') {
    return `monitor:${text('description').trim().toLowerCase()}`
  }
  return `agent:${text('subagent_type') || text('description').trim().toLowerCase()}`
}

/** What the card says the main agent waits on: the model's description, else the command's first line. */
export function waitLabel(kind: WaitKind, input: Record<string, unknown>): string {
  const text = (name: string): string => (typeof input[name] === 'string' ? (input[name] as string).trim() : '')
  const command = kind === 'agent' ? '' : commandOf(text('command'))
  return clip((text('description') || command.split('\n')[0] || text('subagent_type') || 'tarea').trim(), 120)
}

/** The agent a wait names: its type (`Explore`), else its description. */
const agentName = (input: Record<string, unknown>): string => {
  const text = (name: string): string => (typeof input[name] === 'string' ? (input[name] as string).trim() : '')
  return clip((text('subagent_type').replace(/^[\w-]+:/, '') || text('description') || 'agente').trim(), 60)
}

/** Elapsed over the estimate, held under 100% until the work is done; undefined with no estimate. */
export function progressOf(elapsedMs: number, etaMs: number | undefined): number | undefined {
  return etaMs === undefined || etaMs <= 0 ? undefined : Math.min(MAX_PROGRESS, Math.max(0, elapsedMs / etaMs))
}

// Module state, reset by a reload (session.start starts it again): the one-second redraw while the card shows.
let turnStartedAt = 0
let ticker: { cancel: () => void } | undefined

/** Runs the clock while anything is waited on; stops it otherwise. */
async function syncTick($: EngineInterface): Promise<void> {
  const all = await read($, waits)
  const isShown = all.length > 0 || (await read($, lingering)).length > 0 || (await read($, turnCard)) !== null
  if (isShown && ticker === undefined) {
    ticker = $.clock.every(1000, () => {
      void update($, waitTick, n => n + 1)
      void sweep($).catch(error => $.ui.log(`tool-fold: wait sweep: ${String(error)}`, { to: 'debug' }))
    })
  } else if (!isShown && ticker !== undefined) {
    ticker.cancel()
    ticker = undefined
  }
}

// Asks Haiku, once per wait, for what it could not read off the call: a plain description.
const GUESS_HEAD = 'Una tarea en segundo plano de un agente de programación ejecuta lo de arriba. Responde con esta línea, sin texto extra:\n'
const LABEL_LINE = 'descripcion: una frase corta que quepa en una línea, en español llano: qué hace (no cómo)\n'
const LABEL_EXAMPLE = 'descripcion: Ejecuta el benchmark del parser\n'

/** Gives waits Claude's own estimate (its message), which beats whatever else they have. */
async function setEta($: EngineInterface, ids: readonly string[], etaMs: number, source: EtaSource): Promise<void> {
  await update($, waits, all => all.map(task => (ids.includes(task.id) ? { ...task, etaMs, etaSource: source } : task)))
}

/** Fills in a wait's label with one Haiku call. Fire and forget: a miss leaves the wait as it was. */
async function guess($: EngineInterface, id: string, subject: string): Promise<void> {
  const reply = await $.model.complete({
    model: 'haiku',
    prompt: `<tarea>${subject.slice(0, 1500)}</tarea>\n\n${GUESS_HEAD}${LABEL_LINE}<example>\n${LABEL_EXAMPLE}</example>`,
    maxTokens: PHRASE_TOKENS,
    timeoutMs: 15000,
  })
  if (!reply.isAnswered || isCut(reply, PHRASE_TOKENS)) {
    return
  }
  const line = reply.text.split('\n').map(part => part.trim()).find(part => part.toLowerCase().startsWith('descripcion:'))
  const label = cleanPhrase(line?.slice('descripcion:'.length) ?? '')
  if (label !== '') {
    await update($, waits, all => all.map(task => (task.id === id ? { ...task, label: clip(label, 120), isLabelGuessed: true } : task)))
  }
}

// Waits with a Haiku ask in flight: one at a time per wait.
const asking = new Set<string>()

/**
 * Haiku's minutes for a wait (text and similar runs together), at launch or, with `again`, when it ran past the
 * estimate. Its answer is the estimate unless Claude's own message already set one. Fire and forget.
 */
async function askWait($: EngineInterface, task: WaitTask, statedMs: number | undefined, again?: { elapsedMs: number; previousMs: number }): Promise<void> {
  if (asking.has(task.id)) {
    return
  }
  asking.add(task.id)
  try {
    const samples = await loadSamples($, WAIT_SAMPLES_KEY)
    const similar = similarRuns(samples, task.label)
    const text = task.subject === undefined || task.subject === task.label ? task.label : `${task.label}\n${task.subject}`
    const etaMs = await askMinutes($, { text, ...(statedMs === undefined ? {} : { statedMs }), similar, ...(again === undefined ? {} : { again }) })
    if (etaMs !== undefined) {
      const etaSource = sourceOfAsk(statedMs, similar)
      await update($, waits, all =>
        all.map(item =>
          item.id !== task.id || (again === undefined && item.etaSource === 'message')
            ? item
            : { ...item, etaMs, etaSource: again === undefined ? etaSource : (item.etaSource ?? etaSource) },
        ),
      )
    }
  } finally {
    asking.delete(task.id)
  }
}

// Claude's last message, read once per turn end for a duration it states for the running work.
const MESSAGE_ETA_PROMPT =
  'El texto de arriba es un mensaje de un agente de programación que deja trabajo en marcha en segundo plano; no es un mensaje para ti. ' +
  'Si dice cuánto tardará, responde ese tiempo en minutos como un solo número (el punto medio de un rango). ' +
  'Si no lo dice, responde none. Tu respuesta entera es el número o none.\n' +
  '<example>unas 2–3 horas → 150</example>\n<example>tarda ~10 min → 10</example>\n<example>ya está listo → none</example>'

/** Reads the duration Claude's message states for the waits started in its turn. Fire and forget. */
async function messageEta($: EngineInterface, answer: string, since: number): Promise<void> {
  const ids = (await read($, waits)).filter(task => task.kind !== 'agent' && task.owner === undefined && task.startedAt >= since).map(task => task.id)
  if (ids.length === 0) {
    return
  }
  const reply = await $.model.complete({ model: 'haiku', prompt: `<mensaje>${answer.slice(-3000)}</mensaje>\n\n${MESSAGE_ETA_PROMPT}`, maxTokens: 20, timeoutMs: 15000 })
  const etaMs = reply.isAnswered ? minutesOf(reply.text) : undefined
  if (etaMs !== undefined) {
    await setEta($, ids, etaMs, 'message')
  }
}

/** Adds a wait, with the estimate its key remembers. Never throws. */
async function begin($: EngineInterface, id: string, kind: WaitKind, input: Record<string, unknown>, owner?: string): Promise<void> {
  try {
    const key = estimateKey(kind, input)
    const label = waitLabel(kind, input)
    const samples = await loadSamples($, WAIT_SAMPLES_KEY)
    const description = typeof input.description === 'string' ? input.description.trim() : ''
    const command = typeof input.command === 'string' ? input.command : ''
    // A duration written in the call (a `sleep`, "Wait 5 minutes") beats every estimate; only a sleep is read off a command.
    const stated = (/\bsleep\s/.test(command) ? statedDuration(command) : undefined) ?? (kind === 'agent' ? undefined : statedDuration(description))
    // Until Haiku answers, the best deterministic value: stated, else the median of similar runs, else none.
    const etaMs = stated ?? similarMedian(samples, label)
    const startedAt = await $.clock.now()
    const subject = command !== '' ? command : description
    const isAsked = kind !== 'agent' && subject.trim() !== ''
    const task: WaitTask = {
      id,
      kind,
      key,
      label,
      ...(kind === 'agent' ? { name: agentName(input) } : {}),
      ...(owner === undefined ? {} : { owner }),
      ...(isAsked ? { subject: clip(subject, 500), askedAt: startedAt } : {}),
      startedAt,
      ...(etaMs === undefined ? {} : { etaMs, etaSource: stated === undefined ? ('similar' as const) : ('stated' as const) }),
    }
    await update($, waits, all => [...all.filter(item => item.id !== id), task])
    await syncTick($)
    // A shell with no description asks Haiku for a label, and every shell or monitor for its minutes, after the wait is on the card.
    if (kind === 'shell' && description === '' && subject.trim() !== '') {
      void guess($, id, subject).catch(error => $.ui.log(`tool-fold: wait guess: ${String(error)}`, { to: 'debug' }))
    }
    if (isAsked) {
      void askWait($, task, stated).catch(error => $.ui.log(`tool-fold: wait estimate: ${String(error)}`, { to: 'debug' }))
    }
  } catch (error) {
    $.ui.log(`tool-fold: wait: ${String(error)}`, { to: 'debug' })
  }
}

/** Removes a wait (all of them when `id` is undefined) and, for work that ended well, remembers how long it took. Never throws. */
async function finish($: EngineInterface, id: string | undefined, isDone: boolean): Promise<void> {
  try {
    const ended = (await read($, waits)).filter(item => id === undefined || item.id === id)
    if (ended.length === 0) {
      return
    }
    await update($, waits, all => all.filter(item => !ended.some(gone => gone.id === item.id)))
    const now = await $.clock.now()
    if (isDone) {
      await update($, lingering, all => [...all.filter(item => !ended.some(gone => gone.id === item.id)), ...ended.map(task => ({ ...task, endedAt: now }))])
    }
    for (const task of ended) {
      const took = now - task.startedAt
      if (isDone && id !== undefined) {
        await recordSample($, WAIT_SAMPLES_KEY, task.label, took, now)
      }
    }
    await syncTick($)
  } catch (error) {
    $.ui.log(`tool-fold: wait: ${String(error)}`, { to: 'debug' })
  }
}

/** Removes waits that are over by inference (no end was seen), teaching nothing: no sample is recorded. Never throws. */
async function drop($: EngineInterface, ids: readonly string[]): Promise<void> {
  try {
    if (ids.length === 0) {
      return
    }
    await update($, waits, all => all.filter(item => !ids.includes(item.id)))
    await syncTick($)
  } catch (error) {
    $.ui.log(`tool-fold: wait: ${String(error)}`, { to: 'debug' })
  }
}

/** A wait that outlived its estimate by too long: twice the estimate, or ten minutes more if that is longer. */
export const isStale = (task: Pick<WaitTask, 'startedAt' | 'etaMs'>, now: number): boolean => {
  const eta = task.etaMs ?? 0
  return now - task.startedAt > Math.max(2 * eta, eta + STALE_EXTRA_MS)
}

/**
 * Each clock tick (never from render): drops an ended agent's owned wait that outlived its estimate (safety net b),
 * and asks Haiku again for a wait that ran past its estimate, at most once per 30 s.
 */
async function sweep($: EngineInterface): Promise<void> {
  const now = await $.clock.now()
  const all = await read($, waits)
  if ((await read($, lingering)).some(item => now - item.endedAt >= LINGER_MS)) {
    await update($, lingering, list => list.filter(item => now - item.endedAt < LINGER_MS))
    await syncTick($)
    await retitleDock($).catch(() => undefined)
  }
  const turn = (await read($, turnCard)) as TurnCard | null
  if (turn?.endedAt !== undefined && now - turn.endedAt >= LINGER_MS) {
    await update($, turnCard, () => null)
    await syncTick($)
    await retitleDock($).catch(() => undefined)
  }
  const stale: string[] = []
  for (const task of all) {
    if (task.owner !== undefined && isStale(task, now) && !(await isAgentRunning($, task.owner))) {
      stale.push(task.id)
    }
  }
  await drop($, stale)
  for (const task of all) {
    const etaMs = task.etaMs
    if (stale.includes(task.id) || etaMs === undefined || task.askedAt === undefined || asking.has(task.id)) {
      continue
    }
    const elapsedMs = now - task.startedAt
    if (elapsedMs >= etaMs && now - task.askedAt >= REESTIMATE_GAP_MS) {
      await update($, waits, list => list.map(item => (item.id === task.id ? { ...item, askedAt: now } : item)))
      void askWait($, task, undefined, { elapsedMs, previousMs: etaMs }).catch(error => $.ui.log(`tool-fold: wait re-estimate: ${String(error)}`, { to: 'debug' }))
    }
  }
}

/** A tag's text from a notification's envelope: `<status>completed</status>` → `completed`. */
const tagOf = (text: string, tag: string): string | undefined =>
  new RegExp(`<${tag}>\\s*([^<]*?)\\s*</${tag}>`).exec(text)?.[1] || undefined

/** A launch the main loop made: a shell (also one moved there by its timeout or ctrl+b) or a monitor answers its task id; a stop ends its wait. */
export async function onToolCall(
  $: EngineInterface,
  e: { tool: string; agentId?: string },
  result: { deny?: string; isError?: boolean; result?: unknown },
): Promise<void> {
  if (result.deny !== undefined || result.isError === true) {
    return
  }
  const input = e as Record<string, unknown>
  const record = (typeof result.result === 'object' && result.result !== null ? result.result : {}) as Record<string, unknown>
  if (e.tool === 'Bash' && typeof record.backgroundTaskId === 'string') {
    // A subagent's command that dies with its final response sends no notification: there is nothing to wait for.
    // A background agent's own turns go on after its Agent call returned: its command is a wait all the same.
    if (e.agentId !== undefined && record.backgroundEndsWithFinalResponse === true && !(await isBackgroundAgent($, e.agentId))) {
      return
    }
    await begin($, record.backgroundTaskId, 'shell', input, e.agentId)
  } else if (e.tool === 'Monitor' && typeof record.taskId === 'string') {
    await begin($, record.taskId, 'monitor', input, e.agentId)
  } else if (e.tool === 'TaskStop') {
    const stopped = input.task_id ?? input.shell_id
    // A subagent stops only a task it names.
    if (e.agentId === undefined || typeof stopped === 'string') {
      await finish($, typeof stopped === 'string' ? stopped : undefined, false)
    }
  }
}

/** A background agent of the main loop (one spawned by another agent is that agent's wait). */
export async function onAgentSpawn(
  $: EngineInterface,
  e: { background: boolean; parentAgentId?: string; description: string; subagentType: string },
  started: { deny?: string; agentId?: string },
): Promise<void> {
  if (started.deny === undefined && started.agentId !== undefined && e.background && e.parentAgentId === undefined) {
    await begin($, started.agentId, 'agent', { description: e.description, subagent_type: e.subagentType })
  }
}

/**
 * A notification names its task and how it ended. A monitor's event line states no end: its wait goes on. One
 * that ended without naming the task clears every wait (the card is a hint, never stuck).
 */
export async function onNotification($: EngineInterface, text: string): Promise<void> {
  const status = tagOf(text, 'status')
  const id = tagOf(text, 'task-id')
  const known = (await read($, waits)).find(item => item.id === id)
  // A subagent's command named by the main loop's notification: over, but the time it took is not the wait's own (safety net a).
  if (known?.owner !== undefined && (status === undefined ? known.kind !== 'monitor' : ENDED.has(status))) {
    await drop($, [known.id])
    return
  }
  const isEnd = status === undefined ? known?.kind !== 'monitor' : ENDED.has(status)
  // A named task this card does not track (an agent of a subagent) changes nothing.
  if (isEnd && (id === undefined || known !== undefined)) {
    await finish($, id, status === undefined || status === 'completed')
  }
}

/** Haiku's minutes for the main turn (the prompt and similar past turns together). Fire and forget: a miss leaves the deterministic value. */
async function askTurn($: EngineInterface, prompt: string, startedAt: number): Promise<void> {
  const similar = similarRuns(await loadSamples($, TURN_SAMPLES_KEY), prompt)
  const etaMs = await askMinutes($, { text: prompt, similar })
  if (etaMs !== undefined) {
    const etaSource = sourceOfAsk(undefined, similar)
    await update($, turnCard, (turn: TurnCard | null) => (turn === null || turn.startedAt !== startedAt ? turn : { ...turn, etaMs, etaSource }))
  }
}

/** A main-loop call starts: the main card's detail line names it. Never throws. */
export async function onMainCall($: EngineInterface, tool: string, input: Record<string, unknown>): Promise<void> {
  const step = describeStep(tool, input)
  const call = clip(step.detail ?? step.label, 120)
  await update($, turnCard, (turn: TurnCard | null) => (turn === null || turn.endedAt !== undefined ? turn : { ...turn, call }))
}

/** The main loop's turn starts (it is not waiting any more) or ends (it is, if work remains); a background agent's end ends its wait. */
export async function onTurn(
  $: EngineInterface,
  agentId: string | undefined,
  phase: 'start' | 'end',
  reason = 'answer',
  answer = '',
  prompt = '',
): Promise<void> {
  if (agentId !== undefined) {
    if (phase === 'end') {
      await finish($, agentId, reason === 'answer')
    }
    return
  }
  const now = await $.clock.now()
  await update($, idleAt, () => (phase === 'end' ? now : null))
  if (phase === 'start') {
    turnStartedAt = now
    const text = prompt.replace(/\s+/g, ' ').trim()
    const similarEta = similarMedian(await loadSamples($, TURN_SAMPLES_KEY), text)
    const card: TurnCard = {
      startedAt: now,
      prompt: clip(text, 200),
      ...(similarEta === undefined ? {} : { etaMs: similarEta, etaSource: 'similar' as const }),
    }
    await update($, turnCard, () => card)
    if (text !== '') {
      void askTurn($, clip(text, 1500), now).catch(error => $.ui.log(`tool-fold: turn estimate: ${String(error)}`, { to: 'debug' }))
    }
  } else {
    const turn = (await read($, turnCard)) as TurnCard | null
    const isBackground = (await read($, waits)).some(task => task.owner === undefined)
    if (turn !== null) {
      if (reason === 'answer') {
        await recordSample($, TURN_SAMPLES_KEY, turn.prompt, now - turn.startedAt, now)
      }
      // Background work takes the card over (blue); a turn that ended otherwise than by answering leaves at once.
      await update($, turnCard, () => (reason === 'answer' && !isBackground ? { ...turn, endedAt: now } : null))
    }
    if (answer.trim() !== '') {
      void messageEta($, answer, turnStartedAt).catch(error => $.ui.log(`tool-fold: message estimate: ${String(error)}`, { to: 'debug' }))
    }
  }
  await syncTick($)
}


/**
 * A subagent that parked on its background command is woken by the command's end (`backgroundWakesOwner`): the
 * message that starts its turn is the task notification. The command it names is over; a notification naming
 * none leaves its waits to the safety net.
 */
export async function onAgentWoken($: EngineInterface, agentId: string, text: string): Promise<void> {
  const id = tagOf(text, 'task-id')
  const status = tagOf(text, 'status')
  if (id !== undefined && (status === undefined || ENDED.has(status))) {
    const mine = (await read($, waits)).find(item => item.id === id && item.owner === agentId)
    if (mine !== undefined) {
      await finish($, id, status === undefined || status === 'completed')
    }
  }
}

/** True while a background process launched by this subagent is still waited on. */
export async function hasOwnedWaits($: EngineInterface, agentId: string): Promise<boolean> {
  return (await read($, waits)).some(task => task.owner === agentId)
}

/** Takes the redraw clock up again after a reload, which drops the timer. */
export async function resume($: EngineInterface): Promise<void> {
  await syncTick($)
}

/** The main card while a main turn runs (orange) or just ended (green, lingering); empty with no turn. Never writes. */
async function turnRuns($: EngineInterface, now: number, model: string): Promise<AgentRun[]> {
  const turn = (await read($, turnCard)) as TurnCard | null
  if (turn === null || (turn.endedAt !== undefined && now - turn.endedAt >= LINGER_MS)) {
    return []
  }
  const mission = turn.call ?? (turn.prompt === '' ? 'trabajando' : turn.prompt)
  const base = { id: 'wait-main', toolUseId: 'wait-main', type: 'Claude · trabajando', description: mission, mission, model, startedAt: turn.startedAt, current: [], recent: [], counts: {} }
  if (turn.endedAt !== undefined) {
    return [{ ...base, status: 'done', durationMs: turn.endedAt - turn.startedAt, isLingering: true, isWorking: true }]
  }
  const fraction = progressOf(Math.max(0, now - turn.startedAt), turn.etaMs)
  return [
    {
      ...base,
      status: 'running',
      isWorking: true,
      ...(fraction === undefined ? { isTrackOnly: true } : { estimate: Math.round(fraction * 100) }),
      ...(turn.etaSource === undefined || fraction === undefined ? {} : { etaSource: turn.etaSource }),
      ...(turn.etaMs !== undefined && now - turn.startedAt > turn.etaMs + OVERDUE_GRACE_MS ? { isOverdue: true } : {}),
    },
  ]
}

/**
 * The main agent's wait as runs the agent card draws (label "Claude · esperando" idle, "Claude · en segundo plano" while a turn runs, the wait as its mission and live
 * call, the estimate as its percentage): empty when nothing is waited on; labelled by whether the main loop is idle. Never writes.
 */
export async function waitingRuns($: EngineInterface): Promise<AgentRun[]> {
  const [everything, idle] = await Promise.all([read($, waits), read($, idleAt)])
  // A subagent's waits are its own card's (see `agentWaitRuns`).
  const list = everything.filter(task => task.owner === undefined)
  await read($, waitTick)
  const now = await $.clock.now()
  const model = await $.session.model().catch(() => '')
  if (list.length === 0) {
    // The last wait just completed: its card stays full and green until LINGER_MS passes.
    const done = (await read($, lingering) as Lingered[]).filter(task => task.owner === undefined && now - task.endedAt < LINGER_MS)
    const first = done[0]
    if (first === undefined) {
      return turnRuns($, now, model)
    }
    const mission = done.length === 1 ? first.label : `${done.length} tareas en segundo plano`
    return [
      {
        id: 'wait-main',
        toolUseId: 'wait-main',
        type: 'Claude · esperando',
        description: mission,
        mission,
        model,
        status: 'done',
        startedAt: Math.min(...done.map(task => task.startedAt)),
        durationMs: Math.max(...done.map(task => task.endedAt)) - Math.min(...done.map(task => task.startedAt)),
        current: [],
        recent: [],
        counts: {},
        isLingering: true,
      },
    ]
  }
  const agents = list.filter(task => task.kind === 'agent')
  const procs = list.filter(task => task.kind !== 'agent')
  // What the wait says: the agents (one by name, else how many), then the processes the same way.
  const agentPart = agents.length === 0 ? '' : agents.length === 1 ? `a ${agents[0]?.name ?? agents[0]?.label}` : `a ${agents.length} agentes`
  // The label is the mission; the detail only says what kind of process runs, never the mission's words again.
  const procPart = procs.length === 0 ? '' : procs.length === 1 ? `${procs[0]?.kind === 'monitor' ? 'monitor' : 'bash'} en segundo plano` : `${procs.length} procesos en segundo plano`
  const detail = agentPart === '' ? procPart.replace(' en segundo plano', ' · en segundo plano') : `esperando ${agentPart}${procPart === '' ? '' : ` · ${procPart}`}`
  // The process that ends the wait (latest estimated end) gives the estimate; agents carry their own cards' estimates.
  const endOf = (task: WaitTask): number => task.startedAt + (task.etaMs ?? 0)
  const driver = procs.reduce<WaitTask | undefined>((best, task) => (best === undefined || endOf(task) > endOf(best) ? task : best), undefined)
  const earliest = Math.min(...list.map(task => task.startedAt))
  const elapsed = Math.max(0, now - (driver?.startedAt ?? earliest))
  const fraction = driver === undefined ? undefined : progressOf(elapsed, driver.etaMs)
  const isOverdue = fraction !== undefined && driver?.etaMs !== undefined && elapsed > driver.etaMs + OVERDUE_GRACE_MS
  const mission = driver?.label ?? agents[0]?.name ?? agents[0]?.label ?? detail
  return [
    {
      id: 'wait-main',
      toolUseId: 'wait-main',
      // Same card and place while a turn runs: only the label changes, so nothing jumps.
      type: idle === null ? 'Claude · en segundo plano' : 'Claude · esperando',
      description: mission,
      mission,
      model,
      status: 'running',
      startedAt: earliest,
      current: [{ id: 'wait-main', kind: 'other', label: detail, status: 'running' }],
      recent: [],
      counts: {},
      ...(fraction === undefined ? {} : { estimate: Math.round(fraction * 100) }),
      ...(driver?.etaSource === undefined ? {} : { etaSource: driver.etaSource }),
      ...(isOverdue ? { isOverdue } : {}),
      // No estimate at all: the empty track keeps the card's shape (a wait on agents has none, their own cards have it).
      ...(fraction === undefined ? { isTrackOnly: true } : {}),
    },
  ]
}

/**
 * The cards of subagents whose turn ended while a background process they launched still runs: the agent's own
 * name and model, in the waiting state, with the process's estimate. Empty for a still-running agent (its own card
 * shows). Never writes.
 */
export async function agentWaitRuns($: EngineInterface, agents: readonly AgentRun[]): Promise<AgentRun[]> {
  const owned = (await read($, waits)).filter(task => task.owner !== undefined)
  const ended = (await read($, lingering) as Lingered[]).filter(task => task.owner !== undefined)
  if (owned.length === 0 && ended.length === 0) {
    return []
  }
  await read($, waitTick)
  const now = await $.clock.now()
  const cards: AgentRun[] = []
  for (const run of agents) {
    const procs = owned.filter(task => task.owner === run.id)
    if (run.status === 'running') {
      continue
    }
    if (procs.length === 0) {
      // Its last background process completed: the waiting card stays full and green for a moment.
      const done = ended.filter(task => task.owner === run.id && now - task.endedAt < LINGER_MS)
      if (done.length > 0) {
        const { estimate: _e, etaMs: _m, etaSource: _s, todo: _t, isOpenEnded: _o, ...own } = run
        cards.push({
          ...own,
          id: `wait-agent-${run.id}`,
          status: 'done',
          durationMs: Math.max(...done.map(task => task.endedAt)) - run.startedAt,
          current: [],
          recent: [],
          counts: {},
          isLingering: true,
        })
      }
      continue
    }
    const endOf = (task: WaitTask): number => task.startedAt + (task.etaMs ?? 0)
    const driver = procs.reduce((best, task) => (endOf(task) > endOf(best) ? task : best))
    const elapsed = Math.max(0, now - run.startedAt)
    const fraction = progressOf(Math.max(0, now - driver.startedAt), driver.etaMs)
    const detail = procs.length === 1 ? `esperando · ${driver.label} en segundo plano` : `esperando · ${procs.length} procesos`
    const { estimate: _estimate, etaMs: _etaMs, etaSource: _etaSource, todo: _todo, isOpenEnded: _open, ...own } = run
    cards.push({
      ...own,
      id: `wait-agent-${run.id}`,
      status: 'running',
      startedAt: run.startedAt,
      durationMs: elapsed,
      current: [{ id: driver.id, kind: 'other', label: detail, status: 'running' }],
      recent: [],
      counts: {},
      ...(fraction === undefined ? { isTrackOnly: true } : { estimate: Math.round(fraction * 100) }),
      ...(driver.etaSource === undefined ? {} : { etaSource: driver.etaSource }),
      ...(fraction !== undefined && driver.etaMs !== undefined && now - driver.startedAt > driver.etaMs + OVERDUE_GRACE_MS ? { isOverdue: true } : {}),
    })
  }
  return cards
}

/** For `/agents-debug`: what the wait card would draw from, so a missing card can be explained. */
export async function waitDebug($: EngineInterface): Promise<string[]> {
  const [list, idle] = await Promise.all([read($, waits), read($, idleAt)])
  return [
    `main loop idle since: ${idle === null ? 'not idle' : new Date(idle).toISOString().slice(11, 19)}`,
    `waits: ${list.length === 0 ? 'none' : list.map(task => `${task.kind} ${task.id}`).join('; ')}`,
  ]
}
