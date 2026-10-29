---
description: Runs the performance-analyst agent to baseline, profile and report measured improvements; optimizes only when asked.
argument-hint: [optimize] <target: endpoint, command or page> [metric/target]
disable-model-invocation: true
---

Dispatch the `agent-skills:performance-analyst` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: $ARGUMENTS

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- No arguments: use the endpoint, command or page from this conversation; if there is none, ask for it in one question before dispatching.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
