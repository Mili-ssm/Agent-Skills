---
name: "perf-review"
description: "Runs the performance-analyst agent to baseline, profile and report measured improvements; optimizes only when asked."
argument-hint: "[optimize] <target: endpoint, command or page> [metric/target]"
disable-model-invocation: true
---

Dispatch the `performance-analyst` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, and the workload command, dataset and target, because it starts without this conversation.
- Mode: `Mode: optimize` only when the first word of the arguments is `optimize`; otherwise `Mode: report`. The rest of the arguments is the task.
- No arguments: use the endpoint, command or page from this conversation; if there is none, ask for it in one question before dispatching.
- In `optimize` mode the brief also states the paths it may edit, the decisions already taken and why, the command that proves the result, and to stop and report when the brief does not fit the code.
- If it stops for a missing input (runnable workload command, data, target), ask the owner for exactly that, then dispatch once more with it added.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
