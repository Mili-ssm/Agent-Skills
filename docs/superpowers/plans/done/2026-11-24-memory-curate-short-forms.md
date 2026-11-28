# Memory: stuck short forms in curation, owner-confirmed manual lessons

Status: done · merged in #185, 2026-11-24

Owner request 2026-11-24. Branch `fix/memory-curate-short-forms` from `dev`.

## Why

- Two established lessons had no short form: the automatic fill's checker refused the proposal twice (`FILL_ATTEMPTS`), the fill then skips them for good, no curation item lists them, and `mem rules --more` says the background pass will still write them.
- A lesson written with `mem remember` can never load: `rules.eligible` needs origin `transcript` and `confirm --by-owner` refuses other origins. The owner reviewed the manual lessons and vouched for ten.
- No command sets the `weight` of an existing lesson; the owner wants the vouched ones light (provisional, not prioritized).

## Tasks

- [x] 1. Engine: `mem curate` lists eligible lessons with no valid short form whose fill attempts on the present claim are used up, and `mem rules --more` names that item. Check: engine tests pass, new tests fail with the change reverted.
- [x] 2. Data: merged three duplicate pairs and forgot three outdated or one-off lessons; `mem restore` undoes each. Five other proposed duplicates were only overlapping and stay. Check: `mem curate --global` lists none of the kept records.
- [x] 3. Docs and changelog: `plugins/memory/CHANGELOG.md` Unreleased, the curator agent's item list, README rows that describe loading. Check: `python3 scripts/validate.py`.

Dropped by the owner (2026-11-24), for a later development: loading owner-confirmed manual lessons and `mem memory edit --weight`. The lessons the owner vouched for are a project memory.
