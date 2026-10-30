# Evaluation methods

## ISO/IEC 25010 quality attributes

| Characteristic | Sub-characteristics (selection) |
|---|---|
| Functional suitability | Completeness, correctness, appropriateness |
| Performance efficiency | Time behavior, resource use, capacity |
| Compatibility | Co-existence, interoperability |
| Interaction capability (usability) | Learnability, operability, error protection, accessibility |
| Reliability | Availability, fault tolerance, recoverability |
| Security | Confidentiality, integrity, non-repudiation, accountability, authenticity |
| Maintainability | Modularity, reusability, analysability, modifiability, testability |
| Flexibility (portability) | Adaptability, installability, scalability |
| Safety | Operational constraint, risk identification, fail safe |

Rank the top 3–5 for the system; that ranking decides trade-offs.

## ATAM-lite (SEI)

1. Business drivers + ranked quality attributes.
2. Quality attribute scenarios: source, stimulus, environment, artifact, response, response measure. *"Under 10× load, page requests return in < 300 ms p95."*
3. Map scenarios to architectural approaches.
4. Find sensitivity points (one decision drives one attribute), trade-off points (drives several in opposite directions), risks and non-risks.
5. Output risk themes linked to business drivers.

## C4 model (Brown)

| Level | Shows | Audience |
|---|---|---|
| 1 Context | System, users, external systems | Everyone |
| 2 Container | Deployables/runtimes (web app, DB, worker) | Tech team |
| 3 Component | Major modules inside a container | Developers |
| 4 Code | Classes/functions (rarely worth drawing) | — |

Draw as Mermaid `flowchart`; label edges with protocol/purpose.

## Fitness functions (*Building Evolutionary Architectures*)

Automated checks that keep an architectural property true: dependency rules (`import-linter`, crate boundaries, `cargo-deny`), cycle checks, latency budgets in CI, JS/bundle size limits, critical-path coverage. Every structural recommendation proposes one.

## Team cognitive load (*Team Topologies*)

A module or service should fit one team's cognitive load. Signals of overload: one team owns many unrelated domains; frequent cross-team handoffs for one change. Remedy: split along stream-aligned boundaries, platform for shared capabilities.

## Dependency metrics (Martin)

| Metric | Formula | Reading |
|---|---|---|
| Instability I | Ce / (Ca + Ce) | 0 stable, 1 volatile |
| Abstractness A | abstract types / total types | — |
| Distance D | \|A + I − 1\| | Near 0 good; zone of pain (stable + concrete), zone of uselessness (abstract + volatile) |

## Severity scale

| Level | Meaning |
|---|---|
| critical | Blocks a top-ranked quality attribute now |
| major | Will block it under foreseeable change or scale |
| minor | Local friction; fix opportunistically |
| note | Observation, no action required |
