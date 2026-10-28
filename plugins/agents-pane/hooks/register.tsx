import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgentRun, AgentRunStatus, Step, StepKind } from '../types'

// Keep the list bounded: a long session can spawn hundreds of agents.
const MAX_RUNS = 100
// Finished calls a running card keeps on screen under the current ones.
const RECENT = 2
// Bump the shape tag when AgentRun's fields change: an older stored list is then read as empty.
const runs = atom({ plugin: 'agents-pane', key: 'runs' } as const, [], {
  shape: 'runs-2',
})

/** `claude-haiku-5-5` → `haiku-5-5`: shorter on a card. */
export const shortModel = (model: string): string => model.replace(/^claude-/, '')

/** Model family (`haiku`, `sonnet`, `opus`, ...), which picks the model chip's color. */
export const family = (model: string): string =>
  /haiku|sonnet|opus|fable/.exec(model)?.[0] ?? shortModel(model)

/** Chip color per family: cheap models read green at a glance. */
const FAMILY_COLOR: Record<string, string> = {
  haiku: 'success',
  sonnet: 'suggestion',
  opus: 'merged',
  fable: 'warning',
}

/** 1234 → `1s`, 75000 → `1m 15s`, 3725000 → `1h 02m` (Codex's compact elapsed). */
export const formatDuration = (ms: number): string => {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) {
    return `${seconds}s`
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`
  }
  return `${Math.floor(seconds / 3600)}h ${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}m`
}

/** Cuts `text` to `max` characters with an ellipsis. */
const clip = (text: string, max: number): string =>
  text.length <= max ? text : `${text.slice(0, max - 1)}…`

/** Last path segment: `src/app/main.py` → `main.py`. */
const base = (path: string): string => path.split('/').filter(Boolean).pop() ?? path

/** What a tool call does and how a card names it, from its name and input. */
export function describeStep(tool: string, input: Record<string, unknown>): { kind: StepKind; label: string } {
  const text = (key: string): string => (typeof input[key] === 'string' ? (input[key] as string) : '')
  const where = text('path') === '' ? '' : ` in ${base(text('path'))}/`
  switch (tool) {
    case 'Read':
      return { kind: 'read', label: `Read ${base(text('file_path'))}` }
    case 'Glob':
      return { kind: 'list', label: `List ${clip(text('pattern'), 40)}${where}` }
    case 'Grep':
      return { kind: 'search', label: `Search ${clip(`"${text('pattern')}"`, 40)}${where}` }
    case 'Edit':
    case 'Write':
    case 'NotebookEdit':
      return { kind: 'edit', label: `${tool === 'Write' ? 'Write' : 'Edit'} ${base(text('file_path') || text('notebook_path'))}` }
    case 'Bash':
      return { kind: 'run', label: `Run ${clip(text('command').split('\n')[0] ?? '', 48)}` }
    case 'WebSearch':
      return { kind: 'web', label: `Web search ${clip(`"${text('query')}"`, 40)}` }
    case 'WebFetch':
      return { kind: 'web', label: `Fetch ${clip(text('url').replace(/^https?:\/\//, ''), 40)}` }
    case 'Agent':
      return { kind: 'agent', label: `Agent ${clip(text('description'), 40)}` }
    default:
      return { kind: 'other', label: tool.replace(/^mcp__/, '').replace(/__/g, ' ') }
  }
}

const plural = (count: number, word: string): string => `${count} ${word}${count === 1 ? '' : 's'}`

/** `Explored 3 files, 2 searches · Edited 1 file · Ran 2 commands`, as Codex groups calls. */
export function summarize(counts: AgentRun['counts']): string {
  const n = (kind: StepKind): number => counts[kind] ?? 0
  const parts: string[] = []
  const explored = [
    n('read') > 0 ? plural(n('read'), 'file') : '',
    n('list') > 0 ? plural(n('list'), 'listing') : '',
    n('search') > 0 ? plural(n('search'), 'search').replace('searchs', 'searches') : '',
  ].filter(Boolean)
  if (explored.length > 0) {
    parts.push(`Explored ${explored.join(', ')}`)
  }
  if (n('edit') > 0) {
    parts.push(`Edited ${plural(n('edit'), 'file')}`)
  }
  if (n('run') > 0) {
    parts.push(`Ran ${plural(n('run'), 'command')}`)
  }
  if (n('web') > 0) {
    parts.push(`Browsed ${plural(n('web'), 'page')}`)
  }
  if (n('agent') > 0) {
    parts.push(`Spawned ${plural(n('agent'), 'agent')}`)
  }
  if (n('other') > 0) {
    parts.push(`Used ${plural(n('other'), 'tool')}`)
  }
  return parts.join(' · ')
}

/** Spinner frames for surfaces without Svg; the frame follows the clock. */
const FRAMES = ['◐', '◓', '◑', '◒']

/** A spinning arc, animated by SMIL inside the sandboxed frame (no script). */
const SPINNER_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="12" height="12">' +
  '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-opacity=".25" stroke-width="2"/>' +
  '<path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="#d97757" stroke-width="2" stroke-linecap="round">' +
  '<animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="0.9s" repeatCount="indefinite"/>' +
  '</path></svg>'

/** Status word and bullet color of a finished or running card. */
const OUTCOME: Record<AgentRunStatus, { word: string; color: string }> = {
  running: { word: 'Working', color: 'claude' },
  done: { word: 'Done', color: 'success' },
  failed: { word: 'Failed', color: 'error' },
  aborted: { word: 'Stopped', color: 'warning' },
}

// Ticks the live elapsed time while any agent runs; module state, restarted by the next spawn.
let tick: { cancel: () => void } | undefined

/** Applies `fn` to the run with this agent id; never throws (a tool call must not fail on it). */
async function patch($: EngineInterface, agentId: string, fn: (run: AgentRun) => AgentRun): Promise<void> {
  try {
    await update($, runs, list => list.map(run => (run.id === agentId ? fn(run) : run)))
  } catch (error) {
    $.ui.log(`agents-pane: ${String(error)}`, { to: 'debug' })
  }
}

/** Starts the one-second redraw while something runs, stops it once nothing does. */
async function syncTick($: EngineInterface): Promise<void> {
  const isRunning = (await read($, runs)).some(run => run.status === 'running')
  if (isRunning && tick === undefined) {
    tick = $.clock.every(1000, () => $.ui.invalidate('ui.render'))
  } else if (!isRunning && tick !== undefined) {
    tick.cancel()
    tick = undefined
  }
}

export const register: Register = on => {
  // Record each spawn after the engine resolved its model and id.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    if (started.deny !== undefined || started.agentId === undefined) {
      return started
    }
    const id = started.agentId
    const record = async (): Promise<void> => {
      const startedAt = await $.clock.now()
      await update($, runs, list => {
        // A resumed agent keeps its card: mark it running again.
        if (list.some(run => run.id === id)) {
          return list.map(run => (run.id === id ? { ...run, status: 'running', startedAt } : run))
        }
        const run: AgentRun = {
          id,
          toolUseId: e.tool_use_id,
          type: e.subagentType,
          description: e.description,
          model: started.model,
          status: 'running',
          startedAt,
          current: [],
          recent: [],
          counts: {},
        }
        return [...list, run].slice(-MAX_RUNS)
      })
      await syncTick($)
    }
    // A failure here costs the card, never the spawn.
    await record().catch(error => $.ui.log(`agents-pane: ${String(error)}`, { to: 'debug' }))

    return started
  }).catch(($, e, next) => next(e))

  // A subagent's tool call: show it as current while it runs, then fold it into the summary.
  on('tool.call', async ($, e, next) => {
    const agentId = e.agentId
    const isTracked = await read($, runs)
      .then(list => list.some(run => run.id === agentId))
      .catch(() => false)
    if (agentId === undefined || !isTracked) {
      return next(e)
    }
    const step: Step = { id: e.tool_use_id, ...describeStep(e.tool, e as Record<string, unknown>), status: 'running' }
    await patch($, agentId, run => ({ ...run, current: [...run.current, step] }))

    const result = await next(e)
    const status: Step['status'] = result.deny !== undefined || result.isError === true ? 'failed' : 'done'
    await patch($, agentId, run => ({
      ...run,
      current: run.current.filter(item => item.id !== step.id),
      recent: [...run.recent, { ...step, status }].slice(-RECENT),
      counts: { ...run.counts, [step.kind]: (run.counts[step.kind] ?? 0) + 1 },
    }))

    return result
    // The card is a view: a failing hook lets the call go on as if the mod were not there.
  }).catch(($, e, next) => next(e))

  // A subagent's turn ended: store its outcome and duration.
  on('turn.complete', async ($, e, next) => {
    const agentId = e.agentId
    if (agentId !== undefined) {
      const status: AgentRunStatus =
        e.reason === 'answer' ? 'done' : e.reason === 'aborted' ? 'aborted' : 'failed'
      await patch($, agentId, run => ({ ...run, status, durationMs: e.durationMs, current: [] }))
      await syncTick($)
    }

    return next(e)
  })

  // The Agent call's own row in the transcript becomes the card: live while it runs, one line after.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (e.props.tool !== 'Agent' || e.props.isExpanded === true) {
      return next(e)
    }
    const cards = (await read($, runs)).filter(run => run.toolUseId === e.props.tool_use_id)
    if (cards.length === 0) {
      return next(e)
    }
    const { Box, Text } = $.ui.resolve(e)
    const now = await $.clock.now()
    const frame = FRAMES[Math.floor(now / 250) % FRAMES.length] ?? '•'

    /** The bullet: an animated arc where the surface draws Svg, a turning glyph on the terminal. */
    const bullet = (run: AgentRun) => {
      const outcome = OUTCOME[run.status]
      if (run.status !== 'running') {
        return <Text color={outcome.color} bold>•</Text>
      }
      if (e.surface === 'terminal') {
        return <Text color={outcome.color}>{frame}</Text>
      }
      const { Svg } = $.ui.resolve(e)
      return <Svg source={SPINNER_SVG} alt="running" width={12} height={12} isInteractive />
    }

    const card = (run: AgentRun) => {
      const isRunning = run.status === 'running'
      const elapsed = run.durationMs ?? now - run.startedAt
      const summary = summarize(run.counts)
      const chip = (
        <Text color={FAMILY_COLOR[family(run.model)] ?? 'subtle'} weight="medium">
          {shortModel(run.model)}
        </Text>
      )
      const header = (
        <Box key={`${run.id}-head`} flexDirection="row" gap={1}>
          {bullet(run)}
          <Text weight="bold" dimColor={!isRunning && run.status === 'done'}>
            {run.type.replace(/^[\w-]+:/, '')}
          </Text>
          {chip}
          <Text dimColor wrap="truncate">{run.description}</Text>
          <Text dimColor tabular>
            {isRunning ? `${OUTCOME.running.word} ${formatDuration(elapsed)}` : formatDuration(elapsed)}
          </Text>
        </Box>
      )

      // Finished: one line, the header plus what it did (Codex's collapsed group).
      if (!isRunning) {
        return (
          <Box key={run.id} flexDirection="column">
            {header}
            {summary === '' ? null : (
              <Text dimColor>
                {'  └ '}
                {run.status === 'done' ? summary : `${OUTCOME[run.status].word} · ${summary}`}
              </Text>
            )}
          </Box>
        )
      }

      // Running: the summary so far, the last finished calls dim, the live ones bright.
      const rows = [...run.recent, ...run.current]
      return (
        <Box key={run.id} flexDirection="column" borderStyle="round" borderColor="claude" paddingX={1}>
          {header}
          <Text dimColor>
            {'└ '}
            {summary === '' ? 'Starting…' : summary}
          </Text>
          {rows.map(step => (
            <Text
              key={step.id}
              dimColor={step.status === 'done'}
              color={step.status === 'failed' ? 'error' : undefined}
              wrap="truncate"
            >
              {'  '}
              {step.status === 'running' ? `${frame} ` : step.status === 'failed' ? '✗ ' : '✓ '}
              {step.label}
            </Text>
          ))}
        </Box>
      )
    }

    return <Box flexDirection="column">{cards.map(card)}</Box>
  })
}
