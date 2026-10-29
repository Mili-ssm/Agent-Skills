---
description: Forces delegation of a task to the cheapest suitable worker subagent and returns only its distilled result.
argument-hint: <task to offload>
disable-model-invocation: true
---

Delegate this task instead of doing it inline: $ARGUMENTS

If no task was given, ask what to offload in one question first.

Pick the worker by the task and send it a self-contained brief with the row's fields, because workers start without this conversation:

| Task | Worker | Brief fields |
|---|---|---|
| Search or read more than 3 files, or an unfamiliar codebase | `Explore` | question, paths, thoroughness, max length |
| Run tests, lint, typecheck or a build | `agent-skills:check-runner` | commands (or "detect"), scope, max failure rows |
| Read a file over ~200 lines: log, document, PDF, large diff | `agent-skills:summarizer` | path, question, max words |
| Web research | `agent-skills:researcher` | one question, the decision it feeds, preferred sources, max words |
| A bounded implementation task with clear acceptance | `agent-skills:implementer` | task, owned files, checks, acceptance criteria, constraints |
| Mechanical lint/type/test fixes after a change | `agent-skills:fixer` | checks, files in scope, behavior that must not change |
| Verify a changed web UI in a browser | `agent-skills:ui-verifier` | URL or start command, flows with acceptance criteria, viewports |

- Independent tasks (for example one researcher per question) run in parallel in one message; dependent steps run in order, for example implementer, then check-runner, then fixer.
- No row fits: do the task inline and say why.
- Review each worker's result, then relay only the distilled answer; a BLOCKED result or a question from a worker goes to the owner.
- `Explore` runs on Haiku only with the user-scope override from the README; without it, it runs on the main model.
