---
name: "ux-review"
description: "Runs the ux-reviewer agent on a running UI or its templates and returns severity-rated usability and accessibility findings with evidence."
---

Arguments hint: <url or templates path> [flows]

Dispatch the `ux-reviewer` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, and the start command and login or test data, because it starts without this conversation.
- No arguments: use the URL or templates path from this conversation; if there is none, ask for it in one question before dispatching.
- If it stops for a missing input (URL or templates path), ask the owner for exactly that, then dispatch once more with it added.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
