#!/usr/bin/env bash
# SessionStart hook: prints the memory index that opens the session. The hook's JSON on standard input
# goes to `mem`, which finds the project from its `cwd`. Hook processes do not get the variables that
# session-env.sh exports for shell commands, so the options are passed on here.
# Silent and always exit 0, also when uv or mem fail: a failing hook would disturb every session.
[ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ] && export MEM_STORE="$CLAUDE_PLUGIN_OPTION_STORE"
if [ -z "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then # no option: the default store, made by session-env.sh
  data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] && [ -d "$data/agent-memory/store" ] && export MEM_STORE="$data/agent-memory/store"
fi
[ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 0
"$here/../bin/mem" session-index --hook 2>/dev/null || true
exit 0
