import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { AgentRun, WaitKind, WaitTask } from '../types'
import { commandOf, median } from './agents'

// The background work the main loop launched and still waits on, oldest first. Written from events, read by the card.
// Bump the shape tag when WaitTask's fields change: an older stored list is then read as empty.
const waits = atom({ plugin: 'tool-fold', key: 'waits' } as const, [], { shape: 'waits-1' })
// Clock time the main loop's turn ended (null while a turn runs): the wait shows only while it is idle.
const idleAt = atom({ plugin: 'tool-fold', key: 'idleAt' } as const, null)
// Bumped each second while the card shows, so its elapsed time moves (the render itself never writes).
const waitTick = atom({ plugin: 'tool-fold', key: 'waitTick' } as const, 0)

// Durations remembered per command key across sessions ($.store, a local file).
const REMEMBERED = 10
// A run shorter than this teaches nothing (a command that failed at once).
const MIN_SAMPLE_MS = 1000
// Progress never reaches 100% before the work is done.
const MAX_PROGRESS = 0.95
// Words of a command that name it for the estimate: `cargo bench`, `npm test`.
const KEY_TOKENS = 2
// Statuses a notification states when a task is over.
const ENDED = new Set(['completed', 'failed', 'killed', 'stopped'])

/** Cuts `text` to `max` characters with an ellipsis. */
const clip = (text: string, max: number): string => (text.length <= max ? text : `${text.slice(0, max - 1)}…`)

/** The store key of one work key's remembered durations (one key each: no read-modify race across keys). */
const sampleKey = (key: string): string => `wait-durations:${key}`

/** `cargo bench --release -p x` → `bash:cargo bench`: what the estimate calls the same work. */
export function estimateKey(kind: WaitKind, input: Record<string, unknown>): string {
  const text = (name: string): string => (typeof input[name] === 'string' ? (input[name] as string) : '')
  if (kind === 'shell') {
    return `bash:${commandOf(text('command')).trim().split(/\s+/).slice(0, KEY_TOKENS).join(' ')}`
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
  return clip(text('subagent_type') || text('description') || 'agente', 60)
}

/** Elapsed over the estimate, held under 100% until the work is done; undefined with no estimate. */
export function progressOf(elapsedMs: number, etaMs: number | undefined): number | undefined {
  return etaMs === undefined || etaMs <= 0 ? undefined : Math.min(MAX_PROGRESS, Math.max(0, elapsedMs / etaMs))
}

// Module state, reset by a reload (session.start starts it again): the one-second redraw while the card shows.
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

/** Adds a wait, with the estimate its key remembers. Never throws. */
async function begin($: EngineInterface, id: string, kind: WaitKind, input: Record<string, unknown>): Promise<void> {
  try {
    const key = estimateKey(kind, input)
    const past = await $.store.get(sampleKey(key)).catch(() => undefined)
    const etaMs = median(Array.isArray(past) ? past.filter((item): item is number => typeof item === 'number') : [])
    const startedAt = await $.clock.now()
    const task: WaitTask = { id, kind, key, label: waitLabel(kind, input), ...(kind === 'agent' ? { name: agentName(input) } : {}), startedAt, ...(etaMs === undefined ? {} : { etaMs }) }
    await update($, waits, all => [...all.filter(item => item.id !== id), task])
    await syncTick($)
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
      if (isDone && id !== undefined && took >= MIN_SAMPLE_MS) {
        const past = await $.store.get(sampleKey(task.key)).catch(() => undefined)
        const list = Array.isArray(past) ? past.filter((item): item is number => typeof item === 'number') : []
        await $.store.set(sampleKey(task.key), [...list, took].slice(-REMEMBERED)).catch(() => undefined)
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
export async function onTurn($: EngineInterface, agentId: string | undefined, phase: 'start' | 'end', reason = 'answer'): Promise<void> {
  if (agentId !== undefined) {
    if (phase === 'end') {
      await finish($, agentId, reason === 'answer')
    }
    return
  }
  const now = await $.clock.now()
  await update($, idleAt, () => (phase === 'end' ? now : null))
  await syncTick($)
}

/** Takes the redraw clock up again after a reload, which drops the timer. */
export async function resume($: EngineInterface): Promise<void> {
  await syncTick($)
}

const KIND_NAME: Record<WaitKind, string> = { shell: 'bash', monitor: 'monitor', agent: 'agente' }

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
  // What an agent wait says: the one agent's name, else how many.
  const agentDetail = agents.length === 1 ? `esperando a ${agents[0]?.name ?? agents[0]?.label}` : `esperando a ${agents.length} agentes`
  return list.map(task => {
    // Waiting on an agent: its own card carries the estimate.
    const fraction = task.kind === 'agent' ? undefined : progressOf(Math.max(0, now - task.startedAt), task.etaMs)
    return {
      id: `wait-${task.id}`,
      toolUseId: `wait-${task.id}`,
      type: 'Claude · esperando',
      description: task.label,
      mission: task.label,
      model,
      status: 'running',
      startedAt: task.startedAt,
      current: [{ id: task.id, kind: 'other', label: task.kind === 'agent' ? agentDetail : `${KIND_NAME[task.kind]} · en segundo plano`, status: 'running' }],
      recent: [],
      counts: {},
      ...(fraction === undefined ? {} : { estimate: Math.round(fraction * 100) }),
    }
  })
}
