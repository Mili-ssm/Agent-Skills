---
name: "perf-review"
description: "Runs the performance-analyst agent to baseline, profile and report measured improvements; optimizes only when asked."
---

Arguments hint: [optimize] <target: endpoint, command or page> [metric/target]

Dispatch the `performance-analyst` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- No arguments: use the endpoint, command or page from this conversation; if there is none, ask for it in one question before dispatching.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
