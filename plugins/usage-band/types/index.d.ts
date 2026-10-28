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
  /** Wall time in ms of the closed cycles: from the person's first prompt to their last. */
  durationMs: number
  /** Main-loop turns counted (shown as "answers"). */
  turns: number
  byModel: Tally
}

/**
 * One interaction cycle: from a person's prompt to the next one. It spans every main-loop turn between
 * them (a background agent's hand-back starts another turn inside the same cycle).
 */
export type Cycle = {
  /** Tokens of the main loop and of every subagent that ended in the cycle. */
  byModel: Tally
  /** Clock time (ms) of the person's prompt that opened the cycle; `null` before their first prompt. */
  startedAt: number | null
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
