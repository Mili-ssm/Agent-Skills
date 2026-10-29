---
name: refactoring
description: Guides refactoring - restructuring code without changing its behavior - through characterization tests, small test-backed steps, Fowler's smell catalog, Tidy First, Mikado method, parallel change, branch by abstraction and strangler fig. Use when asked to refactor, restructure, clean up, split, rename, extract or untangle a function, module or legacy code, or to pay down tech debt; load it before proposing steps so each one names its smell and keeps tests green.
---

# Refactoring

Refactoring changes structure **without changing behavior**, in small steps that keep tests green. Feature work and refactoring are separate hats (Beck): each checkpoint wears one hat, so a red test has one possible cause.

## Preconditions

1. Tests pin current behavior. Missing → write **characterization tests** first (Feathers): assert what the code does now, oddities included.
2. Clean working tree and a test command that runs in seconds.
3. A named smell and the change it will make easier: "make the change easy, then make the easy change" (Beck). Read the code's history first (Chesterton's fence).

## Loop

1. Pick one refactoring from the [catalog](references/catalog.md).
2. Apply the smallest step; automated/IDE moves first (rename, extract, inline, move) because they preserve behavior mechanically.
3. Run tests (through `check-runner` when output is long). Green → checkpoint: commit `refactor: …` when the owner works with commits. Red → revert and take a smaller step. Many mechanical breakages after a move or rename → `fixer`.
4. Repeat; behavior changes follow in separate checkpoints.

## Size of the job

| Technique | Use when | Steps |
|---|---|---|
| Tidy First (Beck) | Small tidyings right before a change | Guard clauses, explaining variables, reorder, extract helper; give tidyings their own checkpoint |
| Preparatory refactoring | The change is awkward in the current shape | Reshape first, then change |
| Mikado method | Goal has a web of prerequisites | Try goal → note breakages → revert → solve leaf prerequisites → retry; keep the graph in a note |
| Sprout / wrap (Feathers) | Adding to untested legacy code | New tested function called from legacy; wrap old method |

Parallel change (an interface with many callers), branch by abstraction (replacing an internal component on trunk) and strangler fig (replacing a subsystem or legacy app) are in the strategy table of `change-impact`, with their steps.

Legacy code = code without tests. Find **seams** (parameters, interfaces, module boundaries) and break dependencies minimally to get it under test.

## Rules

- Unless the owner named a target, start with churn hotspots (churn × complexity), because cold code nobody changes pays nothing back; with a named target, stay within it.
- Let the compiler guide moves where possible, because its errors list every site a change touches (Rust: change a type, follow the errors).
- Upgrade dependencies in a separate step, so failures have one cause.
- Stop when the motivating change is easy, because further restructuring has no named payoff.
- Public API changes are breaking changes for consumers: use `change-impact`.
