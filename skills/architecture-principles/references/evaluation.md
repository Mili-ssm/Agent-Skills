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

Rank top 3–5 for the system; trade-offs are decided by that ranking.

## ATAM-lite (SEI Architecture Tradeoff Analysis Method)

1. Business drivers + ranked quality attributes.
2. Quality attribute **scenarios**: source, stimulus, environment, artifact, response, response measure. Example: "Under 10× normal load, a page request returns in < 300 ms p95."
3. Map scenarios to architectural approaches.
4. Identify **sensitivity points** (one decision strongly affects one attribute), **trade-off points** (affects several in opposite directions), **risks** and **non-risks**.
5. Output: risk themes linked to business drivers.

## C4 model (Brown)

| Level | Shows | Audience |
|---|---|---|
| 1 Context | System, users, external systems | Everyone |
| 2 Container | Deployables/runtimes (web app, DB, worker) | Tech team |
| 3 Component | Major modules inside a container | Developers |
| 4 Code | Classes/functions (rarely worth drawing) | — |

Draw as Mermaid `flowchart`; label edges with protocol/purpose.

## Fitness functions (Ford, Parsons, Kua — *Building Evolutionary Architectures*)

Automated checks that keep an architectural property true: dependency rules (`import-linter`, `cargo-deny`/crate boundaries, ArchUnit-style tests), cycle checks, latency budgets in CI, bundle/JS size limits, coverage of critical paths. Every structural recommendation should propose one.

## Dependency metrics (Martin)

| Metric | Formula | Reading |
|---|---|---|
| Instability I | Ce / (Ca + Ce) | 0 stable, 1 volatile |
| Abstractness A | abstract types / total types | — |
| Distance D | \|A + I − 1\| | Near 0 good; zone of pain (stable+concrete), zone of uselessness (abstract+volatile) |

## Severity scale for findings

| Level | Meaning |
|---|---|
| critical | Blocks a top-ranked quality attribute now |
| major | Will block it under foreseeable change/scale |
| minor | Local friction; fix opportunistically |
| note | Observation, no action required |
