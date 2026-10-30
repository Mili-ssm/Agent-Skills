---
name: "qa-review"
description: "Runs the qa-engineer agent to assess a test suite, design test cases, root-cause flaky tests or run mutation testing; writes tests only with 'write'."
argument-hint: "[assess|design|flaky|strength|write] [scope]"
disable-model-invocation: true
---

Dispatch the `qa-engineer` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the task plus the files, plan or constraints from this conversation that it refers to, because it starts without this conversation.
- Mode: if the first word of the arguments is one of `assess`, `design`, `flaky`, `strength` or `write`, start the brief with `Mode: <word>`; the rest of the arguments is the task. Only that first word selects `write`; never choose it yourself.
- No arguments: use the target from this conversation; otherwise leave the agent's defaults (mode `assess`) and say which you assumed.
- In `write` mode the brief also states the paths it may edit, the decisions already taken and why, the command that proves the result, and to stop and report when the brief does not fit the code.
- If it stops for a missing input (named area for `write`), ask the owner for exactly that, then dispatch once more with it added.
- Relay its report in full, dropping no findings; then list the decisions or open questions it leaves to the owner, or say there are none.
