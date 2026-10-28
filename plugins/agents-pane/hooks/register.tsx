import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgentRun, AgentRunStatus, Step, StepKind } from '../types'

// Keep the list bounded: a long session can spawn hundreds of agents.
const MAX_RUNS = 100
// Bump the shape tag when AgentRun's fields change: an older stored list is then read as empty.
const runs = atom({ plugin: 'agents-pane', key: 'runs' } as const, [], {
  shape: 'runs-3',
})

/** `claude-haiku-5-5` → `haiku-5-5`: shorter on a card. */
export const shortModel = (model: string): string => model.replace(/^claude-/, '')

/** Model family (`haiku`, `sonnet`, `opus`, ...), which picks the model dot's color. */
export const family = (model: string): string =>
  /haiku|sonnet|opus|fable/.exec(model)?.[0] ?? shortModel(model)

/** Dot color per family (the model name stays dim): cheap models read green at a glance. */
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

/**
 * The part of a shell command that says what runs: drops leading `cd <dir> &&` and
 * `VAR=value;` segments and shortens long absolute paths to their last two segments.
 */
export function commandOf(command: string): string {
  const prefix = /^\s*(?:cd\s+\S+|export\s+\w+=\S*|\w+=\S*)\s*(?:&&|;)\s*/
  let line = command.split('\n')[0] ?? ''
  while (prefix.test(line)) {
    line = line.replace(prefix, '')
  }
  return line.replace(/(?:\/[^\s/'"]+){3,}/g, path =>
    path.length <= 24 ? path : `…/${path.split('/').slice(-2).join('/')}`,
  )
}

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
      return { kind: 'run', label: `Run ${clip(commandOf(text('command')), 56)}` }
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

// Agents named on the status line before `+n`.
const STATUS_SHOWN = 3

/**
 * The status line while agents run, the one always-visible spot under the chat in VS Code:
 * `◐ ux-reviewer · sonnet-5-5 ▸ Run npm test · 37s`, or with several
 * `◐ 3 agents · ux-reviewer ▸ Run npm test 37s │ Explore ▸ Search "x" 12s │ +1`.
 * Undefined (clears the line) when none runs.
 */
export function statusText(list: readonly AgentRun[], now: number): string | undefined {
  const running = list.filter(run => run.status === 'running')
  if (running.length === 0) {
    return undefined
  }
  const frame = FRAMES[Math.floor(now / 1000) % FRAMES.length] ?? '◐'
  const name = (run: AgentRun): string => run.type.replace(/^[\w-]+:/, '')
  const doing = (run: AgentRun, max: number): string => {
    const step = run.current[run.current.length - 1]
    return step === undefined ? '' : ` ▸ ${clip(step.label, max)}`
  }
  const elapsed = (run: AgentRun): string => formatDuration(now - run.startedAt)
  const only = running[0]
  if (running.length === 1 && only !== undefined) {
    return `${frame} ${name(only)} · ${shortModel(only.model)}${doing(only, 60)} · ${elapsed(only)}`
  }
  const shown = running.slice(0, STATUS_SHOWN).map(run => `${name(run)}${doing(run, 28)} ${elapsed(run)}`)
  const more = running.length > STATUS_SHOWN ? ` │ +${running.length - STATUS_SHOWN}` : ''
  return `${frame} ${running.length} agents · ${shown.join(' │ ')}${more}`
}

/** Mirrors the running agents on the status line; never throws. */
async function publishStatus($: EngineInterface): Promise<void> {
  try {
    $.ui.status(statusText(await read($, runs), await $.clock.now()))
  } catch (error) {
    $.ui.log(`agents-pane: ${String(error)}`, { to: 'debug' })
  }
}

// Ticks the live elapsed time while any agent runs; module state, restarted by the next spawn.
let tick: { cancel: () => void } | undefined

/** Applies `fn` to the run with this agent id; never throws (a tool call must not fail on it). */
async function patch($: EngineInterface, agentId: string, fn: (run: AgentRun) => AgentRun): Promise<void> {
  try {
    await update($, runs, list => list.map(run => (run.id === agentId ? fn(run) : run)))
    await publishStatus($)
  } catch (error) {
    $.ui.log(`agents-pane: ${String(error)}`, { to: 'debug' })
  }
}

/** Starts the one-second redraw while something runs, stops it once nothing does. */
async function syncTick($: EngineInterface): Promise<void> {
  await publishStatus($)
  const isRunning = (await read($, runs)).some(run => run.status === 'running')
  if (isRunning && tick === undefined) {
    tick = $.clock.every(1000, () => {
      $.ui.invalidate('ui.render')
      void publishStatus($)
    })
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
      counts: { ...run.counts, [step.kind]: (run.counts[step.kind] ?? 0) + 1 },
      failures: (run.failures ?? 0) + (status === 'failed' ? 1 : 0),
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
      const failures = run.failures ?? 0
      const summary = summarize(run.counts) + (failures > 0 ? ` · ${failures} failed` : '')
      const chip = (
        <Text dimColor>
          <Text color={FAMILY_COLOR[family(run.model)] ?? 'subtle'}>●</Text> {shortModel(run.model)}
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

      // Running: two lines, the live detail is on the status line; the card keeps its place in the chat.
      const step = run.current[run.current.length - 1]
      return (
        // Desktop and VS Code already frame a plugin's tree; the terminal gets a quiet border of its own.
        <Box
          key={run.id}
          flexDirection="column"
          {...(e.surface === 'terminal' ? { borderStyle: 'round', borderDimColor: true, paddingX: 1 } : {})}
        >
          {header}
          <Text dimColor wrap="truncate">
            {'└ '}
            {step === undefined ? (
              summary === '' ? 'Starting…' : summary
            ) : (
              <Text>
                <Text color="claude">{frame}</Text> {step.label}
              </Text>
            )}
          </Text>
        </Box>
      )
    }

    return <Box flexDirection="column">{cards.map(card)}</Box>
  })
}
