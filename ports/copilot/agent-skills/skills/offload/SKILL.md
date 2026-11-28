---
name: "offload"
description: "Forces delegation of a task to the cheapest suitable worker subagent and returns only its distilled result."
argument-hint: "<task to offload>"
disable-model-invocation: true
---

Delegate this task instead of doing it inline: <the arguments the user gave with this command; empty if none>

If no task was given, ask what to offload in one question first.

Pick the worker by the task and send it a brief that stands on its own with the files it names, with the row's fields, because workers start without this conversation. Every brief also carries what only this conversation knows: decisions already taken, each with its reason, and what the worker must not touch. Name a file the worker can open (a committed plan task, a spec, a commit range) instead of restating it; every worker already has its stop rule and report format, so state one only to change it. State the what, the limits and the check, not each step.

| Task | Worker | Brief fields |
|---|---|---|
| Search or read more than 3 files, or an unfamiliar codebase | `explore` (built-in agent) | question, paths, thoroughness, length (Explore has no report format of ours) |
| Run tests, lint, typecheck, a build or another long read-only command | `check-runner` | commands (or "detect"), scope, result wanted (failures, numbers or last lines verbatim), max rows |
| Read a file over ~200 lines (log, document, PDF, large diff, source), map it or pull one part out | `summarizer` | path, mode (`answer` + question, `outline`, `extract` + what) |
| Web research | `researcher` | one question, the decision it feeds, preferred sources, max words |
| A bounded implementation task with clear acceptance, including a plan-loop fix round | `implementer` | task, owned files, checks, acceptance criteria, constraints; for a plan-loop fix round, reported material findings and their evidence (see Routing) |
| Mechanical lint/type/test fixes after a change | `fixer` | checks, files in scope, behavior that must not change |
| Verify a changed web UI in a browser | `ui-verifier` | URL or start command, flows with acceptance criteria, viewports |
| Review what changed in the project since its last review (code, docs, files, a deletion, an image description) | `skeptical-reviewer` | paths, diff, commit range or task file (named, not pasted), intent, owner rules not already in `CLAUDE.md` or `AGENTS.md`, what is already verified, round (1 or 2; round 2 only when the fix reaches beyond the findings: it touches a file or behavior no finding named), for a process review, the rules that applied and the steps taken, each with its evidence, findings already rejected; a change already reviewed is not sent again |

- Long runs go in the background, so this conversation keeps working until the result arrives.
- Independent tasks (for example one researcher per question) run in parallel in one message; dependent steps run in order, for example implementer, then check-runner, then fixer.
- No row fits: do the task inline and say why.
- The design is still open (two valid approaches, an unsettled contract): settle it with the owner first; a worker would pick one silently.
- Review each worker's result, then relay only the distilled answer; a BLOCKED result or a question from a worker goes to the owner.

