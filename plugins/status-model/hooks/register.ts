import type { Register } from 'claude-code'

/** The subagent the line reports on. */
type Run = {
  type: string
  model: string
  /** `running` until its turn ends, then the outcome glyph. */
  status: 'running' | 'done' | 'failed' | 'aborted'
  durationMs?: number
}

const GLYPH: Record<Run['status'], string> = {
  running: '…',
  done: '✓',
  failed: '✗',
  aborted: '■',
}

/** `claude-haiku-5-5` → `haiku-5-5`; `agent-skills:researcher` → `researcher`. */
const short = (name: string): string => name.replace(/^claude-/, '').replace(/^[\w-]+:/, '')

/** 12345 → `12s`, 75000 → `1m15s`. */
const formatDuration = (ms: number): string => {
  const seconds = Math.round(ms / 1000)
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m${seconds % 60}s`
}

/** What the line is drawn from. */
type Line = {
  mainModel: string | undefined
  /** Agents whose turn has not ended yet, by agent id. */
  running: Map<string, Run>
  last: Run | undefined
}

/** `opus-5-5 │ 2 running │ last: researcher → haiku-5-5 ✓ 12s`; undefined clears the entry. */
export function statusText(line: Line): string | undefined {
  const parts: string[] = []
  if (line.mainModel !== undefined) {
    parts.push(short(line.mainModel))
  }
  if (line.running.size > 0) {
    parts.push(`${line.running.size} running`)
  }
  const last = line.last
  if (last !== undefined) {
    const took = last.durationMs === undefined ? '' : ` ${formatDuration(last.durationMs)}`
    parts.push(`last: ${short(last.type)} → ${short(last.model)} ${GLYPH[last.status]}${took}`)
  }
  return parts.length === 0 ? undefined : parts.join(' │ ')
}

export const register: Register = on => {
  // Module state: a hot reload resets it, and the next event redraws the line.
  const line: Line = { mainModel: undefined, running: new Map(), last: undefined }

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    line.mainModel = await $.session.model()
    $.ui.status(statusText(line))

    return started
  })

  // A new subagent: it becomes the "last" one and counts as running.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    if (started.deny === undefined && started.agentId !== undefined) {
      const run: Run = { type: e.subagentType, model: started.model, status: 'running' }
      line.running.set(started.agentId, run)
      line.last = run
      $.ui.status(statusText(line))
    }

    return started
  })

  on('turn.complete', async ($, e, next) => {
    const agentId = e.agentId
    if (agentId === undefined) {
      // Main loop: the model that actually served the turn (catches switches and fallbacks).
      line.mainModel = e.usage?.model ?? line.mainModel
    } else {
      const run = line.running.get(agentId)
      if (run !== undefined) {
        line.running.delete(agentId)
        const status = e.reason === 'answer' ? 'done' : e.reason === 'aborted' ? 'aborted' : 'failed'
        line.last = { ...run, status, durationMs: e.durationMs }
      }
    }
    $.ui.status(statusText(line))

    return next(e)
  })
}
