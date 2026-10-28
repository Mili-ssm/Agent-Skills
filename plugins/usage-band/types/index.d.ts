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
  /** Busy time in ms: the sum of the main loop's turn durations. */
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
  /**
   * Busy time of the finished main-loop turns, in ms: the sum of their `durationMs`. Idle time between
   * turns is not counted. Negative only while a turn that began before the cycle runs on (the person
   * typed over it): the part before the prompt is taken off when that turn completes.
   */
  busyMs: number
  /** Clock time (ms) the running main-loop turn started at; `null` while the main loop is idle. */
  runningSince: number | null
  /** Main-loop tool calls other than `Skill` and `Agent`; a subagent's own calls are not counted. */
  tools: number
  /** Main-loop `Skill` calls. */
  skills: number
  /** Main-loop `Agent` calls. */
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
