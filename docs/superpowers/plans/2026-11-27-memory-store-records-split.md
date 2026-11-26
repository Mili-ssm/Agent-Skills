# `store/` package and the `records.py` split (A14 Task 5 + review A6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned, pre-mortem 2026-11-27 applied · Branches: stacked, `refactor/memory-store-clean` (from `dev` 6cb7571) → `refactor/memory-store-move` → `refactor/memory-records-split` · Date: 2026-11-27

**Goal:** the store's modules live in `engine/store/`, and `records.py` (1,856 lines, 56 importers) is split by responsibility inside it; behavior unchanged.

**Architecture:** first the move (A14 Task 5, [plan](2026-11-26-memory-engine-packages.md)): `records`, `syntheses`, `project_syntheses`, `store_git`, `index`, `notes`, `check`, `rules`, `shortcheck` and `digest_text` → `fingerprints` go to `engine/store/` with the A14 method (alias imports `from store import records`, measured import rules: store imports only stdlib, `core` and `store`). Then the split of `store/records.py` (review A6), along its own sections:

Nine modules cut along the measured call graph (pre-mortem AST, 2026-11-27), extracted bottom-up, one commit each; module names avoid the facade's function names (`projects`, `cases`, `pairs`) and the common parameter name `memory`:

| Module | Holds (from `records.py`) | Imports (store) |
|---|---|---|
| `store/journal.py` | `CURATION_LOG`, `Logged`, `log_before`, `_log_lines`, `_parsed_log`, `last_log_entry`, `restore` | none |
| `store/memory_model.py` | constants (except `CURATION_LOG`), `Memory`, `FieldTypeError`, `valid_short`, `valid_topic`, `valid_triage_reason`, `TRIAGE_REASON_LIMIT`, `slug_of`, `is_live` | none |
| `store/matching.py` | `STOPWORDS`, `STRONG`, `POSSIBLE`, `MIN_TERMS`, `_TOKEN`, `tokenize`, `_terms`, `_containment_of_terms`, `containment`, `MatchOptions`, `match_memories`, `Related`, `related_records` | memory_model |
| `store/terms.py` | `forbidden_file` … `secret_in`, `inside`, `store_is_writable` | memory_model |
| `store/locations.py` | git roots, registry, memories roots, `project_key`, `under_temp`, `tracked_memories`, `mark_repository`, `ensure_excluded`, `default_store` | memory_model, terms |
| `store/sightings.py` | `MAX_SESSION_ID`, `_PROJECT_*`, `sighting` … `counted`, `Case` … `mark_words`, `has_case` | memory_model |
| `store/pairing.py` | `similarity`, `Budget`, `pairs`, `refuted_pairs`, word lists, `OPPOSITES`, `_PARTNERS`, `flagged_words` | matching, memory_model |
| `store/memory_parse.py` | `logger`, `_date`, `_split`, `_checked_*`, `_optional_fields` … `_parse`, `load_memories` | memory_model, sightings |
| `store/memory_write.py` | `_render` family, `WriteOptions`, `write_memory`, `update`, `observe`, `_log_with`, `add_case`, `SightingOptions`, `add_sighting` | memory_model, memory_parse, sightings |
| `store/records.py` | facade: `from store.<module> import a, b` plus `__all__` (not `a as a`: Ruff PLC0414), re-exporting every name importers use, including non-own names they reach through it (`safe_load`, `_parse`, `_main_worktree`, `replace`, `datetime`, `Path`) | all |

A recut follows these lists; a cycle is fixed by recutting, never by `TYPE_CHECKING` imports (the graph test counts them).

**Tech Stack:** Python 3.12 engine, 3.11 for what `bin/` reaches (ADR 0033); Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** owner rulings 2026-11-26 (feature packages, ADR 0034; "continue with the rest of the refactors"); review A6 ([project review](../../studies/2026-11-24-project-review.md)); backlog A6, A14.

## Global Constraints

- Behavior unchanged: CLI output, files, `mem session-index`, goldens.
- ADR 0031 on every touched file; measure only with `ruff check --no-fix` (ruff.toml sets `fix = true`); Task 1 cleans the store tests first (27 files, about 300 findings).
- Facade rule: `store/records.py` holds only imports and `__all__`, no function bodies. Check: every `records.<attr>` used in engine, `bin/` and evals (about 101 names) is in `dir(records)`.
- Patch rule: patch every binding the code under test looks up: a call through the facade (`records.update` in `mem.py`) needs the facade patched, a direct call inside a submodule (`add_sighting` → `update`) needs the defining module; a `patch_all(monkeypatch, name, fn)` test helper patches both. A negative patch (`got_worse` → `1/0`, asserting it is never called) gets a positive control proving the name is called when not blocked.
- Store's own modules (`syntheses`, `project_syntheses`, `rules`, `digest_text` → `fingerprints`) move off the facade in Task 3 before the no-facade-inside-store rule lands.
- Ruling (coordinator, 2026-11-27): `store` is a base layer like `core`: any package may import it (capture, corroborate, settle, research, digest, session already import `records` at base); `store` imports only stdlib, `core` and `store`.
- Engine modules inside `store/` import siblings directly (`from store import memory`), never through the facade; a rule in `test_import_graph.py` forbids `store/*` importing `store.records`.
- New code imports the submodules; migrating the 56 importers off the facade is a later, optional task (recorded in the backlog).
- Tests: suite on default Python and `--python 3.12.0` (2,671 passed, 5 skipped at base); collected count unchanged by moves; self-checks of `mem-auto`, `mem-settle`, `mem-corroborate`, `mem-synthesize` on 3.11.15 and default.
- No CHANGELOG line (pure refactor). Commits pass every hook; no `SKIP`.

## Review Focus

1. A `monkeypatch` on `records.X` that silently stops reaching the code after the split.
2. Module-level state in `records.py` shared by functions that land in different modules (caches such as `_partners()`, compiled patterns, constants).
3. `isinstance` checks or pickled/YAML-dumped class identities (`Memory`, `Case`, `Term`) that must stay one class.
4. String references (`import_module("records")` in `bin/mem-capture`, `sys.modules` blocks, eval answer keys naming `memory/engine/records.py`).
5. `bin/` closures on Python 3.11: the store modules `bin/` reaches need `py311`.

---

### Task 1: Clean the store tests
- [x] 27 files (tests, `shortcheck.py`, `evals/rules_layout/run_trial.py`, `evals/signal/score.py`), parallel batches, one commit per file. Check: suite unchanged; lint zero on each.

### Task 2: Move into `store/`
- [x] First commit: `_imported_engine_modules` (test_import_graph.py) and `_names` (test_bin_python_floor.py) record `node.module` for `from pkg.mod import x`, so `from store.memory import X` is an edge to `store.memory`, not only `store`; prove with a temporary violating import (pre-mortem: today both ignore it, so several rules pass vacuously).
- [x] (tests left in `tests/`: those that import another test file or are imported by one: `test_check`, `test_rules`, `test_store_git`; the rest of the store-related tests exercise `mem` or other features) `git mv` the ten modules; importers, string refs (`bin/mem-capture` `import_module("records")`, eval answer keys), `__file__` paths, `ruff.toml` py311, tests to `tests/store/` when they import no other test file; the store rule; rename `STORE_MODULES` (add `rules`, `shortcheck`, `fingerprints`), the `test_module_imports_without_mem` params, the `check.py` path in `test_check_stays_pure`; `test_notes_imports_no_other_engine_module` excludes `store/__init__`; `ruff.toml` `store/*` py311; eval answer key `store/records.py`; `test_syntheses` globs `store/*.py`; `test_capture_state` blocks `store`. Check: suite, goldens, collected count, self-checks.

### Task 3: Split `store/records.py`
- [ ] One commit per module, bottom-up in the table order: verbatim move, the facade imports it, patches per the patch rule; then store's own modules off the facade, then the no-facade-inside-store rule; eval answer key → `store/locations.py`. Check per commit: suite, goldens, import graph (no cycle), each module under 600 lines.

### Task 4: Split reviews and gate
- [ ] Split reviews of `check.py` (1,396 lines) and `syntheses.py` (1,313): split along their sections if cohesive parts exist, else record why not. Full matrix; docs (ADR 0034 `## Review`, backlog A6/A14, resume state, this plan).

## Deferred findings

| Finding | Ruling |
|---|---|

## Kill criteria

- A golden changes; a cycle; a patch stops reaching its code; the collected count changes across a move; a module over 600 lines; the facade needs logic.
