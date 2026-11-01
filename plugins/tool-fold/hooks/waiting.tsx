import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { AgentRun, EtaSource, WaitKind, WaitSample, WaitTask } from '../types'
import { commandOf } from './agents'
import { WAIT_SAMPLES_KEY, askSimilar, loadSamples, recordSample, similarMedian } from './estimates'

// The background work the main loop launched and still waits on, oldest first. Written from events, read by the card.
// Bump the shape tag when WaitTask's fields change: an older stored list is then read as empty.
const waits = atom({ plugin: 'tool-fold', key: 'waits' } as const, [], { shape: 'waits-2' })
// Clock time the main loop's turn ended (null while a turn runs): the wait shows only while it is idle.
const idleAt = atom({ plugin: 'tool-fold', key: 'idleAt' } as const, null)
// Bumped each second while the card shows, so its elapsed time moves (the render itself never writes).
const waitTick = atom({ plugin: 'tool-fold', key: 'waitTick' } as const, 0)

// Stronger sources replace weaker ones: Claude knows its data, past runs measured, a guess is last.
const RANK: Record<EtaSource, number> = { guess: 1, similar: 2, message: 3 }
// Progress never reaches 100% before the work is done.
const MAX_PROGRESS = 0.95
// Characters of a command's first line that name it for the estimate.
const KEY_CHARS = 80
// A guessed duration outside this range is Haiku misreading the question.
const MAX_GUESS_MIN = 24 * 60
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

/** Runs the clock while something is waited on and the main loop is idle; stops it otherwise. */
async function syncTick($: EngineInterface): Promise<void> {
  const isShown = (await read($, waits)).length > 0 && (await read($, idleAt)) !== null
  if (isShown && ticker === undefined) {
    ticker = $.clock.every(1000, () => {
      void update($, waitTick, n => n + 1)
    })
  } else if (!isShown && ticker !== undefined) {
    ticker.cancel()
    ticker = undefined
  }
}

// Asks Haiku, once per wait, for what it could not read off the call: a plain description and a rough duration.
const GUESS_HEAD = 'Una tarea en segundo plano de un agente de programación ejecuta lo de arriba. Responde con estas líneas, sin texto extra:\n'
const LABEL_LINE = 'descripcion: una frase corta que quepa en una línea, en español llano: qué hace (no cómo)\n'
const ETA_LINE = 'minutos: cuántos minutos tardará aproximadamente, solo un número (por ejemplo 3 o 0.5)\n'
const LABEL_EXAMPLE = 'descripcion: Ejecuta el benchmark del parser\n'
const ETA_EXAMPLE = 'minutos: 4\n'

/** Gives a wait an estimate unless it already has one from an equal or stronger source. */
async function setEta($: EngineInterface, ids: readonly string[], etaMs: number, source: EtaSource): Promise<void> {
  await update($, waits, all =>
    all.map(task =>
      !ids.includes(task.id) || (task.etaSource !== undefined && RANK[task.etaSource] >= RANK[source]) ? task : { ...task, etaMs, etaSource: source },
    ),
  )
}

/** Fills in a wait's label and/or estimate with one Haiku call. Fire and forget: a miss leaves the wait as it was. */
async function guess($: EngineInterface, id: string, subject: string, isLabelNeeded: boolean, isEtaNeeded: boolean): Promise<void> {
  const reply = await $.model.complete({
    model: 'haiku',
    prompt: `<tarea>${subject.slice(0, 1500)}</tarea>\n\n${GUESS_HEAD}${isLabelNeeded ? LABEL_LINE : ''}${isEtaNeeded ? ETA_LINE : ''}<example>\n${isLabelNeeded ? LABEL_EXAMPLE : ''}${isEtaNeeded ? ETA_EXAMPLE : ''}</example>`,
    maxTokens: PHRASE_TOKENS,
    timeoutMs: 15000,
  })
  if (!reply.isAnswered) {
    return
  }
  const lines = reply.text.split('\n').map(part => part.trim()).filter(part => part !== '')
  const valueOf = (name: string): string => lines.find(line => line.toLowerCase().startsWith(`${name}:`))?.slice(name.length + 1) ?? ''
  const label = isLabelNeeded && !isCut(reply, PHRASE_TOKENS) ? cleanPhrase(valueOf('descripcion')) : ''
  const etaMs = isEtaNeeded ? minutesOf(valueOf('minutos')) : undefined
  if (label === '' && etaMs === undefined) {
    return
  }
  if (label !== '') {
    await update($, waits, all => all.map(task => (task.id === id ? { ...task, label: clip(label, 120), isLabelGuessed: true } : task)))
  }
  if (etaMs !== undefined) {
    await setEta($, [id], etaMs, 'guess')
  }
}

/** Asks Haiku which of the latest summaries are the same kind of work as this one; sets the median of their durations. */
async function pickSimilar($: EngineInterface, id: string, subject: string, samples: readonly WaitSample[]): Promise<void> {
  const etaMs = await askSimilar($, subject, samples)
  if (etaMs !== undefined) {
    await setEta($, [id], etaMs, 'similar')
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
  const ids = (await read($, waits)).filter(task => task.kind !== 'agent' && task.startedAt >= since).map(task => task.id)
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
async function begin($: EngineInterface, id: string, kind: WaitKind, input: Record<string, unknown>): Promise<void> {
  try {
    const key = estimateKey(kind, input)
    const label = waitLabel(kind, input)
    const samples = await loadSamples($, WAIT_SAMPLES_KEY)
    const etaMs = similarMedian(samples, label)
    const startedAt = await $.clock.now()
    const task: WaitTask = {
      id,
      kind,
      key,
      label,
      ...(kind === 'agent' ? { name: agentName(input) } : {}),
      startedAt,
      ...(etaMs === undefined ? {} : { etaMs, etaSource: 'similar' as const }),
    }
    await update($, waits, all => [...all.filter(item => item.id !== id), task])
    await syncTick($)
    // A shell or monitor with no description or no history asks Haiku, after the wait is on the card.
    const description = typeof input.description === 'string' ? input.description.trim() : ''
    const isLabelNeeded = kind === 'shell' && description === ''
    const isEtaNeeded = kind !== 'agent' && etaMs === undefined
    const subject = typeof input.command === 'string' ? input.command : description
    if ((isLabelNeeded || isEtaNeeded) && subject.trim() !== '') {
      void guess($, id, description === '' ? subject : `${description}\n${subject}`, isLabelNeeded, isEtaNeeded).catch(error =>
        $.ui.log(`tool-fold: wait guess: ${String(error)}`, { to: 'debug' }),
      )
    }
    // No similar summary: Haiku may still see one among the latest.
    if (kind !== 'agent' && etaMs === undefined && samples.length > 0) {
      void pickSimilar($, id, label, samples).catch(error => $.ui.log(`tool-fold: wait pick: ${String(error)}`, { to: 'debug' }))
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

/** A tag's text from a notification's envelope: `<status>completed</status>` → `completed`. */
const tagOf = (text: string, tag: string): string | undefined =>
  new RegExp(`<${tag}>\\s*([^<]*?)\\s*</${tag}>`).exec(text)?.[1] || undefined

/** A launch the main loop made: a shell (also one moved there by its timeout or ctrl+b) or a monitor answers its task id; a stop ends its wait. */
export async function onToolCall(
  $: EngineInterface,
  e: { tool: string; agentId?: string },
  result: { deny?: string; isError?: boolean; result?: unknown },
): Promise<void> {
  if (e.agentId !== undefined || result.deny !== undefined || result.isError === true) {
    return
  }
  const input = e as Record<string, unknown>
  const record = (typeof result.result === 'object' && result.result !== null ? result.result : {}) as Record<string, unknown>
  if (e.tool === 'Bash' && typeof record.backgroundTaskId === 'string') {
    await begin($, record.backgroundTaskId, 'shell', input)
  } else if (e.tool === 'Monitor' && typeof record.taskId === 'string') {
    await begin($, record.taskId, 'monitor', input)
  } else if (e.tool === 'TaskStop') {
    const stopped = input.task_id ?? input.shell_id
    await finish($, typeof stopped === 'string' ? stopped : undefined, false)
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
  const isEnd = status === undefined ? known?.kind !== 'monitor' : ENDED.has(status)
  // A named task this card does not track (an agent of a subagent) changes nothing.
  if (isEnd && (id === undefined || known !== undefined)) {
    await finish($, id, status === undefined || status === 'completed')
  }
}

/** The main loop's turn starts (it is not waiting any more) or ends (it is, if work remains); a background agent's end ends its wait. */
export async function onTurn(
  $: EngineInterface,
  agentId: string | undefined,
  phase: 'start' | 'end',
  reason = 'answer',
  answer = '',
): Promise<void> {
  if (agentId !== undefined) {
    if (phase === 'end') {
      await finish($, agentId, reason === 'answer')
    }
    return
  }
  const now = await $.clock.now()
  await update($, idleAt, () => (phase === 'end' ? now : null))
  await syncTick($)
  if (phase === 'start') {
    turnStartedAt = now
  } else if (answer.trim() !== '') {
    void messageEta($, answer, turnStartedAt).catch(error => $.ui.log(`tool-fold: message estimate: ${String(error)}`, { to: 'debug' }))
  }
}

/** Takes the redraw clock up again after a reload, which drops the timer. */
export async function resume($: EngineInterface): Promise<void> {
  await syncTick($)
}

/**
 * The main agent's wait as runs the agent card draws (label "Claude · esperando", the wait as its mission and live
 * call, the estimate as its percentage): empty while a turn runs or nothing is waited on. Never writes.
 */
export async function waitingRuns($: EngineInterface): Promise<AgentRun[]> {
  const [list, idle] = await Promise.all([read($, waits), read($, idleAt)])
  if (list.length === 0 || idle === null) {
    return []
  }
  await read($, waitTick)
  const now = await $.clock.now()
  const model = await $.session.model().catch(() => '')
  const agents = list.filter(task => task.kind === 'agent')
  const procs = list.filter(task => task.kind !== 'agent')
  // What the wait says: the agents (one by name, else how many), then the processes the same way.
  const agentPart = agents.length === 0 ? '' : agents.length === 1 ? `a ${agents[0]?.name ?? agents[0]?.label}` : `a ${agents.length} agentes`
  const procPart = procs.length === 0 ? '' : procs.length === 1 ? `${procs[0]?.label} en segundo plano` : `${procs.length} procesos`
  const detail = agentPart === '' ? `esperando ${procPart}` : `esperando ${agentPart}${procPart === '' ? '' : ` · ${procPart}`}`
  // The process that ends the wait (latest estimated end) gives the estimate; agents carry their own cards' estimates.
  const endOf = (task: WaitTask): number => task.startedAt + (task.etaMs ?? 0)
  const driver = procs.reduce<WaitTask | undefined>((best, task) => (best === undefined || endOf(task) > endOf(best) ? task : best), undefined)
  const earliest = Math.min(...list.map(task => task.startedAt))
  const elapsed = Math.max(0, now - (driver?.startedAt ?? earliest))
  const fraction = driver === undefined ? undefined : progressOf(elapsed, driver.etaMs)
  const isOverdue = fraction !== undefined && driver?.etaMs !== undefined && elapsed >= driver.etaMs
  const mission = driver?.label ?? agents[0]?.name ?? agents[0]?.label ?? detail
  return [
    {
      id: 'wait-main',
      toolUseId: 'wait-main',
      type: 'Claude · esperando',
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

/** For `/agents-debug`: what the wait card would draw from, so a missing card can be explained. */
export async function waitDebug($: EngineInterface): Promise<string[]> {
  const [list, idle] = await Promise.all([read($, waits), read($, idleAt)])
  return [
    `main loop idle since: ${idle === null ? 'not idle' : new Date(idle).toISOString().slice(11, 19)}`,
    `waits: ${list.length === 0 ? 'none' : list.map(task => `${task.kind} ${task.id}`).join('; ')}`,
  ]
}
