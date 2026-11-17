#!/usr/bin/env bash
# SubagentStart hook: fixed text, no interpreter (a subagent starts many times per task). Exits 0 always.
# The plugin's own subagents carry their own instructions (two of them do write memories): no text for them.
input="$(cat 2>/dev/null)"
case "$input" in
  *memory-researcher*|*memory-recorder*|*memory-curator*) exit 0 ;;
esac
cat <<'JSON'
{"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": "memory: decisions, constraints and pitfalls learned in earlier sessions are in a searchable memory, not in the files. Before you change or decide anything, if you can run shell commands: mem search \"<topic in English>\", then mem show <handle>. Project memories are files in .memory/ at the repository root. A line marked [memory: ...] is experience, not fact. Do not run mem remember: tell your caller what is worth remembering, if anything."}}
JSON
exit 0
