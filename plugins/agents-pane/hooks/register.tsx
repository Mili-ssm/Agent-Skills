import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { AgentRun, AgentRunStatus } from '../types'

// Pane id, also the slash command that reopens it (`/agents` is taken by Claude Code).
const PANE = 'agents-pane'
const TITLE = 'Agents'
// Keep the list bounded: a long session can spawn hundreds of agents.
const MAX_RUNS = 100
// Bump the shape tag when AgentRun's fields change: an older stored list is then read as empty.
const runs = atom({ plugin: 'agents-pane', key: 'runs' } as const, [], {
  shape: 'runs-1',
})

/** `claude-haiku-5-5` → `haiku-5-5`: shorter in a narrow pane. */
export const shortModel = (model: string): string => model.replace(/^claude-/, '')

/** Model family (`haiku`, `sonnet`, `opus`, ...) for the offload tally. */
export const family = (model: string): string =>
  /haiku|sonnet|opus|fable/.exec(model)?.[0] ?? shortModel(model)

/** 1234 → `1s`, 75000 → `1m15s`. */
export const formatDuration = (ms: number): string => {
  const seconds = Math.round(ms / 1000)
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m${seconds % 60}s`
}

/** Status glyph for a row. */
const GLYPH: Record<AgentRunStatus, string> = {
  running: '…',
  done: '✓',
  failed: '✗',
  aborted: '■',
}

export const register: Register = on => {
  // Auto-open once per load: a pane the person closed stays closed (`/agents-pane` reopens it).
  let isOpened = false

  // Register the command that reopens the pane; the pane itself opens on the first spawn.
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: PANE,
      description: 'Show the subagents of this session (type, model, status, duration)',
    })

    return next(e)
  })

  on('command.run', { command: PANE }, async $ => {
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Agents pane opened.' }
  })

  // Record each spawn after the engine resolved its model and id.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    if (started.deny !== undefined || started.agentId === undefined) {
      return started
    }
    const id = started.agentId

    await update($, runs, list => {
      // A resumed agent keeps its row: mark it running again.
      if (list.some(run => run.id === id)) {
        return list.map(run =>
          run.id === id ? { ...run, status: 'running' } : run,
        )
      }
      const run: AgentRun = {
        id,
        type: e.subagentType,
        description: e.description,
        model: started.model,
        status: 'running',
      }
      return [...list, run].slice(-MAX_RUNS)
    })
    // Show the pane the first time there is something in it.
    if (!isOpened) {
      isOpened = true
      void $.ui.open({ id: PANE, title: TITLE })
    }

    return started
  })

  // A subagent's turn ended: store its outcome and duration.
  on('turn.complete', async ($, e, next) => {
    const agentId = e.agentId
    if (agentId !== undefined) {
      const status: AgentRunStatus =
        e.reason === 'answer' ? 'done' : e.reason === 'aborted' ? 'aborted' : 'failed'
      await update($, runs, list =>
        list.map(run =>
          run.id === agentId ? { ...run, status, durationMs: e.durationMs } : run,
        ),
      )
    }

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const list = await read($, runs)

    if (list.length === 0) {
      return <Text dimColor>No subagents yet.</Text>
    }

    // Tally per model family: shows at a glance how much work ran on cheap models.
    const tally = new Map<string, number>()
    for (const run of list) {
      tally.set(family(run.model), (tally.get(family(run.model)) ?? 0) + 1)
    }
    const summary = [...tally].map(([name, count]) => `${name} ${count}`).join(' · ')
    const running = list.filter(run => run.status === 'running').length
    // Newest first, as many rows as fit (two rows per run, two for the header).
    const room = Math.max(1, Math.floor((e.props.scroll.bodyRows - 2) / 2))
    const shown = list.slice(-room).reverse()

    return (
      <Box flexDirection="column">
        <Text weight="bold">
          {running} running · {summary}
        </Text>
        {shown.map(run => (
          <Box key={run.id} flexDirection="column">
            <Text dimColor={run.status !== 'running'}>
              {GLYPH[run.status]} {run.type} · {shortModel(run.model)}
              {run.durationMs === undefined ? '' : ` · ${formatDuration(run.durationMs)}`}
            </Text>
            <Text dimColor>{'  '}{run.description}</Text>
          </Box>
        ))}
      </Box>
    )
  })
}
