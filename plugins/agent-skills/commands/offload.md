---
description: Forces delegation of a task to the cheapest suitable worker subagent and returns only its distilled result.
argument-hint: <task to offload>
disable-model-invocation: true
---

Delegate this task instead of doing it inline: $ARGUMENTS

Pick the worker by the task, write a self-contained brief (goal, files/paths, commands, acceptance, max length), dispatch it, and relay only its result:

| Task | Worker |
|---|---|
| Search or read code across several files | `Explore` |
| Run tests, lint, typecheck or a build | `agent-skills:check-runner` |
| Read a long log, document, PDF or diff | `agent-skills:summarizer` |
| Web research | `agent-skills:researcher` (one per question, in parallel) |
| A bounded implementation task with clear acceptance | `agent-skills:implementer` |
| Mechanical lint/type/test fixes after a change | `agent-skills:fixer` |

Independent parts go to parallel workers in one message.
