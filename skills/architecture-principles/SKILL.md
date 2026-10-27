---
name: architecture-principles
description: Use when evaluating, designing or refactoring software architecture or module boundaries - catalog of design principles, architectural styles, patterns, smells and evaluation methods (ISO 25010, ATAM, C4, fitness functions) for justified, trade-off-aware recommendations.
---

# Architecture Principles

Architecture = the decisions that are expensive to change. Every recommendation must name the **quality attribute** it improves and the **trade-off** it costs.

## Index

| Need | Reference |
|---|---|
| Design principles (SOLID, GRASP, coupling/cohesion, connascence, deep modules) | [principles.md](references/principles.md) |
| Styles and patterns (hexagonal, clean, DDD, GoF, PoEAA, CQRS, language idioms) | [patterns.md](references/patterns.md) |
| Architecture smells and their remedies | [smells.md](references/smells.md) |
| Evaluating (ISO 25010, ATAM, C4, fitness functions, dependency metrics) | [evaluation.md](references/evaluation.md) |

## Core heuristics

| Heuristic | Use |
|---|---|
| Simplest thing that meets quality attributes | Default; complexity must be paid for by a named requirement |
| Dependencies point toward stability/policy | Domain does not import infrastructure |
| High cohesion, low coupling | Change one reason → touch one module |
| Deep modules (Ousterhout) | Small interface, rich hidden behavior |
| Functional core, imperative shell | Pure logic testable without I/O |
| Conway's law | Boundaries mirror team/communication structure |
| Reversibility | Prefer decisions easy to undo; defer irreversible ones to the last responsible moment |
| YAGNI vs. extension points | Add abstraction at the second real variation, not the first imagined one |

## Assessment process

1. **Context**: purpose, users, constraints, scale, team size (ask or read requirements/ADRs).
2. **Quality attributes**: pick top 3–5 from ISO 25010; rank them. Without ranking, trade-offs are arbitrary.
3. **Map**: C4 context + container (+ component for the area in scope), as Mermaid.
4. **Measure**: dependency direction, cycles, fan-in/fan-out, churn × complexity hotspots (`git log` + file size).
5. **Diagnose**: smells → violated principle → affected quality attribute → evidence `file:line`.
6. **Propose**: options with trade-offs; incremental migration path (strangler, branch by abstraction); fitness function to keep it fixed.
7. **Record**: significant choices → ADR (`decision-records`).

## Anti-patterns in recommendations

- Pattern-first ("use CQRS") without a quality attribute that demands it.
- Big-bang rewrites when incremental migration exists.
- Abstraction layers with one implementation and no test seam benefit.
- Microservices for a single small team (distributed monolith risk).
