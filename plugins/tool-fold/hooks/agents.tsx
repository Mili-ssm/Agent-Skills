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
// The "Agentes" pane: running agents live there while it is placed; the chat keeps one line each.
const DOCK = 'agents'
const docked = atom({ plugin: 'tool-fold', key: 'docked' } as const, false)

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
  // `VAR=value cmd`: an assignment in front of the command itself.
  const env = /^\s*\w+=(?:"[^"]*"|'[^']*'|\S*)\s+(?=\S)/
  while (prefix.test(line) || env.test(line)) {
    line = line.replace(prefix, '').replace(env, '')
  }
  return line.replace(/(?:\/[^\s/'"]+){3,}/g, path =>
    path.length <= 24 ? path : `…/${path.split('/').slice(-2).join('/')}`,
  )
}

/** What a tool call does and how a card names it, from its name and input. */
export function describeStep(tool: string, input: Record<string, unknown>): { kind: StepKind; label: string; detail?: string } {
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
      // The model's own few words on what the command does, when it gave them.
      return {
        kind: 'run',
        label: `Run ${clip(commandOf(text('command')), 56)}`,
        ...(text('description') === '' ? {} : { detail: clip(text('description'), 60) }),
      }
    case 'WebSearch':
      return { kind: 'web', label: `Web search ${clip(`"${text('query')}"`, 40)}` }
    case 'WebFetch':
      return { kind: 'web', label: `Fetch ${clip(text('url').replace(/^https?:\/\//, ''), 40)}` }
    case 'Agent':
      return { kind: 'agent', label: `Agent ${clip(text('description'), 40)}` }
    case 'Skill':
      return { kind: 'skill', label: text('skill').replace(/^[\w-]+:/, '') || 'Skill' }
    default:
      return { kind: 'other', label: tool.replace(/^mcp__/, '').replace(/__/g, ' ') }
  }
}

const plural = (count: number, word: string): string => `${count} ${word}${count === 1 ? '' : 's'}`

/** `Explored 3 files, 2 searches · Edited 1 file · Ran 2 commands`, as Codex groups calls. */
export function summarize(
  counts: AgentRun['counts'],
  extra: { files?: readonly string[]; skills?: readonly string[] } = {},
): string {
  const n = (kind: StepKind): number => counts[kind] ?? 0
  const parts: string[] = []
  // Every call counted once: how much the agent did, before what kind of things.
  const total = Object.values(counts).reduce((sum, count) => sum + (count ?? 0), 0)
  if (total > 1) {
    parts.push(plural(total, 'call'))
  }
  const explored = [
    n('read') > 0 ? plural(n('read'), 'file') : '',
    n('list') > 0 ? plural(n('list'), 'listing') : '',
    n('search') > 0 ? plural(n('search'), 'search').replace('searchs', 'searches') : '',
  ].filter(Boolean)
  if (explored.length > 0) {
    parts.push(`Explored ${explored.join(', ')}`)
  }
  if (n('edit') > 0) {
    // Distinct files where they were recorded, else the edits.
    parts.push(`Edited ${plural(extra.files?.length || n('edit'), 'file')}`)
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
  // Skills by name: they say what kind of work it was.
  if (extra.skills !== undefined && extra.skills.length > 0) {
    parts.push(extra.skills.join(', '))
  } else if (n('skill') > 0) {
    parts.push(plural(n('skill'), 'skill'))
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

// Asks Haiku what a shell command does, for a call that came without the model's own description.
const COMMAND_PROMPT =
  'Di en 3 a 7 palabras, en español llano, la acción concreta que ejecuta este comando de terminal: ' +
  'qué programa corre y sobre qué, no para qué lo quiere el agente. Ejemplos:\n' +
  '`cargo test -p viewer_format` → Ejecuta los tests de viewer_format\n' +
  '`until grep -q complete run.log; do sleep 30; done` → Espera a que run.log diga complete\n' +
  '`sed -n 1,80p src/main.rs` → Muestra las líneas 1-80 de main.rs\n' +
  '`git diff --stat HEAD~3` → Resume los cambios de 3 commits\n' +
  'Responde solo con la frase, sin comillas ni punto final.\n\n'
// Asks Haiku how far an agent with no task list is, from its mission and what it did so far.
// How Haiku estimates an agent's progress: the fixed rules as the system prompt, the agent's data as
// the message. No phase scale: agents differ too much (a watcher has no phases); the rules cover the
// readings that mislead, and an open-ended mission gets no number at all.
const ESTIMATE_SYSTEM = [
  'Estimas cuánto lleva hecho un agente de programación de su misión, a partir de lo que ya hizo.',
  'Reglas:',
  '- La misión dice qué cuenta como terminado; juzga cuánto de eso muestran ya sus acciones.',
  '- Una espera larga o repetida (compilar, medir, sondear un log) no es avance por sí misma.',
  '- Si la misma acción falla varias veces, está atascado: no subas.',
  '- Mantente cerca de tu estimación anterior salvo un avance claro.',
  '- Si la misión no tiene un final medible (vigilar un proceso o un PR, esperar un evento), responde ?.',
  'Responde solo con un número entero entre 0 y 95, o con ?, sin texto.',
].join('\n')
// Durations remembered per agent type across sessions ($.store, a local file): no model call reads them.
const REMEMBERED = 10

/** Middle of a list of durations: the typical one, robust to an odd outlier. */
export const median = (values: readonly number[]): number | undefined => {
  if (values.length === 0) {
    return undefined
  }
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1 ? sorted[middle] : Math.round(((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2)
}

/** The store key of one agent type's remembered durations (one key per type: no read-modify race across types). */
const durationsKey = (type: string): string => `durations:${type}`

/** The durations remembered for an agent type, newest last; an empty list when none or unreadable. */
async function rememberedDurations($: EngineInterface, type: string): Promise<number[]> {
  const value = await $.store.get(durationsKey(type)).catch(() => undefined)
  return Array.isArray(value) ? value.filter((item): item is number => typeof item === 'number') : []
}

// Calls kept per agent for the estimate's history, newest last.
const HISTORY = 40
// How far one estimate may fall below the last: a new reading, not a jump back.
const MAX_DROP = 10
// An estimate follows each call of an agent, at most this often per agent; one asked sooner waits.
const ESTIMATE_GAP_MS = 30_000

/** The agent type without its plugin prefix: `agent-skills:researcher` → `researcher`. */
const agentName = (run: AgentRun): string => run.type.replace(/^[\w-]+:/, '')

/** `Explored 3 files · Ran 2 commands · 1 failed`. */
const summaryOf = (run: AgentRun): string => countsLine(run)

/**
 * `34 calls · 9 searches · 4 edits · 20 commands · qa-review · 1 failed`: what an agent did, in one
 * condensed line. Searches are reads, listings, searches and web calls; edits are distinct files.
 */
export function countsLine(run: Pick<AgentRun, 'counts' | 'files' | 'skills' | 'failures'>): string {
  const n = (kind: StepKind): number => run.counts[kind] ?? 0
  const total = Object.values(run.counts).reduce((sum, count) => sum + (count ?? 0), 0)
  const searches = n('read') + n('list') + n('search') + n('web')
  const edits = run.files?.length || n('edit')
  const parts = [
    total > 0 ? plural(total, 'call') : '',
    searches > 0 ? plural(searches, 'search').replace('searchs', 'searches') : '',
    edits > 0 ? plural(edits, 'edit') : '',
    n('run') > 0 ? plural(n('run'), 'command') : '',
    (run.skills ?? []).join(', '),
    (run.failures ?? 0) > 0 ? `${run.failures} failed` : '',
  ]
  return parts.filter(Boolean).join(' · ')
}

/** The elements a card is drawn with. */
export type Elements = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
}

/**
 * The percentage a running card shows: Haiku's reading, or for an open-ended mission (a watcher) the
 * time against how long its type usually takes, worked out as it draws (no model call), capped at 95.
 */
export function estimateOf(run: Pick<AgentRun, 'estimate' | 'isOpenEnded' | 'typical' | 'startedAt'>, now: number): number | undefined {
  if (run.estimate !== undefined) {
    return run.estimate
  }
  if (run.isOpenEnded === true && run.typical !== undefined && run.typical.ms > 0) {
    return Math.min(95, Math.round(((now - run.startedAt) / run.typical.ms) * 100))
  }
  return undefined
}

/** `◐ ux-reviewer ● sonnet-5-5 [label] 37s`: the row every card and block opens with. */
function runHeader(
  ui: Elements,
  run: AgentRun,
  now: number,
  frame: string,
  label?: string,
  withEstimate = false,
  mark?: string,
) {
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
  // Its own task list when it keeps one; else, while it runs in the pane, Haiku's estimate.
  const progress =
    run.todo !== undefined && run.todo.total > 0 ? (
      <Text dimColor>
        <Text color={run.todo.done === run.todo.total ? 'success' : 'claude'}>
          {progressBar(run.todo.done, run.todo.total, 5)}
        </Text>{' '}
        {run.todo.done}/{run.todo.total}
      </Text>
    ) : withEstimate && isRunning && estimateOf(run, now) !== undefined ? (
      <Text dimColor>
        <Text color="claude">{progressBar(estimateOf(run, now) ?? 0, 100, 5)}</Text> ≈{estimateOf(run, now)}%
      </Text>
    ) : null
  // Two lines, so a narrow chat wraps nothing: who and how far, then what it was asked.
  return (
    <Box key={`${run.id}-head`} flexDirection="column">
      <Box flexDirection="row" gap={1} minWidth={0} overflow="hidden">
        {mark === undefined ? null : <Text dimColor>{mark}</Text>}
        {bullet}
        <Text weight="bold" dimColor={run.status === 'done'}>
          {agentName(run)}
        </Text>
        <Text dimColor>
          <Text color={FAMILY_COLOR[family(run.model)] ?? 'subtle'}>●</Text> {shortModel(run.model)}
        </Text>
        {progress}
        <Text dimColor tabular>
          {isRunning ? `${outcome.word} ${elapsed}` : elapsed}
        </Text>
      </Box>
      {label === undefined ? null : (
        <Text dimColor wrap="truncate">
          {mark === undefined ? '  ' : '    '}
          {label}
        </Text>
      )}
    </Box>
  )
}

/** `  ✓ Read session.py` / `  ◐ Run npm test`: one call, only its glyph colored. */
function stepRow(ui: Elements, step: Step, frame: string, indent: string, withDetail = false) {
  const { Text } = ui
  const glyph =
    step.status === 'running' ? (
      <Text color="claude">{frame}</Text>
    ) : (
      <Text color={step.status === 'failed' ? 'error' : 'success'}>{step.status === 'failed' ? '✗' : '✓'}</Text>
    )
  // In the pane a call reads by what it does alone; the command shows until its words arrive.
  return (
    <Text key={step.id} dimColor={step.status !== 'running'} wrap="truncate">
      {indent}
      {glyph} {withDetail && step.detail !== undefined ? step.detail : step.label}
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
          background: e.background,
          current: [],
          recent: [],
          counts: {},
        }
        return [...all, run].slice(-MAX_RUNS)
      })
      await mirror($, list, id)
      // How long agents of this type took before: a reference for the estimate, read once per spawn.
      const past = await rememberedDurations($, e.subagentType)
      const typical = median(past)
      if (typical !== undefined) {
        await patch($, id, run => ({ ...run, typical: { ms: typical, of: past.length } }))
      }
      await update($, clock, () => startedAt)
      await syncTick($)
      await openDock($)
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
    await $.command.register({ name: 'agents-dock', description: 'Show running agents in the "Agentes" pane' })
    await syncTick($)
    if ((await read($, runs)).some(run => run.status === 'running')) {
      await openDock($)
    }

    return started
  })

  on('command.run', { command: 'agents-dock' }, async $ => {
    await openDock($)
    const isPlaced = await read($, docked)
    return { text: isPlaced ? 'Agentes pane opened.' : 'The pane could not be placed here; agents stay in the chat.' }
  }).catch(($, e, next) => next(e))

  // The person (or the engine) closed the pane: running agents draw in full in the chat again.
  on('ui.close', { id: 'agents' }, async ($, e, next) => {
    const closed = await next(e)
    await update($, docked, () => false)

    return closed
  }).catch(($, e, next) => next(e))

  // The "Agentes" pane: every running agent's live card, as the chat draws it, oldest first.
  on('ui.render', { component: 'Pane', requestId: 'agents' }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const running = (await read($, runs)).filter(run => run.status === 'running')
    if (running.length === 0) {
      return <Text dimColor>No agents running.</Text>
    }
    await read($, clock)
    const now = await $.clock.now()
    const frame = FRAMES[Math.floor(now / 250) % FRAMES.length] ?? '•'
    // The pane's body in cells, less the card's border and padding.
    const maxChars = Math.max(24, e.props.bodyColumns - 4)
    return (
      <Box flexDirection="column" gap={1} minWidth={0} overflow="hidden">
        {running.map(run => liveCard({ Box, Text }, run, now, frame, running.length > 3, maxChars))}
      </Box>
    )
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
  const step: Step = { id: toolUseId, ...describeStep(tool, input), status: 'running', startedAt: await $.clock.now() }
  await patch($, agentId, run => ({ ...run, current: [...run.current, step] }))
  if (step.kind === 'run' && step.detail === undefined && typeof input.command === 'string') {
    void describeCommand($, agentId, step.id, input.command).catch(error =>
      $.ui.log(`tool-fold: command: ${String(error)}`, { to: 'debug' }),
    )
  }
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
  const endedAt = await $.clock.now()
  await patch($, agentId, run => ({
    ...run,
    // The call as the pane last named it (its words may have arrived after it started), and how long it took.
    history: [
      ...(run.history ?? []),
      {
        what: (run.current.find(item => item.id === step.id) ?? step).detail ?? step.label,
        ms: endedAt - (step.startedAt ?? endedAt),
        ok: status === 'done',
      },
    ].slice(-HISTORY),
    ...(plan === undefined ? {} : { todo: plan(run.todo) }),
    current: run.current.filter(item => item.id !== step.id),
    recent: [...run.recent, { ...step, status }].slice(-2),
    counts: { ...run.counts, [step.kind]: (run.counts[step.kind] ?? 0) + 1 },
    failures: (run.failures ?? 0) + (status === 'failed' ? 1 : 0),
    ...(status === 'done' ? touched(run, step, input) : {}),
  }))
  await requestEstimate($, agentId)
}

/** Asks Haiku what a command without the model's description does, and shows it under the call. */
async function describeCommand($: EngineInterface, agentId: string, stepId: string, command: string): Promise<void> {
  const reply = await $.model.complete({ model: 'haiku', prompt: COMMAND_PROMPT + command.slice(0, 1500), maxTokens: 30, timeoutMs: 15000 })
  if (reply.isAnswered && reply.text.trim() !== '') {
    const detail = clip(reply.text.trim().replace(/^["'«“]+|["'»”.]+$/g, ''), 60)
    const withDetail = (steps: Step[]) => steps.map(item => (item.id === stepId ? { ...item, detail } : item))
    await patch($, agentId, run => ({ ...run, current: withDetail(run.current), recent: withDetail(run.recent) }))
  }
}

/**
 * Every call asks for a fresh estimate. One asked within ESTIMATE_GAP_MS of the last is dropped and a
 * single one is set for when the gap ends, on what the agent has done by then. Module state: a
 * reload drops a waiting one, and the agent's next call asks again.
 */
const waiting = new Set<string>()

async function requestEstimate($: EngineInterface, agentId: string): Promise<void> {
  const run = (await read($, runs)).find(item => item.id === agentId)
  if (run === undefined || run.status !== 'running' || run.todo !== undefined || waiting.has(agentId)) {
    return
  }
  const now = await $.clock.now()
  const wait = run.estimatedAt === undefined ? 0 : run.estimatedAt + ESTIMATE_GAP_MS - now
  if (wait > 0) {
    waiting.add(agentId)
    $.clock.after(wait, () => {
      waiting.delete(agentId)
      void requestEstimate($, agentId)
    })
    return
  }
  await patch($, agentId, item => ({ ...item, estimatedAt: now }))
  void estimateProgress($, agentId).catch(error => $.ui.log(`tool-fold: estimate: ${String(error)}`, { to: 'debug' }))
}

/** The estimate's input: the mission, elapsed time, the calls with their durations, the live one, the last reading. */
export function estimateInput(run: AgentRun, now: number): string {
  const history = (run.history ?? [])
    .map(call => `- ${formatDuration(call.ms)} ${call.ok ? '✓' : '✗'} ${call.what}`)
    .join('\n')
  const live = run.current
    .map(step => `- lleva ${formatDuration(now - (step.startedAt ?? now))}: ${step.detail ?? step.label}`)
    .join('\n')
  return [
    `Misión: ${run.mission ?? run.description}`,
    `Tiempo transcurrido: ${formatDuration(now - run.startedAt)}`,
    run.typical === undefined
      ? ''
      : `Referencia: agentes de este tipo suelen tardar ~${formatDuration(run.typical.ms)} (mediana de ${run.typical.of})`,
    `Hecho: ${countsLine(run) || 'nada aún'}`,
    `Historial (de más antigua a más reciente, con duración):\n${history || '- (ninguna terminada)'}`,
    `En curso:\n${live || '- (entre acciones)'}`,
    run.estimate === undefined ? '' : `Tu estimación anterior: ${run.estimate}%`,
  ]
    .filter(Boolean)
    .join('\n\n')
}

/** Asks Haiku how far an agent with no task list is: a rough percentage for the pane, smoothed. */
async function estimateProgress($: EngineInterface, agentId: string): Promise<void> {
  const run = (await read($, runs)).find(item => item.id === agentId)
  if (run === undefined || run.status !== 'running') {
    return
  }
  const reply = await $.model.complete({
    model: 'haiku',
    system: ESTIMATE_SYSTEM,
    prompt: estimateInput(run, await $.clock.now()),
    maxTokens: 10,
    timeoutMs: 15000,
  })
  // `?`: no measurable end (a watcher): the pane shows no percentage rather than an invented one.
  if (reply.isAnswered && /^\s*\?\s*$/.test(reply.text)) {
    await patch($, agentId, item => {
      const { estimate: _dropped, ...rest } = item
      return { ...rest, isOpenEnded: true }
    })
    return
  }
  const value = reply.isAnswered ? Number.parseInt(reply.text.replace(/[^0-9]/g, ''), 10) : Number.NaN
  if (Number.isFinite(value)) {
    await patch($, agentId, item => {
      if (item.status !== 'running') {
        return item
      }
      // Never past 95 while it runs, and never more than MAX_DROP below the last reading.
      const floor = item.estimate === undefined ? 0 : item.estimate - MAX_DROP
      return { ...item, estimate: Math.max(floor, Math.min(95, value)) }
    })
  }
}

/** The distinct files an edit touched and skills a call used, kept for the finished card's line. */
function touched(run: AgentRun, step: Step, input: Record<string, unknown>): Pick<AgentRun, 'files' | 'skills'> {
  const path = typeof input.file_path === 'string' ? input.file_path : typeof input.notebook_path === 'string' ? input.notebook_path : ''
  if (step.kind === 'edit' && path !== '' && !(run.files ?? []).includes(path)) {
    return { files: [...(run.files ?? []), path] }
  }
  if (step.kind === 'skill' && !(run.skills ?? []).includes(step.label)) {
    return { skills: [...(run.skills ?? []), step.label] }
  }
  return {}
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
  const ended = (await read($, runs)).find(run => run.id === agentId)
  // The newest line of the chat when it stops: what ended and what it did. A dim log row is the one
  // bottom row a mod can add on every surface; the styled card stays on the Agent call's own row.
  if (ended !== undefined) {
    $.ui.log(finishedLine(ended))
  }
  // A finished run teaches how long its type takes (only those that ended well).
  const type = ended?.type
  if (status === 'done' && type !== undefined) {
    const past = await rememberedDurations($, type)
    await $.store.set(durationsKey(type), [...past, durationMs].slice(-REMEMBERED)).catch(() => undefined)
  }
  await syncTick($)
  await closeDockWhenIdle($)
}

/** True while an agent of this Agent call still runs: its card stays in view, folded group or not. */
export async function isAgentLive($: EngineInterface, toolUseId: string): Promise<boolean> {
  return (await read($, memberOf(byCall, { requestId: toolUseId }))).some(run => run.status === 'running')
}

/** A running agent's live card: header, mission, its last two calls. The chat and the pane draw the same one. */
function liveCard(ui: Elements, run: AgentRun, now: number, frame: string, isCompact: boolean, maxChars: number) {
  const { Box, Text } = ui
  // Many agents at once: each card keeps its header, mission and live call only.
  // Texts are cut to the pane's width by hand: a text's natural width otherwise widens the whole pane
  // past a narrow VS Code panel, whatever the card's own sizing says.
  const steps = (isCompact ? run.current.slice(-1) : [...run.recent, ...run.current].slice(-2)).map(step => ({
    ...step,
    label: clip(step.label, maxChars - 6),
    ...(step.detail === undefined ? {} : { detail: clip(step.detail, maxChars - 6) }),
  }))
  const counts = clip(countsLine(run), maxChars - 2)
  return (
    // One card per agent, with a quiet border of its own inside the pane's frame.
    // Stretched by the pane, not sized: a set 100% width plus border and padding overflowed into a scroll
    // bar. minWidth 0 lets it shrink below a long header, and what does not fit is clipped inside.
    <Box key={run.id} flexDirection="column" borderStyle="round" borderDimColor paddingX={1} minWidth={0} overflow="hidden">
      {runHeader(ui, run, now, frame, clip(run.mission ?? run.description, maxChars - 2), true)}
      {steps.length === 0 ? (
        <Text dimColor>{'  Starting…'}</Text>
      ) : (
        // Each call hangs from the agent: a tree mark on both lines.
        steps.map(step => stepRow(ui, step, frame, '  └ ', true))
      )}
      {isCompact || counts === '' ? null : (
        <Text dimColor wrap="truncate">
          {'  '}
          {counts}
        </Text>
      )}
    </Box>
  )
}

/**
 * The card an Agent call's row draws: nothing while its agent runs (the pane shows it), the folded
 * card once a foreground agent ended. Null when no run of this session belongs to the call (one
 * spawned before the mod loaded).
 */
export async function agentCard(
  $: EngineInterface,
  toolUseId: string,
  surface: RenderSurface,
  ui: Elements,
  mark?: string,
): Promise<RenderElement | null> {
  const cards = await read($, memberOf(byCall, { requestId: toolUseId }))
  if (cards.length === 0) {
    return null
  }
  const { Box } = ui
  const now = await $.clock.now()

  // Running agents live in the "Agentes" pane only; once stopped, the folded card stays on its own row,
  // and a line at the bottom of the chat says it ended (VS Code does not let a mod redraw its notices).
  const card = (run: AgentRun) => (run.status === 'running' ? <Box key={run.id} /> : finishedCard(ui, run, now, '•', mark))

  return (
    <Box flexDirection="column" paddingLeft={mark === undefined ? 0 : 4}>
      {cards.map(card)}
    </Box>
  )
}

/** `✓ implementer · sonnet-5-5 · 8m 51s · Añadir fuzzing… · 26 calls · 26 commands · 3 failed`. */
export function finishedLine(run: AgentRun): string {
  const glyph = run.status === 'done' ? '✓' : run.status === 'aborted' ? '■' : '✗'
  return [
    `${glyph} ${agentName(run)}`,
    shortModel(run.model),
    formatDuration(run.durationMs ?? 0),
    clip(run.mission ?? run.description, 60),
    countsLine(run),
  ]
    .filter(Boolean)
    .join(' · ')
}

/** A finished agent's card: the header plus what it did (Codex's collapsed group). */
function finishedCard(ui: Elements, run: AgentRun, now: number, frame: string, mark?: string) {
  const { Box, Text } = ui
  const summary = summaryOf(run)
  return (
    <Box key={run.id} flexDirection="column">
      {runHeader(ui, run, now, frame, run.mission ?? run.description, false, mark)}
      {summary === '' ? null : (
        <Text dimColor wrap="truncate">
          {mark === undefined ? '  ' : '    '}
          {run.status === 'done' ? summary : `${OUTCOME[run.status].word} · ${summary}`}
        </Text>
      )}
    </Box>
  )
}

/** Opens the "Agentes" pane and records whether a surface placed it. Never throws. */
async function openDock($: EngineInterface): Promise<void> {
  // The surface draws the title bar; its text at least says how many run (an open id only retitles).
  const running = (await read($, runs)).filter(run => run.status === 'running').length
  const title = `Agentes · ${running}`
  const opened = await $.ui.open({ id: DOCK, title }).catch(() => ({ isPlaced: false }))
  await update($, docked, () => opened.isPlaced)
}

/** Closes the pane once no agent runs: they all sit in the chat again. Never throws. */
async function closeDockWhenIdle($: EngineInterface): Promise<void> {
  if ((await read($, runs)).some(run => run.status === 'running')) {
    // Still some running: retitle with the new count, if the pane is up.
    if (await read($, docked)) {
      await openDock($)
    }
    return
  }
  await update($, docked, () => false)
  await $.ui.close({ id: DOCK }).catch(() => undefined)
}
