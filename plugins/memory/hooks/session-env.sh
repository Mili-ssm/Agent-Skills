#!/usr/bin/env bash
# SessionStart hook: hands the plugin's `store` option to the session's shell
# commands (they do not receive plugin options) and to the config file `mem`
# falls back on. Silent and always exit 0: a failing hook would disturb every session.
store="${CLAUDE_PLUGIN_OPTION_STORE:-}"
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory"
if [ -z "$store" ]; then
  # The option was cleared: the fallback file must not keep an old store alive.
  rm -f "$cfg/store" 2>/dev/null
  exit 0
fi
{
  mkdir -p "$cfg" && printf '%s\n' "$store" > "$cfg/store"
} >/dev/null 2>&1
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  { printf 'export MEM_STORE=%q\n' "$store" >> "$CLAUDE_ENV_FILE"; } 2>/dev/null
fi
exit 0
