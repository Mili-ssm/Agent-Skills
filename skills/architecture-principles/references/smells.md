# Architecture smells

| Smell | Signal | Violates | Remedy |
|---|---|---|---|
| Cyclic dependency | Modules import each other (directly or transitively) | ADP | Extract shared abstraction; invert one edge (DIP) |
| God module | Huge file, high fan-in and fan-out, many reasons to change | SRP, cohesion | Split by responsibility/actor |
| Hub-like dependency | Everything depends on it and it depends on everything | SDP | Separate stable core from volatile parts |
| Leaky abstraction | Callers handle implementation details (SQL errors in UI) | Information hiding | Translate at the boundary; own error types |
| Shallow module | Interface as complex as implementation; pass-through layers | Deep modules | Merge layers; hide more |
| Anemic domain | Entities are data bags; logic in services | Information expert | Move behavior next to data |
| Shotgun surgery | One change touches many modules | CCP, locality | Co-locate what changes together |
| Divergent change | One module changes for many reasons | SRP | Split |
| Scattered config / magic values | Same literal in many places | Connascence of meaning | Central typed config |
| Infrastructure in domain | Domain imports ORM, HTTP, framework | DIP | Ports & adapters |
| Distributed monolith | Services deploy together; synchronous call chains | Independence | Merge, or async contracts |
| Shared database across modules | Many modules write the same tables | Encapsulation | Module owns its data; API between modules |
| Unstable dependency | Stable module depends on volatile one | SDP | Invert via interface |
| Speculative generality | One-implementation abstractions, unused hooks | YAGNI | Inline until the second variant |
| Missing boundary validation | Invalid data travels deep before failing | Parse, don't validate | Typed parsing at the edge |
| Golden hammer | One tool/pattern applied everywhere | Fit to problem | Choose per quality attribute |
| Big ball of mud | No discernible structure | All of the above | Strangle by feature; enforce new boundaries with fitness functions |

## Churn-hotspot analysis (Tornhill, *Your Code as a Crime Scene*)

```bash
# Files changed most in the last year: refactoring candidates when also complex.
git log --since="12 months ago" --name-only --format="" | sort | uniq -c | sort -rn | head -20
```

Churn hotspot = high churn × high complexity (size, nesting). Remedies pay off there; smells in cold, stable code rarely do. Also check change coupling: files that always change together but live apart.
