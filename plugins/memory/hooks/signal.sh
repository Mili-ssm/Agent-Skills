#!/usr/bin/env bash
# PreToolUse hook (matcher Agent): appends a signal of related memories to a subagent's brief. The hook's JSON on
# standard input goes to `mem`, which prints updatedInput or nothing; no permission decision is ever returned.
# Hook processes do not get the variables that session-env.sh exports, so the options are passed on here.
# Silent and always exit 0, also when uv or mem fail: a failing hook would disturb every dispatch.
[ -n "${CLAUDE_PLUGIN_OPTION_STORE:-}" ] && export MEM_STORE="$CLAUDE_PLUGIN_OPTION_STORE"
[ -n "${CLAUDE_PLUGIN_OPTION_MEMORIES:-}" ] && export MEM_MEMORIES="$CLAUDE_PLUGIN_OPTION_MEMORIES"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 0
"$here/../bin/mem" signal --hook 2>/dev/null || true
exit 0
