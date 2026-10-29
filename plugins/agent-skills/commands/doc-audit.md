---
description: Runs the doc-curator agent to verify docs against code and compress them; edits only with 'apply'.
argument-hint: [audit|apply] [paths]
disable-model-invocation: true
---

Dispatch the `agent-skills:doc-curator` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: $ARGUMENTS

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- No arguments: use the target from this conversation; otherwise leave the agent's defaults (mode `audit`, which changes no files, on root Markdown, `docs/` and CLAUDE.md/AGENTS.md) and say which you assumed.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
