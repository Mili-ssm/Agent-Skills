---
name: architecture-principles
description: Catalog of design principles, software laws, architectural styles, patterns, smells and evaluation methods (ISO 25010, ATAM, C4, fitness functions) for trade-off-aware recommendations. Use when evaluating or restructuring a codebase's architecture, module boundaries, layering or coupling, choosing between styles, or when one change ripples across many files; load it before recommending so each option names its quality attribute, trade-off and migration path.
---

# Architecture Principles

Architecture = the decisions that are expensive to change. Every recommendation names the **quality attribute** it improves and the **trade-off** it costs.

## Index

| Workflow step | Open | For |
|---|---|---|
| 2 Rank, 3 Map | [evaluation.md](references/evaluation.md) | ISO 25010 attributes, ATAM, C4 |
| 4 Measure | [smells.md](references/smells.md), [evaluation.md](references/evaluation.md) | Churn-hotspot commands; dependency metrics |
| 5 Diagnose | [smells.md](references/smells.md), [principles.md](references/principles.md), [evaluation.md](references/evaluation.md) | Smell → remedy; SOLID, coupling/cohesion, connascence, deep modules, code-level rules; severity scale |
| 6 Options | [patterns.md](references/patterns.md), [laws.md](references/laws.md), [evaluation.md](references/evaluation.md) | Styles, patterns, idioms; laws for plans and evolution (Gall, Conway, Hyrum, Chesterton, Goodhart…); fitness functions |

## Core heuristics

| Heuristic | Use |
|---|---|
| Simplest design meeting the ranked quality attributes | Complexity must be paid for by a named requirement |
| Grow from a working simple system (Gall) | Prefer incremental migration to big-bang rewrites; a successor system tends to be over-engineered (second-system effect) |
| Dependencies point toward policy and stability | Domain never imports infrastructure |
| Reversibility | Defer one-way-door decisions to the last responsible moment |
| Conway's law | Boundaries follow team communication; design both together |

Further principles (cohesion and coupling, deep modules, rule of three, functional core) are in `principles.md`; further laws (boring technology, Lehman, Postel…) in `laws.md`.

## Assessment workflow (the `architect` agent runs it in full; inline for a small scope)

1. **Context**: purpose, users, constraints, scale, team size (requirements, ADRs, manifests).
2. **Rank 3–5 quality attributes** (ISO 25010); trade-offs are only decidable against a ranking. Main conversation: confirm steps 1–2 with the owner. Agent run (no owner available): mark the ranking `assumed` and list it, with other context gaps, as decisions for the owner.
3. **Map**: C4 context + container (+ component in scope) as Mermaid, derived from imports and config.
4. **Measure**: dependency direction, cycles, fan-in/out, churn hotspots (churn × complexity).
5. **Diagnose**: smell → principle → quality attribute affected → `file:line` → severity (scale in [evaluation.md](references/evaluation.md)).
6. **Options**: trade-offs, effort (S ≤ 1 day, M ≤ 1 week, L > 1 week), incremental migration (strangler, branch by abstraction), a fitness function that keeps the fix in place.
7. **Record** significant choices as ADRs (`decision-records`).

## Recommendation guardrails

- Recommend a pattern only when a ranked quality attribute needs it; an unneeded pattern is pure cost.
- Add a layer only when it hides real complexity or creates a needed test seam.
- One small team → modular monolith before microservices; a distributed monolith is the worst of both.
