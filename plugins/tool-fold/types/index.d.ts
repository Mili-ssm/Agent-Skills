// State contract of the tool-fold mod: what it keeps in `$.state` (survives hot reloads).

/** The id a tool call's row and result carry (`tool_use_id`). */
export type ToolUseId = string

declare module 'claude-code' {
  interface PluginState {
    /** Tool calls the person unfolded, newest last. */
    'tool-fold': { unfolded: Shaped<ToolUseId[]> }
  }
}
