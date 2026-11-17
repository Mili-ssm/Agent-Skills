#!/usr/bin/env bash
# SessionStart hook: hands the plugin's `store` option to the session's shell
# commands (they do not receive plugin options) and to the config file `mem`
# falls back on. Silent and always exit 0: a failing hook would disturb every session.
store="${CLAUDE_PLUGIN_OPTION_STORE:-}"
[ -n "$store" ] || exit 0
{
  dir="${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory"
  mkdir -p "$dir" && printf '%s\n' "$store" > "$dir/store"
} >/dev/null 2>&1
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  printf 'export MEM_STORE=%q\n' "$store" >> "$CLAUDE_ENV_FILE" 2>/dev/null
fi
exit 0
