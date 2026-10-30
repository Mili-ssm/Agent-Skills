---
name: "offload"
description: "Forces delegation of a task to the cheapest suitable worker subagent and returns only its distilled result."
argument-hint: "<task to offload>"
disable-model-invocation: true
---

Delegate this task instead of doing it inline: <the arguments the user gave with this command; empty if none>

If no task was given, ask what to offload in one question first.

Pick the worker by the task and send it a self-contained brief with the row's fields, because workers start without this conversation. Every brief also carries what this conversation knows and the worker cannot see: decisions already taken, each with its reason; what it must not touch; when to stop and report a gap instead of improvising; the report's format and max length. State the what, the limits and the check, not each step.

| Task | Worker | Brief fields |
|---|---|---|
| Search or read more than 3 files, or an unfamiliar codebase | `explore` (built-in agent) | question, paths, thoroughness, max length |
| Run tests, lint, typecheck, a build or another long read-only command | `check-runner` | commands (or "detect"), scope, result wanted (failures, numbers or last lines verbatim), max rows |
| Read a file over ~200 lines (log, document, PDF, large diff, source), map it or pull one part out | `summarizer` | path, mode (`answer` + question, `outline`, `extract` + what), max length |
| Web research | `researcher` | one question, the decision it feeds, preferred sources, max words |
| A bounded implementation task with clear acceptance | `implementer` | task, owned files, checks, acceptance criteria, constraints |
| Mechanical lint/type/test fixes after a change | `fixer` | checks, files in scope, behavior that must not change |
| Verify a changed web UI in a browser | `ui-verifier` | URL or start command, flows with acceptance criteria, viewports |

- Long runs go in the background, so this conversation keeps working until the result arrives.
- Independent tasks (for example one researcher per question) run in parallel in one message; dependent steps run in order, for example implementer, then check-runner, then fixer.
- No row fits: do the task inline and say why.
- The design is still open (two valid approaches, an unsettled contract): settle it with the owner first; a worker would pick one silently.
- Review each worker's result, then relay only the distilled answer; a BLOCKED result or a question from a worker goes to the owner.

