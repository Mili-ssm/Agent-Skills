# `store/` package and the `records.py` split (A14 Task 5 + review A6) Implementation Plan

Status: done · merged in #212–#214, 2026-11-26 · unticked boxes are not open work

Pre-mortem 2026-11-26 applied · Branches: stacked, `refactor/memory-store-clean` (from `dev` 6cb7571) → `refactor/memory-store-move` → `refactor/memory-records-split` · Date: 2026-11-26

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

**Goal:** the store's modules live in `engine/store/`, and `records.py` (1,856 lines, 56 importers) is split by responsibility inside it; behavior unchanged.

**Architecture:** first the move (A14 Task 5, [plan](2026-11-26-memory-engine-packages.md)): `records`, `syntheses`, `project_syntheses`, `store_git`, `index`, `notes`, `check`, `rules`, `shortcheck` and `digest_text` → `fingerprints` go to `engine/store/` with the A14 method (alias imports `from store import records`, measured import rules: store imports only stdlib, `core` and `store`). Then the split of `store/records.py` (review A6), along its own sections:

Nine modules cut along the measured call graph (pre-mortem AST, 2026-11-26), extracted bottom-up, one commit each; module names avoid the facade's function names (`projects`, `cases`, `pairs`) and the common parameter name `memory`:

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
- Ruling (coordinator, 2026-11-26): `store` is a base layer like `core`: any package may import it (capture, corroborate, settle, research, digest, session already import `records` at base); `store` imports only stdlib, `core` and `store`.
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
- [x] One commit per module, bottom-up in the table order: verbatim move, the facade imports it, patches per the patch rule; then store's own modules off the facade, then the no-facade-inside-store rule; eval answer key → `store/locations.py`. Check per commit: suite, goldens, import graph (no cycle), each module under 600 lines.

### Task 3b: `store/` becomes `memories/` and `notes/` (owner ruling 2026-11-26)

ADR 0034's revisit trigger fired: `store/` reached 19 modules in two families with different reasons to change. Owner chose two top-level packages over subpackages in `store/` and over keeping it flat. Layering, enforced in `test_import_graph.py`: `notes → memories → core`; `memories` and `notes` are base layers any feature package may import (the `store` ruling, carried over); `memories` never imports `notes`.

| From | To |
|---|---|
| `store/{records,journal,matching,terms,locations,sightings,pairing,rules,shortcheck,fingerprints}.py` | `memories/` (same names) |
| `store/memory_model.py`, `memory_parse.py`, `memory_write.py` | `memories/model.py`, `parse.py`, `write.py` (the package already says "memory") |
| `store/{index,check,syntheses,project_syntheses}.py` | `notes/` |
| `store/notes.py` | `notes/note.py` |
| `store/store_git.py` | `core/store_git.py` (imports only `core`; both families commit the store) |
| `_BaseLoader`, `safe_load` from `store/notes.py` | `core/yaml_load.py` (so `memories` does not import `notes`); `notes/note.py` imports them |

- [ ] One commit per step: (1) `core/yaml_load.py` and `core/store_git.py`; (2) `memories/` move with renames; (3) `notes/` move; (4) delete `store/`, graph rules (`memories` imports only core and memories; `notes` only core, memories, notes; the no-facade rule now for `memories/*`), tests to `tests/memories/` and `tests/notes/`, `ruff.toml` py311 entries, string refs, eval answer keys. Check per step: suite, collected count unchanged, goldens, bin self-checks on 3.11.15, the graph rule bites.

Pre-mortem 2026-11-26 amendments (measured: package graph acyclic; the risk is guards that go vacuous):
- Every guard that names modules by string is retargeted and proven by a temporary violation: `test_import_graph.py` (`store.store_git` check, `test_notes_imports_no_other_engine_module` → allow `core.yaml_load` explicitly, base-layer set, PACKAGE_DEPENDENCIES, STORE_MODULES, no-facade prefix), `tests/capture/test_capture_state.py` `sys.modules` block, `tests/store/test_records_facade.py` `node.module`, `tests/patching.py` prefix (`memories.`, `notes.`), `bin/mem-capture` `import_module("store.records")` (the floor test skips unresolved names).
- Every `from store` in `evals/` (6 files) retargeted, checked by an import smoke test of each eval with `engine/` on `sys.path`.
- `"safe_load"` leaves `mem.py` `_MOVED` (no caller reads `mem.safe_load`; F401 would strip it from `note.py`).
- Modules keep their aliases (`notes_mod` in check/index, `note_files` in mem.py): `note` is a loop variable in 72+ places.
- `ruff.toml` py311 entries for `memories/*`, `notes/*` land with their move; I001 regrouping fixed by hand after `ruff check --no-fix`.
- Remaining facade patches on `records.update` / `records.log_before` move to `patch_all`.
- Docs: ADR 0034 `## Review 2026-11-26` (the revisit trigger fired), README `engine/store/shortcheck.py`, backlog A14.
- Kill: after the last step `grep -rnE "from store|\"store\.|'store'|store/" plugins/memory --include=*.py` and in `bin/` finds anything outside fixtures; a guard stays green when violated; collected count or a golden changes; `mem.<name>` for a `_MOVED` name raises.

### Task 4: Split reviews and gate
- [x] Split `notes/check.py` (1,396 lines) and `notes/syntheses.py` (1,316) by cohesion. Owner 2026-11-26: size is a review trigger, not a cap (a cohesive 1k–3k file can be right); group by function. Pre-mortem 2026-11-26 measured the first cut (check stayed ~771 lines; a `syntheses` ↔ `units` cycle; `synthesis_*`/`*_rules` prefixes in a 12-module `notes/`), so the syntheses go to their own base package. Layering: `notes → syntheses → memories → core` (syntheses import only core and memories today).

| Module | Holds | From |
|---|---|---|
| `notes/fields.py` | `Problem`, `Validator`, `_DATE`, `_MONTH`, `_IMPERATIVES`, `_INSTRUCTION_FIX`, `instruction_word`, `_string` … `_disputed`, `_PART_OF`, `_DISPUTE_KEYS`, `LEVELS`, `OPTIONAL_FIELDS`, `SCHEMAS` | check.py |
| `notes/links.py` | `rule_links` … `orphan_notes` (index freshness went back to `check.py`, commit a91b7f1) with their own `_FENCE`, `_CODE_SPAN`, `_LINK`, `_REFDEF`, `_SCHEME` | check.py |
| `notes/due.py` | `_REQUIREMENTS` … `due_requirements`, `RETEST_DAYS`, `REREAD_DAYS`, `MODEL_SPECIFIC_ROOT` | check.py |
| `notes/check.py` | the rule catalog (names, flat, domain, schema, consistency, topics, placeholders, size, handles, syntheses, supersession), `RULES`, `check`, `invalid_changed` (~770 lines, cohesive) | stays |
| `syntheses/document.py` | `Section`, `Synthesis`, load, validate, source numbering, `shown`, `source_kinds` | notes/syntheses.py |
| `syntheses/units.py` | `Unit`, `_Ref`, `_Line`, `_Parser`, `units`, `without_references`, `fingerprint*`, `is_current`, `word_count`, `first_paragraph`, plus the leaves that break the cycle: `_FENCE`, `_SCHEME`, `_next_fence`, `_relative`, `_file_part`, `_note_key`, `NOTE_FOLDERS`, `MIN_NOTE_PARTS` | notes/syntheses.py |
| `syntheses/edit.py` | `snapshot` … `match_sections` | notes/syntheses.py |
| `syntheses/project.py` | all of `notes/project_syntheses.py` | moved |

- Part A (check) before part B (syntheses); one module per commit; collected count checked after each.
- Before moving code: the AST purity check (`test_check_stays_pure`) and the parametrize lists (`test_import_graph.py` module list, `test_syntheses.py` no-`import mem` list) cover the new modules; `mem.__getattr__` searches the new modules; a test asserts every `_MOVED` name resolves through `mem`.
- `_LINK`/`_FENCE`/`_SCHEME` exist in both files and the two `_LINK` patterns differ: retarget each reference to its defining module (check family → `links`, syntheses family → `units`).
- Locals named `fields`, `due`, `links`, `units` in importers: import those modules under an alias where a local would clash.
- Eval answer key `synthesis-shrink` (`_guard_shrink`) → `syntheses/edit.py`: a location change only, recorded as such.
- Kill: a cycle only TYPE_CHECKING fixes; the `_MOVED` test fails; collected count or a golden changes.

### Task 5: Regroup small modules and map each package (owner permission 2026-11-26, LLM-native)

Owner rule: size is a balance (neither one 10k-line file nor a hundred 100-line files); merge small parts that rarely change. Agents navigate by grep and outline, so each package's `__init__.py` docstring is its module map.

| Merge | Into | Why |
|---|---|---|
| `memories/pairing.py` (244) | `memories/matching.py` (208) | both answer which memories resemble or contradict each other; pairing already imports matching |
| `memories/shortcheck.py` (66) | `memories/model.py` (142) | the short-form check beside `valid_short`; both pure; `problems` enters as `short_problems` (a bare `model.problems` loses the context grep needs) |

- [x] One commit per merge (verbatim; importers, tests, `patch_all`, eval keys, records facade retargeted; test files merge or move with their module); then one commit: every package `__init__.py` docstring lists each of its modules with one line of role, and a test in `test_import_graph.py` checks every module file of every engine package is named in its package docstring (prove it bites). Pre-mortem 2026-11-26: `fingerprints` → `rules` dropped (both define `line()`, and `fingerprints` exists so `digest` and `rules` never import each other). The map test requires a structured entry per module (a docstring line starting with the backticked module name, then its role), globs `*.py` only, skips `__init__` and non-package folders (`synthesize/briefs/`), and is proven by deleting the entry of a common-word module (`run`). Kept apart on purpose: `fingerprints`, `journal` (used by two packages), `core/yaml_load` (keeps `memories` off `notes`), per-feature `state` modules, `terms` vs `locations`. Check: suite (collected count changes only by the new test), goldens, self-checks, graph rules.

## Deferred findings

| Finding | Ruling |
|---|---|
| `_FENCE`, `_SCHEME` identical in `syntheses/units.py` and `notes/links.py` (Task 4 review) | deferred: pre-existing duplicate; `notes` may import `syntheses.units` if a third copy appears |
| Underscore names used across sibling modules after the splits (`document._scan/_read/_write`, `edit._bump/_clean/_guard_shrink`, `_Ref`, `_REF_LINK`) | deferred: make public in a later pass, one rename per commit |
| ADR/plan `check.py (1,396 lines)` flagged as wrong (reviewer read the post-part-A tree) | rejected: 1,396 at 7861bde, before part A |

## Kill criteria

- A golden changes; a cycle; a patch stops reaching its code; the collected count changes across a move; a records module over 600 lines (Task 3 only; Task 4 splits by cohesion); the facade needs logic.
