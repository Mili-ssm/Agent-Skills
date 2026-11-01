import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { WaitKind, WaitTask } from '../types'
import { commandOf, formatDuration, median } from './agents'

// The background work the main loop launched and still waits on, oldest first. Written from events, read by the card.
// Bump the shape tag when WaitTask's fields change: an older stored list is then read as empty.
const waits = atom({ plugin: 'tool-fold', key: 'waits' } as const, [], { shape: 'waits-1' })
// Clock time the main loop's turn ended (null while a turn runs): the card shows only while it is idle.
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

/** `~45s`, `~3m`, `~1h 05m`: a rough duration, rounded. */
export function approx(ms: number): string {
  const seconds = Math.max(1, Math.round(ms / 1000))
  if (seconds < 60) {
    return `~${seconds}s`
  }
  const minutes = Math.round(seconds / 60)
  return minutes < 60 ? `~${minutes}m` : `~${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`
}

/** Elapsed over the estimate, held under 100% until the work is done; undefined with no estimate. */
export function progressOf(elapsedMs: number, etaMs: number | undefined): number | undefined {
  return etaMs === undefined || etaMs <= 0 ? undefined : Math.min(MAX_PROGRESS, Math.max(0, elapsedMs / etaMs))
}

/** The task type the card's detail line names. */
const KIND_NAME: Record<WaitKind, string> = { shell: 'bash', monitor: 'monitor', agent: 'agente' }

/** The progress line as SVG, 2px high: a 1px faded track under a 2px fill for `fraction`, left to right (undefined: track only). */
export function progressSvg(fraction: number | undefined, width: number, color: string): string {
  const fill = fraction === undefined ? 0 : width * fraction
  const bar = fill > 0 ? `<rect class="done" x="0" y="0" width="${fill.toFixed(2)}" height="2" rx="1" fill="${color}"/>` : ''
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="2" viewBox="0 0 ${width} 2" preserveAspectRatio="none">` +
    `<rect class="track" x="0" y="0.5" width="${width}" height="1" fill="${color}" fill-opacity="0.45"/>${bar}</svg>`
  )
}

/** `▰▰▰▱▱▱▱▱▱▱` for a fraction over `width` cells; no estimate draws only the empty cells. */
export function glyphLine(fraction: number | undefined, width: number): string {
  const filled = fraction === undefined ? 0 : Math.round(fraction * width)
  return '▰'.repeat(filled) + '▱'.repeat(width - filled)
}

// The band's render event, as `$.ui.resolve` takes it.
type BandEvent = Parameters<EngineInterface['ui']['resolve']>[0]

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
    const task: WaitTask = { id, kind, key, label: waitLabel(kind, input), startedAt, ...(etaMs === undefined ? {} : { etaMs }) }
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

/**
 * Puts the waiting card above `rest` (the band's cards below it), or returns `rest` when nothing is waited on. The
 * band is shared: the agents' cards and usage-band's stack beneath. Never writes.
 */
export async function stackCard($: EngineInterface, e: BandEvent, rest: unknown) {
  const [list, idle] = await Promise.all([read($, waits), read($, idleAt)])
  const task = list[0]
  if ((e.props as unknown as { hasSurvey?: boolean }).hasSurvey || task === undefined || idle === null) {
    return rest as never
  }
  await read($, waitTick)
  const { Box, Text } = $.ui.resolve(e)
  const now = await $.clock.now()
  const elapsed = Math.max(0, now - task.startedAt)
  const fraction = progressOf(elapsed, task.etaMs)
  const time = task.etaMs === undefined ? formatDuration(elapsed) : `${formatDuration(elapsed)} / ${approx(task.etaMs)}`
  const more = list.length > 1 ? ` · +${list.length - 1} más` : ''
  const columns = (e.props as unknown as { bodyColumns: number }).bodyColumns
  const room = Math.max(12, Math.min(80, columns - time.length - 16))
  const title = (
    <Box gap={1}>
      <Text weight="bold">Esperando</Text>
      <Text wrap="truncate-end">{clip(task.label, room)}</Text>
      <Text dimColor>{time}</Text>
    </Box>
  )
  const detail = <Text dimColor wrap="truncate-end">{`${KIND_NAME[task.kind]} · en segundo plano${more}`}</Text>
  if (e.surface === 'terminal') {
    return (
      <Box flexDirection="column">
        {title}
        <Text dimColor={fraction === undefined} color={fraction === undefined ? undefined : 'claude'}>
          {glyphLine(fraction, 10)}
        </Text>
        {detail}
        {rest as never}
      </Box>
    )
  }
  const { Svg } = $.ui.resolve(e)
  return (
    <Box flexDirection="column">
      {title}
      <Svg
        source={progressSvg(fraction, 4000, '#d97757')}
        alt={fraction === undefined ? 'Waiting for background work' : `${Math.round(fraction * 100)}% of the estimated time`}
        height={2}
      />
      {detail}
      {rest as never}
    </Box>
  )
}
