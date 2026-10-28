// State contract of the tool-fold mod: what it keeps in `$.state` (survives hot reloads).

declare module 'claude-code' {
  interface PluginState {
    /** Tool calls the person unfolded, by `tool_use_id`, newest last. */
    'tool-fold': { unfolded: Shaped<string[]> }
  }
}

export {}
