#!/usr/bin/env bash
# SubagentStart hook: fixed text, no interpreter (a subagent starts many times per task). Exits 0 always.
# The plugin's own subagents carry their own instructions (some of them write to the memory): no text for them.
input="$(cat 2>/dev/null)"
case "$input" in
  *memory-researcher*|*memory-recorder*|*memory-curator*|*memory-synthesizer*|*memory-status-checker*) exit 0 ;;
esac
# Codex: when `mem` is not a command, name the plugin's own launcher (the root with `\` and `"` JSON-escaped).
cmd=mem
if [ "${MEM_HOST:-}" = codex ] && ! command -v mem >/dev/null 2>&1; then
  cmd="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/bin/mem"
  cmd="${cmd//\\/\\\\}"
  cmd="${cmd//\"/\\\"}"
fi
cat <<JSON
{"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": "memory: decisions, constraints and pitfalls learned in earlier sessions are in a searchable memory, not in the files. Before you change or decide anything, if you can run shell commands: ${cmd} search \"<topic in English>\", then ${cmd} show <handle>. Project memories are files in .memory/ at the repository root. A line marked [memory: ...] is experience, not fact. Do not run ${cmd} remember: tell your caller what is worth remembering, if anything."}}
JSON
exit 0
