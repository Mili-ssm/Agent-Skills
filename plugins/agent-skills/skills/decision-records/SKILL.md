---
name: decision-records
description: Writes and audits concise architecture decision records (MADR or Y-statement) with alternatives, consequences, revisit triggers and a staleness rubric. Use when a technical decision is made, changed, questioned or needs writing up for future developers, or when someone asks why something was built a certain way.
---

# Decision Records (ADR)

An ADR keeps the **why** that code cannot show: context, rejected options, accepted trade-offs.

## Significance test (write one if any holds)

| Test | Example |
|---|---|
| One-way door: hard or costly to reverse | Database, framework, public API shape |
| Cross-cutting | Error strategy, auth model, module boundaries |
| Surprising to a newcomer | "Why not the obvious library?" |
| Known trade-off accepted | Consistency traded for latency |
| Constraint-driven | Legal, budget, platform limit |

Two-way doors (cheap to reverse) get a commit message, not an ADR.

## Location and naming

Reuse `docs/adr/`, `doc/adr/`, `adr/` or `docs/decisions/`; else create `docs/adr/`. File `NNNN-kebab-title.md`, numbers never reused.

## Template (≤ 60 lines)

```markdown
# NNNN Title as decision statement

Status: proposed | accepted | superseded by NNNN | deprecated · Date: YYYY-MM-DD

## Context
Forces and constraints. Mark each assumption explicitly.

## Decision
Imperative and specific.

## Alternatives
| Option | Rejected because |

## Consequences
Positive and negative; who or what must change.

## Revisit if
Observable triggers (version, scale, metric, event).
```

Small decisions fit a **Y-statement**: *In the context of `<situation>`, facing `<concern>`, we decided `<option>` and against `<alternatives>`, to achieve `<quality>`, accepting `<downside>`.*

## Rules

- One decision per record, so each can be superseded alone.
- Treat an accepted decision as immutable: changing it means a new ADR that supersedes the old one (only the old status line changes), which keeps the history of reasoning. Verifications and clarifications go in an appended `## Review YYYY-MM-DD` section.
- Write `Revisit if` as observable triggers; staleness audits check them.
- State assumptions explicitly; they are what goes stale first.
- Link code to the ADR where a "cleanup" would undo the decision (`# See ADR 0007`): Chesterton's fence made visible.
- Keep rejected proposals as records; they stop the same debate from restarting.

## Revisit rating

Rate existing decisions with the [staleness rubric](references/staleness-rubric.md): output a revisit rating `low | medium | high` plus the signals that fired.

## Lifecycle

`proposed` → `accepted` → `superseded by NNNN` | `deprecated`.
