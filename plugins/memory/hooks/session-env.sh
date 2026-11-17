#!/usr/bin/env bash
# SessionStart hook: hands the plugin's `store` and `memories` options to the session's shell
# commands (they do not receive plugin options) and to the config files `mem` falls back on.
# Silent and always exit 0: a failing hook would disturb every session.
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory"
handle() { # <option value> <config file name> <variable>
  if [ -z "$1" ]; then
    # The option was cleared: the fallback file must not keep an old value alive.
    rm -f "$cfg/$2" 2>/dev/null
    return 0
  fi
  { mkdir -p "$cfg" && printf '%s\n' "$1" > "$cfg/$2"; } >/dev/null 2>&1
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    { printf 'export %s=%q\n' "$3" "$1" >> "$CLAUDE_ENV_FILE"; } 2>/dev/null
  fi
  return 0
}
handle "${CLAUDE_PLUGIN_OPTION_STORE:-}" store MEM_STORE
handle "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" memories MEM_MEMORIES
exit 0
