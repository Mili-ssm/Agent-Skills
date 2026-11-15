# 0019 Superpowers supplies the methods and the plan loop; this plugin's agents do the work

Status: accepted · Date: 2026-11-15 · Amends 0010, 0013, 0017

## Context

R5 said "complement Superpowers and not duplicate its process skills", and its table gave plan execution and general review to Superpowers. `user-config/routing.md` and ADR 0017 had already moved both to `implementer` and `skeptical-reviewer` without flipping the requirement. [superpowers-seams.md](../superpowers-seams.md) (Superpowers 7.0.2) records 25 seams, eleven with a conflict.

Observed in 62 sessions (2026-10-27 to 2026-11-15): 530 `implementer` dispatches, never two in one message; in five of the six sessions that loaded `subagent-driven-development` the `implementer` wrote the code while generic Sonnet subagents reviewed each task; `executing-plans`, `requesting-code-review` and `dispatching-parallel-agents` were never loaded.

Assumption, unverified: the model follows the routing lines over the text of a loaded Superpowers skill. The skill's own index says user instructions "take precedence over skills".

## Decision

The owner decided each row on 2026-11-15 (`intent-elicitation`). R5 now requires one instruction per task (goal G7); the boundary table and `user-config/routing.md` carry these rulings.

| Seam | Ruling |
|---|---|
| E1, E2, E3, P3 | An approved code plan runs in the `subagent-driven-development` loop: its order, its ledger, one task at a time. `implementer` is its implementer and commits each task locally. `writing-plans` writes the plan; `brainstorming` comes first only while the design is open |
| seam R1 | `skeptical-reviewer` reviews each task; its brief adds the task text (missing, extra, misunderstood). The main conversation forms the verdicts. Two review rounds per task. After the last task, narrow parallel `skeptical-reviewer` reviews replace the loop's whole-branch reviewer |
| seam R3 | A `check-runner` PASS is evidence when it names the command and the result; the main conversation reruns the decisive check before a commit of its own, a push or a pull request |
| D2 | Lint, type, format and import errors go to `fixer` with no root-cause investigation; the same error after 2 attempts, or a test failing on behavior, goes to `systematic-debugging` |
| D4 | Inside a plan the task's own test-then-code steps apply; outside one, `implementer` keeps "see it fail when feasible" |
| A1 | The routing table and the offload policy decide who does the work; a Superpowers skill loads when a row names it |

"Review before the step" applies to a push, a pull request, a merge, a tag and a commit on a branch that already has an upstream on the remote; a task commit inside the loop is reviewed right after it.

## Alternatives

| Option | Rejected because |
|---|---|
| `implementer` rows without the loop | No ledger and no resumable order; the owner chose the loop |
| The Superpowers task reviewer on Sonnet | Stronger on a vendor defect-search benchmark (F1 0.76 against 0.58 for Haiku, at about four times the cost per run there; not measured on task review). The owner keeps the cheap reviewer whose findings the caller verifies |
| The loop with Superpowers subagents only | Abandons the agents that carry most of today's work |
| Rewriting the Superpowers methods here and uninstalling it | Five or six skills to write and measure; upstream improvements lost |
| Deny rules for the three unused skills | Declined by the owner; the docs do not say whether a denied skill leaves the listing |

## Consequences

- `routing.md` gains a "Plan loop" section of six bridging lines, loaded in every session. It ships unmeasured (N6).
- This record holds one decision, how the two plugins fit, as one ruling per seam. A ruling that changes gets its own ADR that amends this one.
- The loop expects verdicts, a report file and a commit per task; the lines say who supplies each. The reviewer stays advisory, so the main conversation decides "needs fixes".
- Loading the skill costs about 4,900 tokens per plan execution.
- Seams P1, P2, P4-P6, E4, E5, D1, D3, D5, A2-A4 and seams R2, R4 and R5 stay open or already fit.

## Revisit if

A Superpowers update changes the loop's scripts or prompts; or the owner reports worse results (G8).

### Kill criteria

Proposed with this record; the owner has not set them.

| Signal in a trace of a plan run | Action |
|---|---|
| The main conversation overrides an agent's model, or dispatches generic subagents for a role, in 2 runs | Tighten the two "no model parameter" lines |
| A task stalls for lack of a verdict, or findings are dropped without a ruling, in 2 runs | Switch the task reviewer to the Superpowers one on Sonnet (alternative 2) |
| The loop cannot start on a plan (`task-brief` finds no task heading) | Use the non-loop row for that plan and record the plan shape |
