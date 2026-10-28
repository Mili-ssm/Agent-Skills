// State contract of the usage-band mod: what it keeps in `$.state` (survives hot reloads).

/** Tokens of one model family (`opus`, `sonnet`, `haiku`, ...). */
export type ModelTokens = {
  /** Every token the requests counted: input, cache reads and writes, output. */
  total: number
  output: number
}

/** Tokens per model family. */
export type Tally = Record<string, ModelTokens>

/** One answer (main-loop turn) or the session so far. */
export type Usage = {
  /** Wall time in ms: the answer's, or the sum of the session's answers. */
  durationMs: number
  /** Answers counted (1 for one answer). */
  turns: number
  byModel: Tally
}

declare module 'claude-code' {
  interface PluginState {
    'usage-band': {
      last: Shaped<Usage | null>
      session: Shaped<Usage>
      isHidden: boolean
    }
  }
}
