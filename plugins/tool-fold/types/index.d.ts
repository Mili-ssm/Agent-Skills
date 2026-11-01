// State contract of the tool-fold mod: what it keeps in `$.state` (survives hot reloads).

/** Where one subagent run stands. */
export type AgentRunStatus = 'running' | 'done' | 'failed' | 'aborted'

/** What a tool call does, as the card groups it: `Explored 3 files, 2 searches`. */
export type StepKind = 'read' | 'list' | 'search' | 'edit' | 'run' | 'web' | 'agent' | 'skill' | 'other'

/** One tool call of a subagent. */
export type Step = {
  /** The call's `tool_use_id`. */
  id: string
  kind: StepKind
  /** `Read register.tsx`, `Search "foo" in src/`, `Run npm test`. */
  label: string
  /** A few words on what it does: the model's own description of a command, else Haiku's. */
  detail?: string
  /** Clock time it started, for its duration. */
  startedAt?: number
  status: 'running' | 'done' | 'failed'
}

/** One subagent spawned in this session, drawn as a card on its Agent call's row. */
export type AgentRun = {
  /** Agent id from `agent.spawn` (the same id `tool.call` and `turn.complete` carry). */
  id: string
  /** The Agent call whose transcript row draws this run (a workflow's agents share one). */
  toolUseId: string
  /** Agent type: `Explore`, `general-purpose`, `agent-skills:researcher`, ... */
  type: string
  /** The Agent call's short task description. */
  description: string
  /** One plain-language sentence (Spanish) of what the agent was asked, from Haiku; absent until it answers. */
  mission?: string
  /** Resolved model id, e.g. `claude-haiku-5-5`. */
  model: string
  status: AgentRunStatus
  /** Clock time of the spawn, for the live elapsed time. */
  startedAt: number
  /** Wall time of the run (from `turn.complete`), set when it ends. */
  durationMs?: number
  /** Calls still running, oldest first. */
  current: Step[]
  /** The last two finished calls: the card shows the newest two of these and the live ones. */
  recent: Step[]
  /** Finished calls per kind, for the summary line. */
  counts: Partial<Record<StepKind, number>>
  /** Finished calls that failed (absent on runs stored before it was counted). */
  failures?: number
  /** The agent's own task list (TodoWrite or Task tools): done of total, and the task ids finished. */
  todo?: { done: number; total: number; completed: string[] }
  /** Its finished calls, newest last (bounded): what each did, how long it took, whether it worked. */
  history?: { what: string; ms: number; ok: boolean }[]
  /** Distinct files its edits touched, for the finished card's count. */
  files?: string[]
  /** Skills it used, by name. */
  skills?: string[]
  /** Haiku's rough percentage done, for an agent with no task list, shown in the pane while it runs. */
  estimate?: number
  /** How long agents of its type took before (median of the remembered ones, and how many): a reference. */
  typical?: { ms: number; of: number }
  /** Haiku found no measurable end (a watcher): the pane shows time against `typical` instead. */
  isOpenEnded?: boolean
  /** The main agent's wait has no estimate: its card draws the empty track only. */
  isTrackOnly?: boolean
  /** Where the wait's estimate came from, drawn as a dim icon before the right datum: `✦` Claude's message, `⟲` similar runs, `?` Haiku's guess. */
  etaSource?: EtaSource
  /** Typical duration of similar past agents (ms), from the agent memory: progress is elapsed over it. */
  etaMs?: number
  /** The main agent's wait ran past its estimate: the card says so instead of the time left. */
  isOverdue?: boolean
  /** Clock time of the last estimate asked for (one per call, at most every 30 s). */
  estimatedAt?: number
  /** Runs in the background (the main loop does not wait on it). */
  background?: boolean
}


/** What a background task is: a shell command, a monitor or an agent. */
export type WaitKind = 'shell' | 'monitor' | 'agent'

/** Background work the main loop launched and still waits on, drawn as a synthetic main-agent run on the agent card. */
export type WaitTask = {
  /** The task id its launch answered (a shell's `backgroundTaskId`, a monitor's `taskId`, an agent's id). */
  id: string
  kind: WaitKind
  /** What the estimate calls the same work: `bash:cargo bench`. */
  key: string
  /** What the card's mission says it waits on, from the model's description or the command. */
  label: string
  /** True once `label` came from Haiku (the call had no description). */
  isLabelGuessed?: boolean
  /** An agent's type, else its description: what the card names when it waits on this one agent. */
  name?: string
  /** Clock time it launched, for the elapsed time. */
  startedAt: number
  /** The estimate in ms; absent with none. */
  etaMs?: number
  /** Where `etaMs` came from; a stronger source (message over similar over guess) replaces a weaker one. */
  etaSource?: EtaSource
}

/** Claude's own message, similar finished runs, or Haiku's guess from the command. */
export type EtaSource = 'message' | 'similar' | 'guess'

/** One finished wait, remembered across sessions: its label and how long it took. */
export type WaitSample = { summary: string; durationMs: number; at: number }

/** One call of a group, in the order the model made them. */
export type GroupCall = {
  /** The call's `tool_use_id`. */
  id: string
  tool: string
  /** The name a group line lists it by: a skill's or an agent type's name, else the tool's (absent in groups stored before it). */
  tag?: string
  /** What the folded row says it does. */
  label: string
  status: 'running' | 'done' | 'failed'
}

/** A run of main-loop tool calls with no reply text between them. */
export type ToolRun = {
  /** `g-` and the first call's id. */
  id: string
  calls: GroupCall[]
  /** True once reply text, an Agent call or the turn's end closed it. */
  isClosed: boolean
  /** One plain-language sentence (Spanish) for the whole run, from Haiku once closed. */
  summary?: string
  /** Clock time it opened and closed, for its duration (absent in runs stored before them). */
  startedAt?: number
  endedAt?: number
}

declare module 'claude-code' {
  interface PluginState {
    'tool-fold': {
      /** Unfolded or not, keyed by a call's `tool_use_id` or a group's id. */
      isOpen: StateFamily<boolean>
      /** The group a call belongs to (its id), keyed by the call's `tool_use_id`. */
      groupOf: StateFamily<string>
      /** A group, keyed by its id. */
      group: StateFamily<ToolRun | null>
      /** The id of the group new calls join, or null between runs. */
      current: string | null
      /** Every subagent of the session, newest last. */
      runs: Shaped<AgentRun[]>
      /** The runs drawn on one Agent call's row, keyed by its tool_use_id. */
      byCall: StateFamily<Shaped<AgentRun[]>>
      /** Clock time of the last tick, read by what shows a live elapsed time. */
      now: number
      /** Background work the main loop waits on, oldest first. */
      waits: Shaped<WaitTask[]>
      /** Clock time the main loop's turn ended; null while a turn runs. */
      idleAt: number | null
      /** Bumped each second while the main agent's wait shows. */
      waitTick: number
      /** True while the "Agentes" pane is placed: running agents draw there, one line each in the chat. */
      docked: boolean
    }
  }
}
