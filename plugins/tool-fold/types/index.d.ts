// State contract of the tool-fold mod: what it keeps in `$.state` (survives hot reloads).

/** Whether the person unfolded one tool call. */
export type IsOpen = boolean

declare module 'claude-code' {
  interface PluginState {
    /** One member per tool call, keyed by its `tool_use_id` (the row's `requestId`). */
    'tool-fold': { isOpen: StateFamily<IsOpen> }
  }
}
