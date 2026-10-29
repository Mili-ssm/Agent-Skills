---
description: Runs the pre-mortem agent on a plan or spec before execution and returns failure stories, risks, amendments and kill criteria.
argument-hint: [plan path]
disable-model-invocation: true
---

Dispatch the `agent-skills:pre-mortem` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: $ARGUMENTS

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- No arguments: use the plan under discussion in this conversation; otherwise leave the agent's default (the only plan file under `docs/plans/`, `docs/superpowers/plans/`, `plans/` or `specs/`) and say which you assumed.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
