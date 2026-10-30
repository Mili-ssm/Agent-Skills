---
name: "doc-audit"
description: "Runs the doc-curator agent to verify docs against code and compress them; edits only with 'apply'."
---

Arguments hint: [audit|apply] [paths]

Dispatch the `doc-curator` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- Mode: `Mode: apply` only when the first word of the arguments is `apply`; otherwise `Mode: audit`, and end the relay with "rerun with `apply` to write these edits". The rest of the arguments is the task.
- No arguments: use the target from this conversation; otherwise `Mode: audit` (changes no files) on root Markdown, `docs/` and CLAUDE.md/AGENTS.md, and say which you assumed.
- In `apply` mode the brief also states the paths it may edit, the decisions already taken and why, the command that proves the result, and to stop and report when the brief does not fit the code.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
