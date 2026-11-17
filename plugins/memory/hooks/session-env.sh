#!/usr/bin/env bash
# SessionStart hook: hands the plugin's `store` and `memories` options to the session's shell
# commands (they do not receive plugin options) and to the config files `mem` falls back on.
# With no `store` option it makes the default store on the first run and hands that one over.
# Silent and always exit 0: a failing hook would disturb every session.
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || here=""
export_var() { # <variable> <value>
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    { printf 'export %s=%q\n' "$1" "$2" >> "$CLAUDE_ENV_FILE"; } 2>/dev/null
  fi
  return 0
}
handle() { # <option value> <config file name> <variable>
  if [ -z "$1" ]; then
    # The option was cleared: the fallback file must not keep an old value alive.
    rm -f "$cfg/$2" 2>/dev/null
    return 0
  fi
  { mkdir -p "$cfg" && printf '%s\n' "$1" > "$cfg/$2"; } >/dev/null 2>&1
  export_var "$3" "$1"
}
default_store() {
  local data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] || return 0
  local dir="$data/agent-memory/store"
  # The marker, not the folder: an init cut short by the time limit is finished on the next start.
  if [ ! -f "$dir/mem-store.yaml" ] && [ -n "$here" ]; then
    if command -v timeout >/dev/null 2>&1; then
      timeout 4 "$here/../bin/mem" init >/dev/null 2>&1 || true   # bounded: a cold cache without network must not hold the session
    else
      "$here/../bin/mem" init >/dev/null 2>&1 || true
    fi
  fi
  [ -f "$dir/mem-store.yaml" ] && export_var MEM_STORE "$dir"
  return 0
}
if [ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then
  handle "$CLAUDE_PLUGIN_OPTION_STORE" store MEM_STORE
else
  # The option was cleared: the fallback file must not keep an old path alive.
  rm -f "$cfg/store" 2>/dev/null
  default_store
fi
handle "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" memories MEM_MEMORIES
# Background settling (option auto_settle, exactly "true"): the variables below are what lets the write path of this
# session's shell commands start a settling run; no variable, no trigger (a trial or a test never has them).
if [ "${CLAUDE_PLUGIN_OPTION_AUTO_SETTLE:-}" = "true" ]; then
  [ -n "$here" ] && . "$here/find-claude.sh" 2>/dev/null
  claude=""
  type find_claude >/dev/null 2>&1 && claude="$(find_claude)"
  export_var MEM_SETTLE_AUTO 1
  export_var MEM_SETTLE_MINUTES "${CLAUDE_PLUGIN_OPTION_AUTO_SETTLE_MINUTES:-30}"
  [ -n "$claude" ] && export_var MEM_SETTLE_CLAUDE "$claude"
  # `settle log` creates the settle state when it is missing and records the memories that exist as judged, so the
  # first write after the option is turned on is not taken as already judged.
  store="${CLAUDE_PLUGIN_OPTION_STORE:-}"
  if [ -z "$store" ]; then
    data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
    [ -n "$data" ] && [ -f "$data/agent-memory/store/mem-store.yaml" ] && store="$data/agent-memory/store"
  fi
  if [ -n "$here" ] && [ -n "$store" ]; then
    if command -v timeout >/dev/null 2>&1; then
      MEM_STORE="$store" MEM_MEMORIES="${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" timeout 3 "$here/../bin/mem" settle log </dev/null >/dev/null 2>&1
    else
      MEM_STORE="$store" MEM_MEMORIES="${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" "$here/../bin/mem" settle log </dev/null >/dev/null 2>&1
    fi
  fi
fi
exit 0
