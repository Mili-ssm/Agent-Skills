// State contract of the usage-band mod: what it keeps in `$.state` (survives hot reloads).

/** Tokens of one model family (`opus`, `sonnet`, `haiku`, ...). */
export type ModelTokens = {
  /** Every token the requests counted: input, cache reads and writes, output. */
  total: number
  output: number
}

/** Tokens per model family. */
export type Tally = Record<string, ModelTokens>

/** The session so far. */
export type Usage = {
  /** Claude's busy time in ms over the session: every closed busy stretch of every cycle. */
  durationMs: number
  /** Main-loop turns counted (shown as "answers"). */
  turns: number
  byModel: Tally
}

/**
 * One interaction cycle: from a person's prompt to the next one. Its time is Claude's busy time in it: the
 * clock runs while a turn of the main loop or of an agent is open and stops when everything has finished; a
 * background agent's hand-back that wakes the model again adds another busy stretch to the same cycle.
 */
export type Cycle = {
  /** Tokens of the main loop and of every subagent that ended in the cycle. */
  byModel: Tally
  /** Clock time (ms) of the person's prompt that opened the cycle; `null` before their first prompt. */
  startedAt: number | null
  /** Busy time (ms) of the stretches already closed. */
  activeMs: number
  /** Clock time (ms) the open busy stretch began; `null` while Claude is idle. */
  busySince: number | null
  /** True once the cycle's line was printed at an idle moment and nothing ran since. */
  logged: boolean
  /** Every tool call of the main loop and of its agents, `Skill` and `Agent` calls included. */
  calls: number
  /** `Skill` calls, by the main loop or an agent. */
  skills: number
  /** `Agent` calls, by the main loop or an agent. */
  agents: number
}

declare module 'claude-code' {
  interface PluginState {
    'usage-band': {
      session: Shaped<Usage>
      cycle: Shaped<Cycle>
    }
  }
}
