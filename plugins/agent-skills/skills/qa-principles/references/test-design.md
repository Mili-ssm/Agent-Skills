# Test design techniques

## Black-box (ISTQB)

| Technique | Use when | How |
|---|---|---|
| Equivalence partitioning | Inputs split into classes treated alike | One case per valid and invalid class |
| Boundary value analysis | Ordered ranges, limits, sizes | min−1, min, min+1, max−1, max, max+1 |
| Decision table | Rules combine conditions | One column per rule; collapse irrelevant conditions |
| State transition | Behavior depends on state/history | All states, all valid transitions, key invalid ones |
| Pairwise / combinatorial | Many parameters | All pairs covered (`allpairspy`, PICT) |
| Use case / scenario | User goals end to end | Main path + extensions + failures |

## White-box

Statement < branch < condition/MC/DC (safety-critical) < path (rarely feasible). Use branch coverage to find unexercised logic, never as the quality goal.

## Exploratory heuristics

| Heuristic | Use |
|---|---|
| SFDPOT (Bach): Structure, Function, Data, Platform, Operations, Time | What to vary while exploring |
| HICCUPPS (Bolton): consistent with History, Image, Comparable products, Claims, User expectations, Product itself, Purpose, Statutes | Oracles: how to decide an observation is a bug |
| Charters | "Explore `<target>` with `<resources>` to discover `<information>`", time-boxed |
| Error guessing | Empty/None, zero, negative, unicode, huge, duplicates, concurrency, time zones/DST, leap days, locale, rounding, encoding, permissions, partial failure, retries |

## Property-based

| Property | Example |
|---|---|
| Round-trip | `decode(encode(x)) == x` |
| Invariant | Sorting preserves length and multiset |
| Idempotence | `f(f(x)) == f(x)` |
| Oracle / model | Optimized impl equals naive impl |
| Metamorphic | Adding a filter never increases result count |
| Commutativity | Order of independent operations irrelevant |
| Stateful (model-based) | Random command sequences against the system and a simple model; compare after each step |

## Case format

```markdown
| ID | Area | Technique | Input / precondition | Expected | Size | Risk |
```
