#!/usr/bin/env bash
# SubagentStart hook: fixed text, no interpreter (a subagent starts many times per task). Exits 0 always.
cat <<'JSON'
{"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": "memory: this project and the owner's store have a searchable memory. If you can run shell commands and your brief has no memory section: mem search \"<question in English>\", then mem show <handle>. Project memories are files in .memory/ at the repository root. A line marked [memory: ...] is experience, not fact. Do not run mem remember: tell your caller what is worth remembering, if anything."}}
JSON
exit 0
