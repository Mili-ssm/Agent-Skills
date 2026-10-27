# Test design techniques (ISTQB)

## Black-box

| Technique | Use when | How |
|---|---|---|
| Equivalence partitioning | Input domain splits into classes treated alike | One case per valid and invalid class |
| Boundary value analysis | Ordered ranges, limits, sizes | Test min−1, min, min+1, max−1, max, max+1 (3-value BVA) |
| Decision table | Business rules combine conditions | One column per rule; collapse irrelevant conditions |
| State transition | Behavior depends on state/history | Cover all states, all valid transitions, key invalid transitions |
| Pairwise / combinatorial | Many parameters, too many combinations | All pairs covered (tools: `allpairspy`, PICT) |
| Use case / scenario | End-to-end user goals | Main success path + extensions + failures |
| Cause-effect graphing | Complex logical input relations | Derive decision table from graph |

## White-box

| Coverage | Meaning |
|---|---|
| Statement | Each line executed (weakest) |
| Branch / decision | Each branch outcome taken |
| Condition / MC/DC | Each condition independently affects outcome (safety-critical) |
| Path | Combinations of branches (rarely feasible) |

## Experience-based

- **Error guessing**: typical defects — empty/null/None, zero, negative, unicode, very large, duplicates, concurrency, time zones/DST, leap days, locale, off-by-one, rounding, encoding, permissions, partial failure, retries.
- **Exploratory testing**: time-boxed charters ("Explore X with Y to discover Z").
- **Checklist-based**: domain checklists (forms, auth, payments, file upload).

## Property-based (invariants)

| Property type | Example |
|---|---|
| Round-trip | `decode(encode(x)) == x` |
| Invariant | Sorting preserves length and multiset |
| Idempotence | `f(f(x)) == f(x)` |
| Oracle / model | Optimized impl equals naive impl |
| Metamorphic | Adding a filter never increases result count |
| Commutativity | Order of independent ops irrelevant |

## Case format

```markdown
| ID | Feature | Technique | Input / precondition | Expected | Level | Risk |
```
