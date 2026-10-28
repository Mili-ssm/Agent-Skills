import { atom, memberOf, read, update } from 'claude-code'
import type { BoxProps, ElementConstructor, EngineInterface, Register, SvgProps, TextProps } from 'claude-code'

import type { AgentRun, AgentRunStatus, Step, StepKind } from '../types'

// Keep the list bounded: a long session can spawn hundreds of agents.
const MAX_RUNS = 100
// Bump the shape tag when AgentRun's fields change: an older stored list is then read as empty.
const runs = atom({ plugin: 'agents-pane', key: 'runs' } as const, [], {
  shape: 'runs-4',
})
// The runs drawn on one Agent call's row, keyed by its tool_use_id: a change to one agent
// redraws its own card, not every card in the chat.
const byCall = atom({ plugin: 'agents-pane', key: 'byCall' } as const, [], { shape: 'runs-4' })
// The clock the live elapsed times read: only running cards and the spinner block subscribe,
// so its tick redraws them alone (an invalidate would redraw every row this plugin hooks).
const clock = atom({ plugin: 'agents-pane', key: 'now' } as const, 0)

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

// Agents the bottom block and the status line name before `+n`.
const SHOWN = 3

// Asks Haiku for the mission line: what the agent was asked, as a person would say it.
const MISSION_PROMPT =
  'En una sola frase corta (máximo 12 palabras), en español llano y sin tecnicismos innecesarios, ' +
  'di qué se le ha pedido hacer a este agente. Responde solo con la frase, sin comillas ni punto final.\n\nEncargo:\n'

/** The agent type without its plugin prefix: `agent-skills:researcher` → `researcher`. */
const agentName = (run: AgentRun): string => run.type.replace(/^[\w-]+:/, '')

/** The newest live call of a run, if one is running. */
const liveStep = (run: AgentRun): Step | undefined => run.current[run.current.length - 1]

/** `Explored 3 files · Ran 2 commands · 1 failed`. */
const summaryOf = (run: AgentRun): string => {
  const failures = run.failures ?? 0
  return summarize(run.counts) + (failures > 0 ? ` · ${failures} failed` : '')
}

/**
 * The status line, used while the main loop is idle and only background agents run:
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
  const doing = (run: AgentRun, max: number): string => {
    const step = liveStep(run)
    return step === undefined ? '' : ` ▸ ${clip(step.label, max)}`
  }
  const elapsed = (run: AgentRun): string => formatDuration(now - run.startedAt)
  const only = running[0]
  if (running.length === 1 && only !== undefined) {
    return `${frame} ${agentName(only)} · ${shortModel(only.model)}${doing(only, 60)} · ${elapsed(only)}`
  }
  const shown = running.slice(0, SHOWN).map(run => `${agentName(run)}${doing(run, 28)} ${elapsed(run)}`)
  const more = running.length > SHOWN ? ` │ +${running.length - SHOWN}` : ''
  return `${frame} ${running.length} agents · ${shown.join(' │ ')}${more}`
}

/** The elements a card is drawn with; `Svg` where the surface has it. */
type Elements = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
  Svg?: ElementConstructor<SvgProps>
}

/** `◐ ux-reviewer ● sonnet-5-5 [label] 37s`: the row every card and block opens with. */
function runHeader(ui: Elements, run: AgentRun, now: number, frame: string, label?: string) {
  const { Box, Text, Svg } = ui
  const isRunning = run.status === 'running'
  const outcome = OUTCOME[run.status]
  const elapsed = formatDuration(run.durationMs ?? now - run.startedAt)
  const bullet = !isRunning ? (
    <Text color={outcome.color} bold>
      •
    </Text>
  ) : Svg === undefined ? (
    <Text color={outcome.color}>{frame}</Text>
  ) : (
    <Svg source={SPINNER_SVG} alt="running" width={12} height={12} isInteractive />
  )
  return (
    <Box key={`${run.id}-head`} flexDirection="row" gap={1}>
      {bullet}
      <Text weight="bold" dimColor={run.status === 'done'}>
        {agentName(run)}
      </Text>
      <Text dimColor>
        <Text color={FAMILY_COLOR[family(run.model)] ?? 'subtle'}>●</Text> {shortModel(run.model)}
      </Text>
      {label === undefined ? null : (
        <Text dimColor wrap="truncate">
          {label}
        </Text>
      )}
      <Text dimColor tabular>
        {isRunning ? `${outcome.word} ${elapsed}` : elapsed}
      </Text>
    </Box>
  )
}

/** `  ✓ Read session.py` / `  ◐ Run npm test`: one call, only its glyph colored. */
function stepRow(ui: Elements, step: Step, frame: string, indent: string) {
  const { Text } = ui
  return (
    <Text key={step.id} dimColor={step.status !== 'running'} wrap="truncate">
      {indent}
      {step.status === 'running' ? (
        <Text color="claude">{frame}</Text>
      ) : (
        <Text color={step.status === 'failed' ? 'error' : 'success'}>{step.status === 'failed' ? '✗' : '✓'}</Text>
      )}{' '}
      {step.label}
    </Text>
  )
}

/** Mirrors the running agents on the status line while the main loop is idle; never throws. */
async function publishStatus($: EngineInterface): Promise<void> {
  try {
    // While the main loop works, the block under its spinner shows them instead.
    $.ui.status(isMainWorking ? undefined : statusText(await read($, runs), await $.clock.now()))
  } catch (error) {
    $.ui.log(`agents-pane: ${String(error)}`, { to: 'debug' })
  }
}

// Module state, reset by a reload: the next event sets both again.
// Ticks the live elapsed time while any agent runs.
let tick: { cancel: () => void } | undefined
// True while the main loop's turn runs, when its spinner (and the block under it) is drawn.
let isMainWorking = false

/** Applies `fn` to the run with this agent id; never throws (a tool call must not fail on it). */
async function patch($: EngineInterface, agentId: string, fn: (run: AgentRun) => AgentRun): Promise<void> {
  try {
    const list = await update($, runs, all => all.map(run => (run.id === agentId ? fn(run) : run)))
    await mirror($, list, agentId)
    await publishStatus($)
  } catch (error) {
    $.ui.log(`agents-pane: ${String(error)}`, { to: 'debug' })
  }
}

/** Copies the runs of `agentId`'s Agent call into that call's family member, which its card reads. */
async function mirror($: EngineInterface, list: readonly AgentRun[], agentId: string): Promise<void> {
  const toolUseId = list.find(run => run.id === agentId)?.toolUseId
  if (toolUseId !== undefined) {
    const cards = list.filter(run => run.toolUseId === toolUseId)
    await update($, memberOf(byCall, { requestId: toolUseId }), () => cards)
  }
}

/** Starts the one-second redraw while something runs, stops it once nothing does. */
async function syncTick($: EngineInterface): Promise<void> {
  await publishStatus($)
  const isRunning = (await read($, runs)).some(run => run.status === 'running')
  if (isRunning && tick === undefined) {
    tick = $.clock.every(1000, () => {
      void $.clock.now().then(now => update($, clock, () => now))
      void publishStatus($)
    })
  } else if (!isRunning && tick !== undefined) {
    tick.cancel()
    tick = undefined
  }
}

/** Asks Haiku for the run's mission line and stores it; a miss leaves the description. */
async function writeMission($: EngineInterface, agentId: string, prompt: string): Promise<void> {
  const reply = await $.model.complete({
    model: 'haiku',
    prompt: MISSION_PROMPT + prompt.slice(0, 4000),
    maxTokens: 60,
    timeoutMs: 20000,
  })
  if (reply.isAnswered && reply.text.trim() !== '') {
    const mission = clip(reply.text.trim().replace(/^["'«“]+|["'»”.]+$/g, ''), 100)
    await patch($, agentId, run => ({ ...run, mission }))
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
    let isNew = true
    const record = async (): Promise<void> => {
      const startedAt = await $.clock.now()
      const list = await update($, runs, all => {
        // A resumed agent keeps its card: mark it running again.
        if (all.some(run => run.id === id)) {
          isNew = false
          return all.map(run => (run.id === id ? { ...run, status: 'running', startedAt } : run))
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
        return [...all, run].slice(-MAX_RUNS)
      })
      await mirror($, list, id)
      await update($, clock, () => startedAt)
      await syncTick($)
    }
    // A failure here costs the card, never the spawn.
    await record().catch(error => $.ui.log(`agents-pane: ${String(error)}`, { to: 'debug' }))
    // The mission arrives later; the spawn does not wait for it.
    if (isNew) {
      void writeMission($, id, e.prompt).catch(error =>
        $.ui.log(`agents-pane: mission: ${String(error)}`, { to: 'debug' }),
      )
    }

    return started
    // The card is a view: a failing hook lets the call go on as if the mod were not there.
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
      recent: [...run.recent, { ...step, status }].slice(-2),
      counts: { ...run.counts, [step.kind]: (run.counts[step.kind] ?? 0) + 1 },
      failures: (run.failures ?? 0) + (status === 'failed' ? 1 : 0),
    }))

    return result
  }).catch(($, e, next) => next(e))

  // The main loop's spinner shows while its turn runs: the running agents move under it.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      isMainWorking = true
      await publishStatus($)
    }

    return next(e)
  })

  // A subagent's turn ended: store its outcome and duration. The main loop's: back to the status line.
  on('turn.complete', async ($, e, next) => {
    const agentId = e.agentId
    if (agentId === undefined) {
      isMainWorking = false
      await publishStatus($)
    } else {
      const status: AgentRunStatus =
        e.reason === 'answer' ? 'done' : e.reason === 'aborted' ? 'aborted' : 'failed'
      await patch($, agentId, run => ({ ...run, status, durationMs: e.durationMs, current: [] }))
      await syncTick($)
    }

    return next(e)
  })

  // Under the main spinner: one framed block per running agent, stacked, with its mission and live call.
  on('ui.render', { component: 'Spinner' }, async ($, e, next) => {
    const list = await read($, runs)
    const running = list.filter(run => run.status === 'running')
    // A subagent's own spinner keeps the engine's look.
    if (running.length === 0 || list.some(run => run.id === e.requestId)) {
      return next(e)
    }
    const engine = await next(e)
    const ui = $.ui.resolve(e)
    const { Box, Text } = ui
    // Subscribes the block to the tick; the time itself is read fresh.
    await read($, clock)
    const now = await $.clock.now()
    const frame = FRAMES[Math.floor(now / 250) % FRAMES.length] ?? '•'
    const elements: Elements = e.surface === 'terminal' ? { Box, Text } : { Box, Text, Svg: $.ui.resolve(e).Svg }
    const hidden = running.length - SHOWN

    return (
      <Box flexDirection="column">
        {engine}
        <Box
          flexDirection="column"
          gap={1}
          {...(e.surface === 'terminal' ? { borderStyle: 'round', borderDimColor: true, paddingX: 1 } : {})}
        >
          {running.slice(0, SHOWN).map(run => {
            const step = liveStep(run)
            const summary = summaryOf(run)
            return (
              <Box key={run.id} flexDirection="column">
                {runHeader(elements, run, now, frame)}
                <Text wrap="truncate">
                  {'  '}
                  {run.mission ?? run.description}
                </Text>
                {step === undefined ? (
                  <Text dimColor wrap="truncate">
                    {'  └ '}
                    {summary === '' ? 'Starting…' : summary}
                  </Text>
                ) : (
                  stepRow(elements, step, frame, '  ')
                )}
              </Box>
            )
          })}
          {hidden > 0 ? <Text dimColor>{`+${hidden} ${hidden === 1 ? 'agente más' : 'agentes más'}`}</Text> : null}
        </Box>
      </Box>
    )
  })

  // The Agent call's own row in the transcript becomes the card: compact while it runs, one summary after.
  // Matched on the tool, so the engine never runs this hook for the other rows of the chat.
  on('ui.render', { component: 'ToolUse', props: { tool: 'Agent' } }, async ($, e, next) => {
    if (e.props.isExpanded === true) {
      return next(e)
    }
    const cards = await read($, memberOf(byCall, e))
    if (cards.length === 0) {
      return next(e)
    }
    const ui = $.ui.resolve(e)
    const { Box, Text } = ui
    // Only a running card follows the tick; a finished one never redraws for it.
    if (cards.some(run => run.status === 'running')) {
      await read($, clock)
    }
    const now = await $.clock.now()
    const frame = FRAMES[Math.floor(now / 250) % FRAMES.length] ?? '•'
    const elements: Elements = e.surface === 'terminal' ? { Box, Text } : { Box, Text, Svg: $.ui.resolve(e).Svg }

    const card = (run: AgentRun) => {
      const header = runHeader(elements, run, now, frame, run.mission ?? run.description)
      const summary = summaryOf(run)

      // Finished: the header plus what it did (Codex's collapsed group).
      if (run.status !== 'running') {
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

      // Running: the last finished call and the live one; the full block sits at the bottom.
      const steps = [...run.recent, ...run.current].slice(-2)
      return (
        // Desktop and VS Code already frame a plugin's tree; the terminal gets a quiet border of its own.
        <Box
          key={run.id}
          flexDirection="column"
          {...(e.surface === 'terminal' ? { borderStyle: 'round', borderDimColor: true, paddingX: 1 } : {})}
        >
          {header}
          {steps.length === 0 ? (
            <Text dimColor>{'└ Starting…'}</Text>
          ) : (
            steps.map(step => stepRow(elements, step, frame, '  '))
          )}
        </Box>
      )
    }

    return <Box flexDirection="column">{cards.map(card)}</Box>
  })
}
