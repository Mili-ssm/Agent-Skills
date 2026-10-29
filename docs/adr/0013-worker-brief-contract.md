# 0013 Worker brief contract

Status: accepted · Date: 2026-10-29

## Context

The main conversation runs the stronger model and holds the whole context; workers run Haiku or Sonnet, start without the conversation, and cannot ask the owner. The offload policy (ADR 0012) listed a brief's fields as "goal, paths, commands, constraints, acceptance criteria, max report length". It did not name the two things only the main conversation knows: the decisions already taken with their reasons, and what the worker must not touch.

Published practice agrees on the gap:

| Source | Finding |
|---|---|
| Anthropic, multi-agent research system (2025) | Short, vague subagent tasks duplicated work and left gaps; each subagent needs an objective, an output format, tool and source guidance, and clear task boundaries |
| Cognition, "Don't build multi-agents" (2025) | Actions carry implicit decisions; workers that do not see them make conflicting ones |
| Superpowers `writing-plans` | Plans written for an executor with zero context: exact paths, commands with expected output |

Over-specifying has its own costs: a worker follows a wrong plan faithfully, and a plan that already holds the code leaves the worker nothing to save (ADR 0012: a Sonnet main conversation does not delegate to a Sonnet implementer).

## Decision

- `user-config/offload-policy.md` (the single copy, ADR 0012) names the brief's six parts: goal and acceptance; scope and what not to touch; decisions with their reasons; checks; a stop rule; report bounds. It says to state the what, the limits and the check, not each step.
- A task whose design is still open is not delegated: the main conversation settles it, or asks the owner, then briefs it.
- `/agent-skills:offload`, `docs-principles` (prompt authoring) and `feature-briefing` (plans record each decision with its reason) say the same; the workers' own stop rules mention a brief that does not fit the code.
- The `implementer` offload case puts a decision and an off-limits file only in the prompt and checks, with `tool_used` `input_match` on the Agent call, that the brief carries the decision with its reason, the off-limits file and a stop rule.

## Alternatives

| Option | Rejected because |
|---|---|
| A separate brief-template file | The owner would copy two files into `CLAUDE.md`; the policy already travels there and into the evals |
| Plans with complete code for the worker | The expensive model does the work; delegation saves nothing |
| An `llm` grader over the trace | It sees only the first and last 12 messages; `input_match` reads the whole dispatch |

## Consequences

- The policy grows by about ten lines in every main conversation that carries it.
- Owners copy the new policy into their `CLAUDE.md`.

## Revisit if

Brief graders stay at the baseline, or delegation in the offload cases drops below its ADR 0012 level.

## Measurement 2026-10-29

`implementer` offload case, Opus main, 3 runs each, the same scaffold and prompt; the only change is the policy text (and `implementer`'s stop rule naming a brief that does not fit the code).

| Grader | Before (old policy) | After |
|---|---|---|
| Delegated to `implementer` | 2/3 | 3/3 |
| Main conversation edited no owned file | 2/3 | 3/3 |
| Brief: decision with its reason | 2/3 (2/2 briefs) | 3/3 |
| Brief: `invoice.py` off-limits | 2/3 (2/2 briefs) | 3/3 |
| Brief: stop rule | 0/3 | 3/3 |
| Task implemented | 3/3 | 3/3 |

- Opus already carried the conversation's decision and off-limits file when it delegated; the new text added the stop rule, and every brief came out with the six parts as headed sections, at about 300 words.
- One "after" brief wrote "Do NOT touch `invoice.py`", which the first scope pattern missed; the pattern now matches any case of "not", and the stored traces were rescored with it.
- Regression, Sonnet main, 3 runs: REGRESSION
- Cost: about $0.8 per 3-run Opus case.
