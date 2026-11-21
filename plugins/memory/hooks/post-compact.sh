#!/usr/bin/env bash
# PostCompact hook: `mem` checks the handoff block of the summary and prints the lines that tell the agent what
# is missing (nothing when the block is complete), and logs counts only. The hook's JSON on standard input goes to
# `mem`. Hook processes do not get the variables that session-env.sh exports, so the options are passed on here.
# Silent and always exit 0, also when uv or mem fail: a failing hook would disturb every compaction.
[ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ] && export MEM_STORE="$CLAUDE_PLUGIN_OPTION_STORE"
if [ -z "${CLAUDE_PLUGIN_OPTION_STORE:-}" ]; then # no option: the default store, made by session-env.sh
  data="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
  [ -n "$data" ] && [ -f "$data/agent-memory/store/mem-store.yaml" ] && export MEM_STORE="$data/agent-memory/store"
fi
[ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 0
if command -v timeout >/dev/null 2>&1; then
  timeout 4 "$here/../bin/mem" compact-log --hook 2>/dev/null || true
else
  "$here/../bin/mem" compact-log --hook 2>/dev/null || true
fi
exit 0
