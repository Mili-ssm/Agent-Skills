---
name: architecture-principles
description: Catalog of design principles, software laws, architectural styles, patterns, smells and evaluation methods (ISO 25010, ATAM, C4, fitness functions) for trade-off-aware recommendations. Use when evaluating or restructuring a codebase's architecture, module boundaries, layering or coupling, choosing between styles, or when one change ripples across many files; load it before recommending so each option names its quality attribute, trade-off and migration path.
---

# Architecture Principles

Architecture = the decisions that are expensive to change. Every recommendation names the **quality attribute** it improves and the **trade-off** it costs.

## Index

| Need | Reference |
|---|---|
| Design principles (SOLID, coupling/cohesion, connascence, deep modules, code-level rules) | [principles.md](references/principles.md) |
| Software laws and heuristics (Gall, Hyrum, Conway, Chesterton, Goodhart, LoB…) | [laws.md](references/laws.md) |
| Styles and patterns (hexagonal, vertical slice, DDD, Sans-IO, hypermedia, idioms) | [patterns.md](references/patterns.md) |
| Smells with remedies, churn-hotspot analysis | [smells.md](references/smells.md) |
| Evaluation (ISO 25010, ATAM, C4, fitness functions, metrics, severity) | [evaluation.md](references/evaluation.md) |

## Core heuristics

| Heuristic | Use |
|---|---|
| Simplest design meeting the ranked quality attributes | Complexity must be paid for by a named requirement |
| Grow from a working simple system (Gall) | Prefer incremental evolution to big-bang designs |
| Dependencies point toward policy and stability | Domain never imports infrastructure |
| High cohesion, low coupling, locality of behaviour | One reason to change → one place to look |
| Deep modules (Ousterhout) | Small interface, rich hidden behavior |
| Functional core, imperative shell | Logic testable without I/O |
| Conway's law | Boundaries follow team communication; design both together |
| Reversibility | Defer one-way-door decisions to the last responsible moment |
| Rule of three | Abstract at the third real variation, not the first imagined one |
| Boring technology by default | Spend novelty only where it buys a ranked quality attribute |

## Assessment workflow

The `architect` agent follows this workflow; use it inline for small scopes.

1. **Context**: purpose, users, constraints, scale, team size (requirements, ADRs, manifests).
2. **Rank 3–5 quality attributes** (ISO 25010); trade-offs are only decidable against a ranking.
3. **Map**: C4 context + container (+ component in scope) as Mermaid, derived from imports and config.
4. **Measure**: dependency direction, cycles, fan-in/out, churn hotspots (churn × complexity).
5. **Diagnose**: smell → principle → quality attribute affected → `file:line` → severity.
6. **Options**: trade-offs, effort S/M/L, incremental migration (strangler, branch by abstraction), a fitness function that keeps the fix in place.
7. **Record** significant choices as ADRs (`decision-records`).

## Recommendation guardrails

- Recommend a pattern only when a ranked quality attribute needs it; an unneeded pattern is pure cost.
- Prefer incremental migration to rewrites (second-system effect).
- Add a layer only when it hides real complexity or creates a needed test seam.
- One small team → modular monolith before microservices; a distributed monolith is the worst of both.
