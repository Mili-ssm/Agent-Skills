# `store/` package and the `records.py` split (A14 Task 5 + review A6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned · Branches: stacked, `refactor/memory-store-clean` (from `dev` 6cb7571) → `refactor/memory-store-move` → `refactor/memory-records-split` · Date: 2026-11-27

**Goal:** the store's modules live in `engine/store/`, and `records.py` (1,856 lines, 56 importers) is split by responsibility inside it; behavior unchanged.

**Architecture:** first the move (A14 Task 5, [plan](2026-11-26-memory-engine-packages.md)): `records`, `syntheses`, `project_syntheses`, `store_git`, `index`, `notes`, `check`, `rules`, `shortcheck` and `digest_text` → `fingerprints` go to `engine/store/` with the A14 method (alias imports `from store import records`, measured import rules: store imports only stdlib, `core` and `store`). Then the split of `store/records.py` (review A6), along its own sections:

| Module | Holds (from `records.py`) |
|---|---|
| `store/memory.py` | `Memory`, field checks and parsing (`_checked_*`, `_parse*`, `load_memories`), `slug_of`, rendering and `write_memory`, `is_live`, `update`, `observe`, `FieldTypeError` |
| `store/projects.py` | git and project roots (`_git_common_dir`, `_main_worktree`, `_toplevel`, `project_root`, `project_dir`), the registry (`read_registry`, `register_project`, `forget_project`), `memories_root`, `global_memories_root`, `project_key`, `under_temp`, `tracked_memories`, `mark_repository`, `ensure_excluded`, `default_store` |
| `store/cases.py` | sightings and sessions (`sighting*`, `session_key`, `normalized_sources`, `sessions`, `projects`), standing and quarantine, `Case`, cases, versions, `Tally`, `reword_note`, `got_worse`, `mark_words`, `add_case`, `add_sighting` |
| `store/pairs.py` | `similarity`, `Budget`, `pairs`, `refuted_pairs`, `differing_words`, `flagged_words` |
| `store/journal.py` | `Logged`, `log_before`, `last_log_entry`, `restore` |
| `store/terms.py` | forbidden terms and secrets (`Term`, `parse_term`, `read_terms`, `term_hits`, `forbidden_line`, `secret_in`, `ForbiddenListError`), `inside`, `store_is_writable` |
| `store/matching.py` | `tokenize`, `containment`, `match_memories`, `Related`, `related_records` |
| `store/records.py` | a facade: imports the modules above and re-exports their public names, so the 56 importers keep `records.X` while they migrate (parallel change); it holds no logic |

Exact boundaries follow the call graph (Task 3 measures it); a helper used by two modules goes to the lower one; no cycle.

**Tech Stack:** Python 3.12 engine, 3.11 for what `bin/` reaches (ADR 0033); Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** owner rulings 2026-11-26 (feature packages, ADR 0034; "continue with the rest of the refactors"); review A6 ([project review](../../studies/2026-11-24-project-review.md)); backlog A6, A14.

## Global Constraints

- Behavior unchanged: CLI output, files, `mem session-index`, goldens.
- ADR 0031 on every touched file; measure only with `ruff check --no-fix` (ruff.toml sets `fix = true`); Task 1 cleans the store tests first (27 files, about 300 findings).
- Facade rule: `store/records.py` has only imports and re-exports (`from store.memory import Memory as Memory` style or `__all__`), no function bodies; a `monkeypatch.setattr(records, "X", …)` no longer reaches code that calls `X` inside a submodule, so every such patch is retargeted to the defining module and proven by removal in a scratch copy.
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
- [ ] 27 files (tests, `shortcheck.py`, `evals/rules_layout/run_trial.py`, `evals/signal/score.py`), parallel batches, one commit per file. Check: suite unchanged; lint zero on each.

### Task 2: Move into `store/`
- [ ] `git mv` the ten modules; importers, string refs (`bin/mem-capture` `import_module("records")`, eval answer keys), `__file__` paths, `ruff.toml` py311, tests to `tests/store/` when they import no other test file; the store rule. Check: suite, goldens, collected count, self-checks.

### Task 3: Split `store/records.py`
- [ ] Measure the call graph and module-level state; cut the seven modules by verbatim moves; `records.py` becomes the facade; retarget and prove patches; the no-facade-inside-store rule. Check: suite, goldens, each module under 600 lines.

### Task 4: Split reviews and gate
- [ ] Split reviews of `check.py` (1,396 lines) and `syntheses.py` (1,313): split along their sections if cohesive parts exist, else record why not. Full matrix; docs (ADR 0034 `## Review`, backlog A6/A14, resume state, this plan).

## Deferred findings

| Finding | Ruling |
|---|---|

## Kill criteria

- A golden changes; a cycle; a patch stops reaching its code; the collected count changes across a move; a module over 600 lines; the facade needs logic.
