---
name: "consistency-audit"
description: "Runs the consistency-auditor agent to find contradictions, ambiguities and stale decisions between code and docs."
---

Arguments hint: [project|feature|change] [scope]

Dispatch the `consistency-auditor` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- Mode: if the first word of the arguments is one of `project`, `feature` or `change`, start the brief with `Mode: <word>`; the rest of the arguments is the task.
- No arguments: use the target from this conversation; otherwise leave the agent's defaults (mode `project`, whole repo) and say which you assumed.
- If it stops for a missing input (feature name for `feature`, change description for `change`), ask the owner for exactly that, then dispatch once more with it added.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
