// State contract of the agents-pane mod: what it keeps in `$.state` (survives hot reloads).

/** Where one subagent run stands. */
export type AgentRunStatus = 'running' | 'done' | 'failed' | 'aborted'

/** One subagent spawned in this session, as the pane lists it. */
export type AgentRun = {
  /** Agent id from `agent.spawn` (the same id `$.agent.list()` and `turn.complete` carry). */
  id: string
  /** Agent type: `Explore`, `general-purpose`, `agent-skills:researcher`, ... */
  type: string
  /** The Agent call's short task description. */
  description: string
  /** Resolved model id, e.g. `claude-haiku-5-5`. */
  model: string
  status: AgentRunStatus
  /** Wall time of the last run (from `turn.complete`), set when it ends. */
  durationMs?: number
}

declare module 'claude-code' {
  interface PluginState {
    'agents-pane': { runs: Shaped<AgentRun[]> }
  }
}
