// State contract of the tool-fold mod: what it keeps in `$.state` (survives hot reloads).

/** One call of a group, in the order the model made them. */
export type GroupCall = {
  /** The call's `tool_use_id`. */
  id: string
  tool: string
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
    }
  }
}
