# Software laws and heuristics

Informal laws that predict failure modes. Cite them by name in findings and plans.

## Design and evolution

| Law | Statement | Implication |
|---|---|---|
| Gall's law | Working complex systems evolve from working simple ones | Start simple; avoid big-bang designs and rewrites |
| Conway's law | Systems mirror the communication structure of their org | Align module boundaries with team boundaries (inverse Conway maneuver) |
| Hyrum's law | With enough users, every observable behavior is depended on | Undocumented behavior is part of the contract; changes need impact analysis |
| Lehman's laws | Used software must keep changing, and its complexity grows unless actively reduced | Budget continuous refactoring |
| Second-system effect (Brooks) | The successor system gets over-engineered | Scope rewrites to the proven needs |
| Chesterton's fence | Don't remove what you don't understand | Find the reason (git blame, ADR) before deleting |
| Postel's law | Liberal in what you accept, strict in what you send | At boundaries only; inside, fail fast |
| Rule of least power (Berners-Lee) | Use the least powerful language that solves the problem | HTML/CSS before JS; config before code; SQL before loops |
| Worse is better (Gabriel) | Simple, available designs spread and win over perfect ones | Ship simple and iterate |
| Lindy effect | Long-lived technology tends to keep living | Prefer proven tools for core infrastructure |
| Boring technology (McKinley) | A team affords few novel choices ("innovation tokens") | Novelty must buy a ranked quality attribute; critics note the real cost is operational overhead |
| Zawinski / feature creep | Programs grow until they do everything | Guard scope with explicit non-goals |

## Measurement and planning

| Law | Statement | Implication |
|---|---|---|
| Goodhart's law | A measure that becomes a target stops measuring | Pair metrics (coverage + mutation score; velocity + defects) |
| Hofstadter's law | It takes longer than expected, even accounting for this law | Use reference-class estimates, buffers, kill criteria |
| Brooks's law | Adding people to a late project makes it later | Cut scope before adding people |
| Parkinson's law | Work expands to fill the time available | Time-box spikes |
| Planning fallacy (Kahneman) | Estimates ignore base rates | Compare with similar past work |
| Amdahl's law | Speed-up is bounded by the unimproved fraction | Optimize the dominant cost only |
| Little's law | L = λ × W (in-flight = arrival rate × latency) | Size pools/queues; latency growth means queueing |

## Distributed systems

| Law | Implication |
|---|---|
| Fallacies of distributed computing (reliable network, zero latency, infinite bandwidth, secure network, fixed topology, one admin, zero transport cost, homogeneous network) | Every remote call needs timeout, retry policy, idempotency and failure handling |
| CAP / PACELC | Under partition choose consistency or availability; otherwise latency vs. consistency |
| End-to-end principle | Correctness checks belong at the endpoints, not only in the transport |
| Tail at scale (Dean & Barroso) | Fan-out amplifies p99 latency; hedge requests, bound fan-out |
