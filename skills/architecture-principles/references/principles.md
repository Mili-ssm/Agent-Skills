# Design principles

## SOLID (Martin)

| Principle | Rule | Violation signal |
|---|---|---|
| SRP | One reason to change per module (one actor) | Unrelated changes hit the same file |
| OCP | Extend behavior without editing stable code | Growing `if/match` on type across files |
| LSP | Subtypes honor base contracts | Overrides that throw "not supported" |
| ISP | Clients depend only on what they use | Fat interfaces; stubs implementing unused methods |
| DIP | Policy depends on abstractions, details implement them | Domain imports DB/HTTP clients |

## GRASP (Larman)

Information Expert · Creator · Controller · Low Coupling · High Cohesion · Polymorphism · Pure Fabrication · Indirection · Protected Variations (wrap what varies behind a stable interface).

## Coupling and cohesion

| Cohesion (best → worst) | Coupling (best → worst) |
|---|---|
| Functional, sequential, communicational, procedural, temporal, logical, coincidental | Data, stamp, control, external, common (global), content |

## Connascence (Page-Jones)

Static (weaker → stronger): name, type, meaning (magic values), position, algorithm. Dynamic: execution order, timing, value, identity. Rules: reduce strength, reduce degree (how many elements), keep strong connascence local (inside one module).

## Ousterhout, *A Philosophy of Software Design*

- Complexity = dependencies + obscurity. Symptoms: change amplification, cognitive load, unknown unknowns.
- Deep modules; avoid shallow pass-through layers.
- Information hiding vs. leakage; define errors out of existence; pull complexity downward.
- Strategic over tactical programming.

## Package principles (Martin)

| Principle | Rule |
|---|---|
| REP / CCP / CRP | Release together, change together, reuse together |
| ADP | No dependency cycles between packages |
| SDP | Depend in the direction of stability |
| SAP | Stable packages are abstract |

## Other

KISS · DRY (knowledge, not text; tolerate duplication until the third instance — rule of three) · YAGNI · Law of Demeter · Composition over inheritance · Tell, don't ask · Command-query separation · Fail fast · Make illegal states unrepresentable · Postel/robustness at boundaries only.
