---
name: decision-records
description: Writes and audits concise architecture decision records (MADR or Y-statement) with alternatives, consequences, revisit triggers and a staleness rubric. Use when a technical decision is made, changed, questioned or needs writing up for future developers, when existing records need an audit, or to find the recorded rationale of an existing decision (check docs/adr first); a casual "why" question about a piece of code does not need it.
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

Reuse `docs/adr/`, `doc/adr/`, `adr/` or `docs/decisions/`; else create `docs/adr/` (read-only agents: put the draft in the report instead). File `NNNN-kebab-title.md`, numbers never reused. To find why an existing decision was made, read these folders first (Context and Alternatives hold the rationale); nothing recorded → say so instead of inferring a rationale.

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

## Audit

1. **Find** the ADRs (locations above) and note decisions that exist only in code or prose.
2. **Rate** each with the [staleness rubric](references/staleness-rubric.md); open it at this step, because the signals and the aggregation rule live there. The rating is `low | medium | high` plus the signals that fired.
3. **Report** one row per ADR, worst rating first, unless the task or the calling agent sets its own format: `| ADR | Status | Rating | Signals | Action |`, where Action is keep · add a dated Review note · supersede · deprecate.
