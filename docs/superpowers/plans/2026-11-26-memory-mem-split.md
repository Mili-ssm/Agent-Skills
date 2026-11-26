# Split `mem.py` into `engine/commands/` (A5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned, pre-mortem 2026-11-26 applied · Branch: `refactor/memory-mem-split` (from `dev` 1af5485), one pull request per task · Date: 2026-11-26

**Goal:** `engine/mem.py` (10,502 lines) becomes the parser, the dispatch and a re-export map; every `cmd_*` handler lives with its logic in `engine/commands/`; behavior unchanged.

**Architecture:** [ADR 0028](../../adr/0028-mem-commands-live-in-an-engine-commands-layer.md). Architect measurement 2026-11-26 (697 symbols, 42 handlers, AST call graph; scripts in the session scratchpad, not kept):

| Module | Commands | ≈ lines | Imports (engine) |
|---|---|---|---|
| `notes/search.py` (pure) | none: BM25 `Corpus`/`rank`, filters, `find`/`search`, `related`, mentions, `search_eval` | 400 | memories, notes |
| `commands/common.py` | none: store resolution, `data_dir`, usage log, `resolve_note`, `_check_terms`/`_refuse_secret`, read-only guards, `_set_field`/`_swap_file`, `_commit_points`, project-synthesis context, `UsageError` | 450 | core, memories, notes, syntheses |
| `commands/admin.py` | terms, projects, init, history | 420 | core, memories |
| `commands/read.py` | check, index, find, topics, show, search, passages, related, search-eval, stats, review | 1,340 | notes, memories, syntheses |
| `commands/edit.py` | new, note, rename, unify; `new_note`; attach-to-section helpers; `_NEW_FIELDS` | 1,250 | notes, syntheses, core |
| `commands/sources.py` | fetch-sources, import | 720 | notes, research, core |
| `commands/synthesis.py` | synthesis, project-synthesis | 1,060 | syntheses, notes |
| `commands/memory.py` | remember, confirm, observe, refute, forget, triage, supersede, merge, distinct, restore, promote, memories, rules, memory, settle | 2,100 | memories, corroborate, digest, settle, syntheses |
| `commands/curate.py` | curate; session-start curation decisions | 1,130 | memories, corroborate, notes, syntheses |
| `commands/hooks.py` | session-index, compact-log, signal | 730 | capture, session, settle, memories |
| `mem.py` | parser, `_dispatch`, `_MOVED` | ≤ 1,350 | everything |

Order inside `commands/` (acyclic): `common → admin, read, edit → sources, synthesis → memory (uses read) → curate (uses memory, edit) → hooks (uses curate, memory)`.

**Tech Stack:** Python 3.12–3.14 (uv), Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** refactor plan [2026-11-23-memory-refactor.md](2026-11-23-memory-refactor.md) item A5; ADR 0028 (owner rulings: parser stays in `mem.py`, `admin` apart, `settle` in `memory`); ADR 0034.

## Global Constraints

- Behavior unchanged: CLI stdout, stderr, exit codes, files, goldens, `mem session-index`; `--help` of `mem` and every subcommand byte-identical (save goldens before Task 1).
- Verbatim moves; handlers raise `UsageError` instead of `build_parser().error` (dispatch prints the same message, exit 2).
- Each moved name tests read as `mem.X` joins `_MOVED` (`dict[str, str]`, name → module); tests patch the defining module or use `tests/patching.py` `patch_all`, never `setattr(mem, …)` for a moved name (guard test, Task 1).
- Call convention (pre-mortem: a `from X import n` binding is not reached by patching the defining module, nor by `patch_all`): command modules call every shared engine name through its module attribute (`common._swap_file`, `index_files.apply_index`), never by a from-import; `patch_all` also walks `commands.*`.
- `commands` is imported only by `mem`; `entry` and feature packages never import it; `importlib` stays banned.
- A ratcheting line ceiling on `mem.py` drops with every task.
- ADR 0031 on every touched file (`ruff check --no-fix` read-only). Commits pass every hook; no `SKIP`. Pure refactor: no CHANGELOG line. One pull request per task to `dev`; merge only on the owner's word.

## Review Focus

1. A `monkeypatch.setattr(mem, name, …)` that no longer reaches the moved code (R1: `mem.time` in `test_fetch_sources.py` would sleep for real, slow but green).
2. Messages and exit codes of the twelve `build_parser().error` sites after `UsageError` (golden first).
3. Module-level handler dicts (`_PS_`, `_SETTLE_`, `_PROJECTS_`, `_TERMS_HANDLERS`) moving with their handlers.
4. Start-up: the session-index hook timed (p50, p95) before and after the hooks task; `sources` stays lazily imported.
5. Each task re-moves from `dev`'s tip and checks every moved function's AST against it (174 commits in nine days; no other work on `mem.py` during A5).
6. Names defined twice after a move (`__getattr__` picking the wrong one): `_MOVED` maps each name to one module.

---

### Task 1: Preparation (no code moves)
- [x] `research/pipeline.py` uses `memories.records.tokenize` instead of `mem.tokenize` (drops the frozen edge `research → mem`); `UsageError` plus dispatch handling, with a golden test of stderr and exit 2 for every former `build_parser().error` site (twelve) first; `_MOVED` becomes a name → module dict and `__getattr__` looks it up directly; `test_import_graph.py` rules for `commands` (only `mem` imports it); the guard test (an AST scan of tests and evals failing on `setattr(mem, n)` / `monkeypatch.setattr(mem, "n")` when `n` is not a def, class or assignment in `mem.py`; a temporary allow-list, today `time`, `apply_index`, `invalid_changed`, `orphan_notes`, that each task shrinks and that is empty after Task 9); delete the dead `mem._read_note` patch (`tests/test_resolve.py`, already a no-op); every `__file__`-relative path made explicit and tested (`mem stats` "mem.py lines" counts `mem.py` by name and its test asserts the exact value; `_TEMPLATES` moves to `commands/common.py` as `parents[1] / "templates"`); `evals/signal/score.py` and `evals/research/run_trial.py` import `tokenize`, `split_frontmatter`, `FrontmatterError` from `memories`/`notes` directly, plus an import-smoke test of `evals/**/*.py`; goldens store the full stderr (usage line included) and `SystemExit.code` from `main()`; the `mem.py` line ceiling test; `--help` goldens of `mem` and every subcommand. Check: suite; goldens; each new guard proven by a temporary violation.

### Task 2: `commands/common.py` and `commands/admin.py`
- [x] Verbatim moves; `_MOVED` entries; ceiling lowered. Check: suite, goldens, help goldens, graph rules.

### Task 3: `notes/search.py` and `commands/read.py`
- [x] As Task 2; `build_corpus` patches retargeted.

### Task 4: `commands/edit.py`
- [x] As Task 2; patches `_edited_note_text`, `_index_files`, `apply_index` retargeted (`_swap_file`, `invalid_changed` already were); `_attach`, `_set_part_of`, `_log_note` live in `edit`; `_section_ref`, `_note_target`, `NewNoteError`, `_sha`, `_log_group`, `_read_body` stay shared in `common`.

### Task 5: `commands/sources.py`
- [ ] As Task 2; local static import from `mem.py`; patches `_download`, `FETCH_MAX_BYTES`, `time`, `_write_text_copy` retargeted.

### Task 6: `commands/memory.py` (with settle)
- [ ] As Task 2; `_merge_pair` patch retargeted.

### Task 7: `commands/curate.py`
- [ ] As Task 2; `_decisions`, `_write_marks`, `orphan_notes` patches; `orphan_notes` and the due queries next to their callers (refactor plan).

### Task 8: `commands/hooks.py`
- [ ] As Task 2; `PAIR_WORK` patch; session-index hook timed before and after (p50, p95).

### Task 9: `commands/synthesis.py`, then docs
- [ ] As Task 2 (last: highest churn; `_write_logged_changes` patch retargeted; the allow-list ends empty); then ADR 0034 Review line, backlog A5, refactor plan item, resume state.

## Deferred findings

| Finding | Ruling |
|---|---|

## Kill criteria

- A task needs a patch target that is neither its own module nor allow-listed; a rebase conflict inside a moved function body (redo the move from `dev`'s tip, never hand-merge); allow-list entries left after Task 9.
- A golden, stdout, stderr or exit code changes; a patch stops reaching its code; a cycle or a `commands` importer other than `mem`; a module over 2,600 lines; the session-index hook p95 rises by more than 100 ms.
