---
description: Runs the prompt-engineer agent to review skills, agents, commands, system prompts, tool descriptions or CLAUDE.md for LLM behavior; read-only.
argument-hint: [paths or plugin] [target models] [trace or symptom]
disable-model-invocation: true
---

Dispatch the `agent-skills:prompt-engineer` subagent with the task below instead of doing its work inline, because it runs with its own model and tools in a fresh context and returns only a report.

Task: $ARGUMENTS

- Brief it self-contained: the files in scope, the target models, the symptom or trace and the wanted behavior from this conversation, because it starts without this conversation.
- No arguments: use the prompt files changed or discussed in this conversation; with none, the repo's skills, agents, commands and CLAUDE.md/AGENTS.md; say which you assumed.
- If it stops for a missing input (files or plugin in scope), ask the owner for exactly that, then dispatch once more with it added.
- Relay its report in full, dropping no findings; then list the decisions it leaves to the owner, or say there are none.
