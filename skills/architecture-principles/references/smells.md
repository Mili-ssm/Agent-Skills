# Architecture smells

| Smell | Signal | Violates | Remedy |
|---|---|---|---|
| Cyclic dependency | Modules import each other (directly or transitively) | ADP | Extract shared abstraction; invert one edge (DIP) |
| God module / class | Huge file, high fan-in and fan-out, many reasons to change | SRP, cohesion | Split by responsibility/actor |
| Hub-like dependency | One module everything depends on and that depends on everything | SDP | Separate stable core from volatile parts |
| Leaky abstraction | Callers handle the implementation's details (SQL errors in UI) | Information hiding | Translate at boundary; own error types |
| Shallow module | Interface as complex as implementation; pass-through layers | Deep modules | Merge layers; hide more |
| Anemic domain | Entities are data bags; logic in services | Information expert | Move behavior next to data |
| Feature envy (module-level) | Module mostly uses another's data | Cohesion | Move logic to data owner |
| Shotgun surgery | One change touches many modules | CCP | Co-locate what changes together |
| Divergent change | One module changes for many reasons | SRP | Split |
| Scattered config / magic values | Same literal in many places | Connascence of meaning | Central typed config |
| Infrastructure in domain | Domain imports ORM, HTTP, framework | DIP | Ports & adapters |
| Distributed monolith | Services must deploy together; sync call chains | Independence | Merge or define async contracts |
| Shared database across modules | Many modules write the same tables | Encapsulation | Module owns its data; API between modules |
| Unstable dependency | Stable module depends on volatile one | SDP | Invert via interface |
| Speculative generality | Abstractions with one implementation, unused hooks | YAGNI | Inline until second variant |
| Missing boundary validation | Invalid data travels deep before failing | Fail fast | Parse, don't validate, at the edge |

## Hotspot analysis (Tornhill, *Your Code as a Crime Scene*)

```bash
# Churn: files changed most often in the last year (top candidates for refactoring).
git log --since="12 months ago" --name-only --format="" | sort | uniq -c | sort -rn | head -20
```

Hotspot = high churn × high complexity (size, nesting). Prioritize remedies there; ignore smells in cold code.
