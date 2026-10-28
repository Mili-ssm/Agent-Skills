import { atom, memberOf, read, update } from 'claude-code'
import type { BoxProps, ElementConstructor, EngineInterface, Register, RenderElement, RenderSurface, TextProps } from 'claude-code'

import type { AgentRun, AgentRunStatus, Step, StepKind } from '../types'

// Keep the list bounded: a long session can spawn hundreds of agents.
const MAX_RUNS = 100
// Bump the shape tag when AgentRun's fields change: an older stored list is then read as empty.
const runs = atom({ plugin: 'tool-fold', key: 'runs' } as const, [], {
  shape: 'runs-4',
})
// The runs drawn on one Agent call's row, keyed by its tool_use_id: a change to one agent
// redraws its own card, not every card in the chat.
export const byCall = atom({ plugin: 'tool-fold', key: 'byCall' } as const, [], { shape: 'runs-4' })
// The clock the live elapsed times read: only running cards and the spinner block subscribe,
// so its tick redraws them alone (an invalidate would redraw every row this plugin hooks).
const clock = atom({ plugin: 'tool-fold', key: 'now' } as const, 0)

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
  // A line that only changes directory or sets a variable says nothing: the first other line does.
  const setup = /^\s*(?:cd\s+\S+|export\s+\w+=\S*|\w+=\S*)\s*(?:&&|;)?\s*\\?\s*$/
  const lines = command.split('\n').filter(item => item.trim() !== '')
  let line = lines.find(item => !setup.test(item)) ?? lines[0] ?? ''
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

/**
 * How a call changes the agent's own task list, for its `3/7` progress: TodoWrite states the whole
 * list; TaskCreate adds one task; TaskUpdate to `completed` finishes one (once per task id).
 */
export function planChange(tool: string, input: Record<string, unknown>): ((todo: AgentRun['todo']) => AgentRun['todo']) | undefined {
  if (tool === 'TodoWrite' && Array.isArray(input.todos)) {
    const todos = input.todos as readonly Record<string, unknown>[]
    const done = todos.filter(item => item.status === 'completed').length
    return () => ({ done, total: todos.length, completed: [] })
  }
  if (tool === 'TaskCreate') {
    return todo => ({ done: todo?.done ?? 0, total: (todo?.total ?? 0) + 1, completed: todo?.completed ?? [] })
  }
  if (tool === 'TaskUpdate' && input.status === 'completed' && typeof input.taskId === 'string') {
    const id = input.taskId
    return todo =>
      todo === undefined || todo.completed.includes(id)
        ? todo
        : { ...todo, done: Math.min(todo.total, todo.done + 1), completed: [...todo.completed, id] }
  }
  return undefined
}

/** `▰▰▰▱▱` for done/total over `width` cells. */
export const progressBar = (done: number, total: number, width: number): string => {
  const filled = total === 0 ? 0 : Math.round((done / total) * width)
  return '▰'.repeat(filled) + '▱'.repeat(width - filled)
}

/** Spinner frames; the frame follows the clock tick. A glyph on every surface: an animated Svg
 * needs a sandboxed frame per running header, too heavy for a row redrawn every second. */
const FRAMES = ['◐', '◓', '◑', '◒']

/** Status word and bullet color of a finished or running card. */
const OUTCOME: Record<AgentRunStatus, { word: string; color: string }> = {
  running: { word: 'Working', color: 'claude' },
  done: { word: 'Done', color: 'success' },
  failed: { word: 'Failed', color: 'error' },
  aborted: { word: 'Stopped', color: 'warning' },
}

// Asks Haiku for the mission line: what the agent was asked, as a person would say it.
const MISSION_PROMPT =
  'En una sola frase corta (máximo 12 palabras), en español llano y sin tecnicismos innecesarios, ' +
  'di qué se le ha pedido hacer a este agente. Responde solo con la frase, sin comillas ni punto final.\n\nEncargo:\n'

/** The agent type without its plugin prefix: `agent-skills:researcher` → `researcher`. */
const agentName = (run: AgentRun): string => run.type.replace(/^[\w-]+:/, '')

/** `Explored 3 files · Ran 2 commands · 1 failed`. */
const summaryOf = (run: AgentRun): string => {
  const failures = run.failures ?? 0
  return summarize(run.counts) + (failures > 0 ? ` · ${failures} failed` : '')
}

/** The elements a card is drawn with. */
export type Elements = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
}

/** `◐ ux-reviewer ● sonnet-5-5 [label] 37s`: the row every card and block opens with. */
function runHeader(ui: Elements, run: AgentRun, now: number, frame: string, label?: string) {
  const { Box, Text } = ui
  const isRunning = run.status === 'running'
  const outcome = OUTCOME[run.status]
  const elapsed = formatDuration(run.durationMs ?? now - run.startedAt)
  const bullet = !isRunning ? (
    <Text color={outcome.color} bold>
      •
    </Text>
  ) : (
    <Text color={outcome.color}>{frame}</Text>
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
      {run.todo === undefined || run.todo.total === 0 ? null : (
        <Text dimColor>
          <Text color={run.todo.done === run.todo.total ? 'success' : 'claude'}>
            {progressBar(run.todo.done, run.todo.total, 5)}
          </Text>{' '}
          {run.todo.done}/{run.todo.total}
        </Text>
      )}
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

// Module state, reset by a reload (session.start starts it again): ticks the live elapsed time while any agent runs.
let tick: { cancel: () => void } | undefined

/** Applies `fn` to the run with this agent id; never throws (a tool call must not fail on it). */
async function patch($: EngineInterface, agentId: string, fn: (run: AgentRun) => AgentRun): Promise<void> {
  try {
    const list = await update($, runs, all => all.map(run => (run.id === agentId ? fn(run) : run)))
    await mirror($, list, agentId)
  } catch (error) {
    $.ui.log(`tool-fold: ${String(error)}`, { to: 'debug' })
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
  const isRunning = (await read($, runs)).some(run => run.status === 'running')
  if (isRunning && tick === undefined) {
    tick = $.clock.every(1000, () => {
      void $.clock.now().then(now => update($, clock, () => now))
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

/** The agent hooks: spawns, their calls and ends, the spinner block; tool-fold's register adds them. */
export const registerAgents: Register = (on, options) => {
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
    await record().catch(error => $.ui.log(`tool-fold: ${String(error)}`, { to: 'debug' }))
    // The mission arrives later; the spawn does not wait for it.
    // A workflow's agents draw no Agent card (and may carry a placeholder prompt): no Haiku call.
    if (isNew && e.workflow === undefined) {
      void writeMission($, id, e.prompt).catch(error =>
        $.ui.log(`tool-fold: mission: ${String(error)}`, { to: 'debug' }),
      )
    }

    return started
    // The card is a view: a failing hook lets the call go on as if the mod were not there.
  }).catch(($, e, next) => next(e))


  // After a load or a hot reload (which drops the timer and module state): pick up running agents again.
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    // Earlier versions kept running agents on the status line: clear what one left there.
    $.ui.status(undefined)
    await syncTick($)

    return started
  })

}

/**
 * A subagent's tool call starts: shown as its live call. Returns the step to close with `endAgentCall`,
 * or undefined for a loop this mod does not track. Never throws.
 */
export async function startAgentCall(
  $: EngineInterface,
  agentId: string,
  tool: string,
  toolUseId: string,
  input: Record<string, unknown>,
): Promise<Step | undefined> {
  const isTracked = await read($, runs)
    .then(list => list.some(run => run.id === agentId))
    .catch(() => false)
  if (!isTracked) {
    return undefined
  }
  const step: Step = { id: toolUseId, ...describeStep(tool, input), status: 'running' }
  await patch($, agentId, run => ({ ...run, current: [...run.current, step] }))
  return step
}

/** A subagent's tool call ended: folded into its summary, and into its task count when it plans. */
export async function endAgentCall(
  $: EngineInterface,
  agentId: string,
  step: Step,
  tool: string,
  input: Record<string, unknown>,
  status: Step['status'],
): Promise<void> {
  const plan = status === 'done' ? planChange(tool, input) : undefined
  await patch($, agentId, run => ({
    ...run,
    ...(plan === undefined ? {} : { todo: plan(run.todo) }),
    current: run.current.filter(item => item.id !== step.id),
    recent: [...run.recent, { ...step, status }].slice(-2),
    counts: { ...run.counts, [step.kind]: (run.counts[step.kind] ?? 0) + 1 },
    failures: (run.failures ?? 0) + (status === 'failed' ? 1 : 0),
  }))
}

/** A loop's turn ended: a subagent's stores its outcome; the main loop's moves agents back to the status line. */
export async function endAgentTurn(
  $: EngineInterface,
  agentId: string | undefined,
  reason: string,
  durationMs: number,
): Promise<void> {
  if (agentId === undefined) {
    return
  }
  const status: AgentRunStatus = reason === 'answer' ? 'done' : reason === 'aborted' ? 'aborted' : 'failed'
  await patch($, agentId, run => ({ ...run, status, durationMs, current: [] }))
  await syncTick($)
}

/** True while an agent of this Agent call still runs: its card stays in view, folded group or not. */
export async function isAgentLive($: EngineInterface, toolUseId: string): Promise<boolean> {
  return (await read($, memberOf(byCall, { requestId: toolUseId }))).some(run => run.status === 'running')
}

/**
 * The card an Agent call's row draws: live while its agent runs, one summary line after.
 * Null when no run of this session belongs to the call (one spawned before the mod loaded).
 */
export async function agentCard(
  $: EngineInterface,
  toolUseId: string,
  surface: RenderSurface,
  ui: Elements,
): Promise<RenderElement | null> {
  const cards = await read($, memberOf(byCall, { requestId: toolUseId }))
  if (cards.length === 0) {
    return null
  }
  const { Box, Text } = ui
  // Only a running card follows the tick; a finished one never redraws for it.
  if (cards.some(run => run.status === 'running')) {
    await read($, clock)
  }
  const now = await $.clock.now()
  const frame = FRAMES[Math.floor(now / 250) % FRAMES.length] ?? '•'

  const card = (run: AgentRun) => {
    const header = runHeader(ui, run, now, frame, run.mission ?? run.description)
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
        {...(surface === 'terminal' ? { borderStyle: 'round', borderDimColor: true, paddingX: 1 } : {})}
      >
        {header}
        {steps.length === 0 ? <Text dimColor>{'└ Starting…'}</Text> : steps.map(step => stepRow(ui, step, frame, '  '))}
      </Box>
    )
  }

  return <Box flexDirection="column">{cards.map(card)}</Box>
}
