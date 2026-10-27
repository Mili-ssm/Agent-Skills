# Smell → refactoring catalog (Fowler, *Refactoring* 2nd ed.)

| Smell | Symptom | Refactorings |
|---|---|---|
| Mysterious name | Name hides intent | Rename |
| Duplicated code | Same logic in several places | Extract function, slide statements, pull up method |
| Long function | Does not fit one screen; mixed abstraction levels | Extract function, replace temp with query, decompose conditional, split loop |
| Long parameter list | Many args travel together | Introduce parameter object, preserve whole object, remove flag argument |
| Global / mutable data | Unexpected changes | Encapsulate variable, split variable, separate query from modifier, immutable values |
| Divergent change | One module changes for many reasons | Split phase, extract class/module |
| Shotgun surgery | One change touches many modules | Move function/field, combine into class, inline module |
| Feature envy | Uses another module's data more than its own | Move function |
| Data clumps | Same fields travel together | Extract class / value object |
| Primitive obsession | Strings/ints for domain concepts | Replace primitive with object (newtype, value object) |
| Repeated switches | Same `match`/`if` on type in many places | Polymorphism or enum methods |
| Imperative loops | Manual accumulation | Replace loop with pipeline (comprehension, iterator chain) |
| Lazy element / middle man | Adds nothing, only delegates | Inline function/class, remove middle man |
| Speculative generality | Unused hooks, params, abstractions | Collapse hierarchy, inline, remove dead code |
| Temporary field | Set only in some cases | Extract class, introduce special case |
| Message chains | `a.b().c().d()` | Hide delegate, extract function |
| Large class | Too many fields/methods | Extract class, extract trait |
| Refused bequest | Subclass ignores parent behavior | Replace subclass with delegate |
| Comment explaining what | Comment compensates unclear code | Extract well-named function, introduce assertion |
| Dead code | Unreachable or unused | Delete (git keeps history) |

## Language notes

| Python | Rust |
|---|---|
| `ruff` flags many smells (`C901`, `SIM`, unused) | `clippy` (selected `pedantic` lints) |
| Dataclass / Pydantic for data clumps | Struct/newtype; `From`/`TryFrom` for conversions |
| `Protocol` instead of inheritance trees | Traits; enums with methods for repeated matches |
| Type hints + `pyright` make moves safer | Compiler errors guide every move |
