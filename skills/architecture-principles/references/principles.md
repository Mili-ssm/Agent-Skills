# Design principles

## SOLID (Martin)

| Principle | Rule | Violation signal |
|---|---|---|
| SRP | One reason to change per module (one actor) | Unrelated changes hit the same file |
| OCP | Extend without editing stable code | Growing `if/match` on type across files |
| LSP | Subtypes honor base contracts | Overrides that raise "not supported" |
| ISP | Clients depend only on what they use | Fat interfaces, stub methods |
| DIP | Policy depends on abstractions; details implement them | Domain imports DB/HTTP clients |

GRASP (Larman) adds: information expert, creator, controller, pure fabrication, indirection, protected variations (wrap what varies behind a stable interface).

## Coupling, cohesion, connascence

| Cohesion (best → worst) | Coupling (best → worst) |
|---|---|
| Functional, sequential, communicational, procedural, temporal, logical, coincidental | Data, stamp, control, external, common (global), content |

Connascence (Page-Jones), weaker → stronger. Static: name, type, meaning, position, algorithm. Dynamic: execution order, timing, value, identity. Reduce strength and degree; keep strong connascence inside one module.

## Information hiding and complexity

| Source | Idea |
|---|---|
| Parnas (1972) | Modularize around decisions likely to change, not processing steps |
| Ousterhout | Complexity = dependencies + obscurity; symptoms: change amplification, cognitive load, unknown unknowns. Deep modules, define errors out of existence, pull complexity downward |
| Hickey, *Simple Made Easy* | Simple (not interleaved) ≠ easy (familiar). Avoid complecting state, time, identity |
| Gabriel / htmx, Locality of Behaviour | A unit's behavior should be evident from the unit itself; trade against DRY consciously |
| tef, *Write code that is easy to delete* | Optimize for removal: isolate volatile code, duplicate before coupling |

## Package principles (Martin)

REP/CCP/CRP: release, change and reuse together. ADP: no cycles. SDP: depend toward stability. SAP: stable packages are abstract.

## Code-level rules

| Rule | Meaning |
|---|---|
| Least astonishment (POLA) | Names and behavior match what a reader expects |
| Make illegal states unrepresentable | Types encode invariants (enums, newtypes, typestate) |
| Parse, don't validate | Convert raw input to trusted types once, at the boundary |
| Single level of abstraction (SLAP) | A function mixes no high-level steps with low-level detail |
| Command-query separation | A function changes state or returns data, not both |
| Design by contract (Meyer) | Explicit pre/postconditions and invariants; assert them in debug |
| Errors as values | `Result`/explicit errors for expected failures; exceptions/panics for bugs |
| Guard clauses | Return early; keep the happy path unindented |
| Temporal coupling | Make required call order impossible to get wrong (builder, typestate) |
| AHA / rule of three | Avoid hasty abstractions; duplication is cheaper than the wrong abstraction |
| Kernighan's law | Debugging is twice as hard as writing; clever code is undebuggable |
| Fail fast | Detect and report errors at the earliest point |
| KISS · YAGNI · DRY (of knowledge) · Demeter · composition over inheritance · tell, don't ask | Known defaults; apply with the above trade-offs |
