---
name: decision-records
description: Use when a significant technical decision is made, changed, superseded or questioned, or when creating, auditing or rating ADRs for staleness - concise MADR-style records with alternatives, consequences and explicit revisit triggers.
---

# Decision Records (ADR)

A decision record captures **why**, not what. Code shows what; ADRs preserve the context that code cannot.

## Significance test (write an ADR if ≥ 1 holds)

| Test | Example |
|---|---|
| Hard or costly to reverse | Database, framework, public API shape |
| Cross-cutting | Error-handling strategy, auth model, module boundaries |
| Surprising to a newcomer | "Why not the obvious library?" |
| Trade-off accepted knowingly | Consistency sacrificed for latency |
| Constraint-driven | Legal, budget, platform limitation |

Skip trivial, local, easily reversible choices.

## Location and naming

1. Reuse existing dir: `docs/adr/`, `doc/adr/`, `adr/`, `docs/decisions/`.
2. Else create `docs/adr/`.
3. File: `NNNN-kebab-title.md`, zero-padded, never renumbered.

## Template (≤ 60 lines)

```markdown
# NNNN Title as decision statement

Status: proposed | accepted | superseded by NNNN | deprecated · Date: YYYY-MM-DD

## Context
Forces, constraints, assumptions (mark each assumption explicitly).

## Decision
What we do. Imperative, specific.

## Alternatives
| Option | Rejected because |

## Consequences
Positive and negative. Who/what must change.

## Revisit if
Observable triggers that invalidate this decision.
```

## Rules

- One decision per record.
- Accepted records are immutable: change = new ADR that supersedes; update old status line only.
- `Revisit if` is mandatory and must be observable (version, scale, metric, event), not "if needed".
- Assumptions stated explicitly → they are what staleness audits check.
- Link code ↔ ADR when it prevents a "fix" that would undo the decision (`# See ADR 0007`).

## Staleness rating

Rate any existing decision with [the rubric](references/staleness-rubric.md). Output `low | medium | high` plus fired signals. Never a percentage (no calibration data).

## Lifecycle

`proposed` → `accepted` → (`superseded by NNNN` | `deprecated`). Rejected proposals stay as records: they prevent re-litigating.
