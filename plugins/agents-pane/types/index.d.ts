// State contract of the agents-pane mod: what it keeps in `$.state` (survives hot reloads).

/** Where one subagent run stands. */
export type AgentRunStatus = 'running' | 'done' | 'failed' | 'aborted'

/** What a tool call does, as the card groups it: `Explored 3 files, 2 searches`. */
export type StepKind = 'read' | 'list' | 'search' | 'edit' | 'run' | 'web' | 'agent' | 'other'

/** One tool call of a subagent. */
export type Step = {
  /** The call's `tool_use_id`. */
  id: string
  kind: StepKind
  /** `Read register.tsx`, `Search "foo" in src/`, `Run npm test`. */
  label: string
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
  /** Resolved model id, e.g. `claude-haiku-5-5`. */
  model: string
  status: AgentRunStatus
  /** Clock time of the spawn, for the live elapsed time. */
  startedAt: number
  /** Wall time of the run (from `turn.complete`), set when it ends. */
  durationMs?: number
  /** Calls still running, oldest first. */
  current: Step[]
  /** Finished calls per kind, for the summary line. */
  counts: Partial<Record<StepKind, number>>
  /** Finished calls that failed (absent on runs stored before it was counted). */
  failures?: number
}

declare module 'claude-code' {
  interface PluginState {
    'agents-pane': { runs: Shaped<AgentRun[]> }
  }
}
