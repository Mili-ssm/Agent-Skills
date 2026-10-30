---
name: "arch-review"
description: "Runs the architect agent on a scope, design or goal and returns its C4 map, findings, options and ADR drafts."
argument-hint: "[assess|review|propose] [scope or goal]"
disable-model-invocation: true
---

Dispatch the `architect` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- No arguments: use the target from this conversation; otherwise leave the agent's defaults (mode `assess`, whole repo) and say which you assumed.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
