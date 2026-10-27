# Smell → refactoring catalog (Fowler, *Refactoring* 2nd ed.)

| Smell | Symptom | Refactorings |
|---|---|---|
| Mysterious name | Name doesn't reveal intent | Rename variable/function/field |
| Duplicated code | Same logic in several places | Extract function, slide statements, pull up method |
| Long function | Hard to read in one screen | Extract function, replace temp with query, decompose conditional, split loop |
| Long parameter list | Many args, often together | Introduce parameter object, preserve whole object, remove flag argument |
| Global data | Mutable module-level state | Encapsulate variable; pass explicitly |
| Mutable data | Unexpected changes | Encapsulate, split variable, separate query from modifier, prefer immutable values |
| Divergent change | One module changes for many reasons | Split phase, extract class/module |
| Shotgun surgery | One change touches many modules | Move function/field, combine functions into class, inline module |
| Feature envy | Function uses another module's data more than its own | Move function |
| Data clumps | Same group of fields travels together | Extract class / value object |
| Primitive obsession | Strings/ints for domain concepts | Replace primitive with object (newtype, value object) |
| Repeated switches | Same `match`/`if` on type in many places | Replace conditional with polymorphism / enum methods |
| Loops | Imperative accumulation | Replace loop with pipeline (comprehension, iterator chain) |
| Lazy element | Class/function that adds nothing | Inline function/class |
| Speculative generality | Unused hooks, params, abstractions | Collapse hierarchy, inline, remove dead code |
| Temporary field | Field set only in some cases | Extract class, introduce special case |
| Message chains | `a.b().c().d()` | Hide delegate, extract function |
| Middle man | Class only delegates | Remove middle man, inline |
| Insider trading | Modules exchange internals | Move function/field, hide delegate |
| Large class | Too many fields/methods | Extract class, extract superclass/trait |
| Refused bequest | Subclass ignores parent behavior | Replace subclass with delegate, push down |
| Comments explaining what | Comment compensates unclear code | Extract function with good name, introduce assertion |
| Dead code | Unreachable/unused | Remove (git keeps history) |

## Language notes

| Python | Rust |
|---|---|
| `ruff` flags many smells (complexity `C901`, unused, simplifications `SIM`) | `clippy` (`clippy::pedantic` selectively) |
| Dataclass / Pydantic for data clumps | Struct/newtype; `From`/`TryFrom` for conversions |
| `Protocol` instead of inheritance trees | Traits; enums with methods for repeated matches |
| `functools` / generators for pipelines | Iterator adapters |
| Type hints + `pyright` make moves safer | Compiler errors guide every move |
