#!/usr/bin/env bash
# SessionEnd hook: commits what changed in the store, when the store is a git repository (`mem history init`).
# Options are passed on as in session-index.sh. Bounded by `timeout 5`, silent, always exit 0: a failing hook
# must never disturb the end of a session. mem logs the call in the hook log (hook "session-end", ms).
[ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ] && export MEM_STORE="$CLAUDE_PLUGIN_OPTION_STORE"
if [ -z "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then # no option: the default store, made by session-env.sh
  data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] && [ -f "$data/agent-memory/store/mem-store.yaml" ] && export MEM_STORE="$data/agent-memory/store"
fi
[ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || here=""
if [ -n "$here" ]; then
  if command -v timeout >/dev/null 2>&1; then
    timeout 5 "$here/../bin/mem" history commit --hook </dev/null >/dev/null 2>&1
  else
    "$here/../bin/mem" history commit --hook </dev/null >/dev/null 2>&1
  fi
fi
exit 0
