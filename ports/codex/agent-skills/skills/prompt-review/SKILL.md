---
name: "prompt-review"
description: "Runs the prompt-engineer agent to review skills, agents, commands, system prompts, tool descriptions or CLAUDE.md for LLM behavior; read-only."
---

Arguments hint: [paths or plugin] [target models] [trace or symptom]

Dispatch the `prompt-engineer` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: <the arguments the user gave with this command; empty if none>

- Brief it self-contained: the files in scope, the target models, the symptom or trace and the wanted behavior from this conversation, because it starts without this conversation.
- No arguments: use the prompt files changed or discussed in this conversation; with none, the repo's skills, agents, commands and CLAUDE.md/AGENTS.md; say which you assumed.
- Relay its report in full, dropping no findings; then list the decisions it leaves to the owner, or say there are none.
