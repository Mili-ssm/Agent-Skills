---
name: "security-audit"
description: "Runs the security-reviewer agent for a source-to-sink review, STRIDE threat model or design review."
---

Arguments hint: [review|threat-model|design] [scope]

Dispatch the `security-reviewer` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- Mode: if the first word of the arguments is one of `review`, `threat-model` or `design`, start the brief with `Mode: <word>`; the rest of the arguments is the task.
- No arguments: use the target from this conversation; otherwise leave the agent's defaults (mode `review`) and say which you assumed.
- If it stops for a missing input (plan or spec for `design`), ask the owner for exactly that, then dispatch once more with it added.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
