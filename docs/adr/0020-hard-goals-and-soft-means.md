# 0020 Requirements separate hard goals from soft means; N6 becomes soft

Status: accepted · Date: 2026-11-15 · Amends 0007

## Context

`docs/requirements.md` listed 16 requirements without saying which were ends and which were chosen means. An audit of the requirements, the 18 ADRs and the user-level rules (2026-11-15) found the goals mostly implicit and the means stated as if they were needs: a line cap, a model name, a named skill.

N6 required every description or prompt change to be measured. ADR 0017 and ADR 0018 shipped unmeasured by the owner's choice, because evals cost weekly usage, and the maintainer notes already allow a change "labeled unmeasured, with kill criteria".

The recorded trigger and offload figures were measured with Sonnet or Opus as the main model; the owner's main model changed afterwards.

## Decision

- Eight goals, G1 to G8, are functional and hard: one changes only by the owner's decision, with a PR and an ADR.
- Every R and N row keeps its ID and gains three columns: the goal it serves, its kind (functional or technical, hard or soft) and what reopens it. A row is hard only when it restates a goal (R2, R3, R4, R5, N4, N9); a soft row can be dropped when a measured gain outweighs its cost.
- N6 is soft and narrower: a change to a `description` or to `user-config/offload-policy.md` is measured; any other prompt change may ship labeled unmeasured, with a kill criterion in its ADR.
- The recorded figures stand until a measured text changes; then that text is measured with the main model in use.

## Alternatives

| Option | Rejected because |
|---|---|
| Keep N6 hard | It was already waived twice; a rule that is broken by choice misleads the next reader |
| Re-measure every case now with the current main model | Costs weekly usage with no text changed |
| Leave the classification in the owner's head | Agents treated thresholds and model names as needs and argued from them |

## Consequences

- A reader can tell which rows may be traded for a measured gain and which may not.
- Unmeasured changes need a kill criterion, or they are not allowed to merge.
- The figures in ADR 0007, 0010, 0012, 0013 and 0014 describe an earlier main model; treat them as a baseline, not as current.

## Revisit if

An unmeasured change is reverted for regressing in use; or the owner drops or rewrites a goal.
