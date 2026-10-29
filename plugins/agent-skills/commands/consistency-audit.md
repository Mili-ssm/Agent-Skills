---
description: Runs the consistency-auditor agent to find contradictions, ambiguities and stale decisions between code and docs.
argument-hint: [project|feature|change] [scope]
disable-model-invocation: true
---

Dispatch the `agent-skills:consistency-auditor` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: $ARGUMENTS

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- No arguments: use the target from this conversation; otherwise leave the agent's defaults (mode `project`, whole repo) and say which you assumed.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
