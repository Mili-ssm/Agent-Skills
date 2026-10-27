---
name: refactoring
description: Use when restructuring existing code without changing behavior - removing code smells, untangling legacy code, splitting modules, renaming or extracting - safe small-step refactoring with characterization tests, Fowler's catalog, Mikado method, strangler fig and branch by abstraction.
---

# Refactoring

Refactoring = changing structure **without changing behavior**, in small steps that keep tests green. Feature work and refactoring are separate "hats" (Beck): never mix them in one step or commit.

## Preconditions

1. Tests pin current behavior of the code to change. Missing → write **characterization tests** first (Feathers): assert what the code does now, even if odd.
2. Clean working tree; know the command that runs the relevant tests in seconds.
3. Know why: name the smell and the change it will make easier ("make the change easy, then make the easy change").

## Loop

1. Pick one refactoring from [the catalog](references/catalog.md).
2. Apply the smallest step (IDE-safe moves first: rename, extract, inline, move).
3. Run tests. Green → commit (`refactor: …`). Red → revert, take a smaller step.
4. Repeat. Behavior changes go in separate commits afterwards.

## Large refactorings

| Technique | Use when | Steps |
|---|---|---|
| Mikado method | Change has a web of prerequisites | Try goal → note what breaks → revert → solve leaf prerequisites first → retry. Keep the Mikado graph in a note |
| Parallel change (expand/contract) | Changing an interface with many callers | Add new form → migrate callers gradually → remove old form |
| Branch by abstraction | Replacing an internal component on trunk | Introduce abstraction → route callers through it → build new impl behind it → switch → delete old |
| Strangler fig | Replacing a subsystem or legacy app | Intercept entry point → move routes/features one by one → retire legacy |
| Sprout / wrap (Feathers) | Adding to untested legacy code | New tested function/class called from legacy; wrap old method |

## Legacy code (Feathers)

- Legacy = code without tests. Find **seams** (places to alter behavior without editing: parameters, interfaces, module boundaries, dependency injection).
- Break dependencies minimally to get code under test (extract interface, parameterize constructor, extract and override call).
- Scratch refactoring to learn the code, then throw it away.

## Rules

- Prefer automated/IDE refactorings and compiler-guided moves (Rust: change a type, follow errors).
- Don't refactor cold code nobody changes; prioritize hotspots (churn × complexity).
- Don't refactor and upgrade dependencies in the same step.
- Stop when the motivating change is easy; perfection is not the goal.
- Public API changes are not refactorings for consumers: use `change-impact`.
