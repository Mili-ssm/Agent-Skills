# One home for the background-job lifecycle (`jobs.py`, review A3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

Status: implemented, merged to dev 2026-11-26 (PR #202) · Branch: `refactor/memory-jobs` (stacked on `refactor/memory-headless`, PR #201) · Date: 2026-11-26

**Goal:** the background-job pieces that are copied identically across the memory plugin's background scripts live once, in `engine/jobs.py`; behavior unchanged.

**Architecture:** `engine/jobs.py` (stdlib only, Python 3.11-safe: `bin/` imports it, ADR 0033) receives the generic job pieces now in `engine/auto_state.py` (`STATUS_NAME`, `LOCK_NAME`, `STALE_RUNNING_SECONDS`, `read_json`, `write_json`, `private_dir`, `take_run_lock`, `failure`, and `lock_held(folder)`, the folder-level body of `run_lock_held`) and one copy of each piece that is duplicated identically. `auto_state.py` keeps only what is specific to `mem-auto`: `auto_dir`, `run_lock_held(data, store)` (its `None` guard, then `jobs.lock_held(auto_dir(...))`) and its `failure_line` wrapper. Callers import `jobs` and call `jobs.X`; `auto_state` binds the moved names from `jobs` only between Tasks 3a and 3c. Where a state-folder function is called in many places, its module keeps the name as a binding (`data_dir = jobs.state_dir`), so call sites do not change.

**Tech Stack:** Python 3.12 engine, 3.11 for `bin/` and what it imports; Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist, pre-commit.

**Spec:** [refactor plan](2026-11-23-memory-refactor.md) task "One headless launcher and one job lifecycle" (the `jobs.py` half) and review A3 in the [project review](../../studies/2026-11-24-project-review.md); owner rulings 2026-11-26: a new `jobs.py`; **only identical copies move** (copies that differ stay where they are). [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md), [ADR 0033](../../adr/0033-memory-bin-scripts-need-python-3-11.md).

## What moves and what stays (inventory 2026-11-26)

| Piece | Copies | Moves to `jobs` |
|---|---|---|
| Generic pieces of `auto_state.py` (lock, `failure`, JSON, `private_dir`, constants) | 1, imported by about 10 modules | yes |
| State folder: `MEM_DATA`, else `XDG_STATE_HOME`, else `~/.local/state`, plus `agent-memory` | `bin/mem-capture` `data_dir`, `corroborate_state.data_dir`, `bin/mem-synthesize` `state_dir`, `research_pipeline` (verified identical by the pre-mortem) | yes, as `jobs.state_dir()`; each module keeps its name as a binding to it |
| `mem.py` `data_dir(env)` (returns None without `HOME`) | 1 | no: a different contract |
| JSON-lines log, `O_APPEND`, mode 0600 | `bin/mem-capture`, `corroborate_state` | yes, if identical |
| `runs/*` older than 30 days by mtime | `bin/mem-auto`, `bin/mem-settle` (`research_pipeline._prune_old_runs` differs: reads the clock itself, no `is_dir` guard) | yes for mem-auto and mem-settle if identical; research stays |
| `failure_line` "Automatic X failed on DATE: REASON; log: L (Y ack clears this)." with strict date parse | `auto_state`, `settle_state` | yes, as `jobs.failure_line(folder, kind, ack, now)`; each module keeps a wrapper with its old signature (`mem.py` calls them) |
| `failure_line` of capture (tolerant date parse), of corroborate (other text) | 1 each | no: they differ |
| `bin/mem-settle` `_lock_held` | duplicates the folder-level body of `run_lock_held` | yes: call `jobs.lock_held(state.dir)` |
| `budget_of` (inf accepted or not, defaults 2.0 / 0.25), `save_status` (keeps or drops `failure: None`), prune "keep 20 / 14 days", text `log.txt` writers, `settle.locked` (raises `Busy`) | several, different | no |

## Global Constraints

- Behavior unchanged: same files, paths, modes, JSON keys, log lines, session-start lines, exit codes.
- "Identical" is proven, not assumed: Task 2's characterization tests run every copy that moves on the same inputs and compare outputs; a copy that differs in any output stays.
- `jobs.py` stdlib only and 3.11-safe; add `"plugins/memory/engine/jobs.py" = "py311"` to `ruff.toml` `[per-file-target-version]`; `test_bin_python_floor.py` covers it through the `bin/` scripts.
- Callers call `jobs.X` through the module attribute; tests that patch or call a moved name through `auto_state` are retargeted in the same commit (only the target changes). Search for attribute chains too, not only `setattr(`: `test_corroborate_fill.py` patches `auto_state.os`, `test_capture_sweep.py` calls `capture_state.auto_state.take_run_lock`.
- `jobs.py` imports no plugin module except `safe_io`.
- Clean (ADR 0031): every touched Python file passes `uvx ruff@0.17.6 check --no-fix`, `uvx ruff@0.17.6 format --check`, `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings`, no suppression. Known debt at plan base: `engine/settle.py` about 20 Ruff, unformatted, 1 basedpyright; `engine/settle_state.py` 4 Ruff, unformatted, one `type: ignore`; `engine/capture_state.py` 1 Ruff, unformatted; `engine/auto_state.py` unformatted; tests `test_capture_state.py` 9 Ruff / 6 basedpyright, `test_projects.py` 16 Ruff, `test_safe_io.py` 6 Ruff. Task 1 measures every file the later tasks touch and cleans what is unclean, one commit per file, before any move (lesson of A2: a signature or import change drags unclean callers in).
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2,498 passed, 5 skipped at plan base); self-checks of `mem-auto`, `mem-settle`, `mem-corroborate` keep their result; `mem-synthesize --self-check` keeps its known failing last assertion.
- Commits pass every hook; no `SKIP`.

## Review Focus

1. A session-start line (`mem session-index`) that changes text or disappears after the move: pinned by Task 2.
2. A lock taken through `jobs` that another process checks through an old path (same file name `run.lock`, same folder).
3. The state folder with `MEM_DATA`, `XDG_STATE_HOME` or `HOME` unset or empty: same result per caller as before.
4. A monkeypatch on `auto_state.X` that no longer reaches the code after the move.
5. `bin/` scripts on Python 3.11 importing `jobs`.

---

### Task 1: Clean what the move will touch

- [x] **Step 1:** Build the file list mechanically: `grep -rlE '\b(au|auto_state)\.'` over engine, `bin/`, `evals/`, tests, plus every file holding a copy in the "yes" rows and its callers; record each with its Ruff, format and basedpyright counts.
- [x] **Step 2:** Clean each unclean one, behavior unchanged, one commit each (`refactor(memory): <file> clean` / `test(memory): <file> clean`). Large ones (over ~40 findings) get their own dispatch.

### Task 2: Characterization tests of the pieces that move

**Files:** Create `plugins/memory/engine/tests/test_jobs_golden.py`.

- [x] **Step 1:** For each "yes" row: assert a literal expected value for each copy (the copies' equality is a cross-check in this task only; Task 4 may change which function a golden calls, never the expected values) (state folder for env combinations incl. empty and unset; a JSON-lines append's file content and mode; prune with files at 29 and 31 days; `failure_line` text for auto and settle with a fixed status, a stale running state and no failure). A row whose copies differ: drop it from the move and say so in the report.
- [x] **Step 2:** Run at base: pass. Commit `test(memory): golden behavior of the job pieces that move to jobs.py`.

### Task 3a: `engine/jobs.py`, with `auto_state` binding the moved names

- [x] **Step 1:** Create `jobs.py` with the pieces named in Architecture (verbatim, `lock_held(folder)` cut from `run_lock_held`); `auto_state` binds them from `jobs` (`STATUS_NAME = jobs.STATUS_NAME`, …) so no caller changes yet; `ruff.toml` py311 line; unit tests for `lock_held`. Suite, goldens, lint pass. Commit `refactor(memory): jobs.py holds the generic job pieces`.

### Task 3b: importers call `jobs`

- [x] **Step 1:** In batches (the `corroborate_*` modules; `bin/` scripts; other engine modules; tests), callers of a moved name call `jobs.X`; patches and attribute chains retargeted. One commit per batch.

### Task 3c: `auto_state` drops the bindings

- [x] **Step 1:** Remove the bindings; `auto_state` keeps `auto_dir`, `run_lock_held`, `failure_line`. Suite, goldens, self-checks, lint pass. Commit.

### Task 4: One copy of each identical piece

- [x] **Step 1:** `jobs.state_dir()` (modules keep their names as bindings), the JSON-lines log, the 30-day prune of `mem-auto`/`mem-settle` and `jobs.failure_line(folder, kind, ack, now)` (modules keep wrappers) replace the copies Task 2 proved identical; `bin/mem-settle` `_lock_held` calls `jobs.lock_held(state.dir)`.
- [x] **Step 2:** Goldens unchanged; suite, self-checks, lint pass. Commit `refactor(memory): one copy of the state folder, job log, prune and failure line`.

### Task 5: Gate and docs

- [x] **Step 1:** `pre-commit run --from-ref <plan base> --to-ref HEAD`; `python3 scripts/validate.py`; `claude plugin validate .`.
- [x] **Step 2:** Refactor plan: tick its "One headless launcher and one job lifecycle" task; backlog A3 row; this plan's Status and deferred findings. No CHANGELOG line (pure refactor). Commit.

## Deferred findings

| Finding | Ruling |
|---|---|
| The commit `c3e8605` (engine modules call `jobs`) fails two tests alone; the next commit fixes them | Accepted: only a bisect landing there sees it |
| `settle_state.minutes_of` no longer parses buffer objects such as `array.array` (falls back to the default) | Accepted: callers pass environment and argparse strings only |
| `failure` names both `jobs.failure` and local variables in several modules | Cosmetic |
| `test_jobs.py` covers only `lock_held`; the moved pieces rely on `test_jobs_golden.py` | Accepted |
| Found by a Python 3.12 run: `mem-auto` and `mem-settle` crashed at start on Python < 3.15 (measured 3.12.0 to 3.14.4) since PR #199 (loaded `mem-synthesize`, now with `@dataclass`, without registering it in `sys.modules`) | Fixed here (d67ef6f) with a guard test in `test_bin_python_floor.py`; test loaders and the `run_trials.py` loader fixed too |
| Under Python 3.12, `test_backfill.py` (101 lint findings, not touched) and `test_synthesize_references.py` (uses its loader) still error on the same cause, test-side only; the suite under 3.12 also has 14 failures that `dev` has | Fixed in the [fixes plan](2026-11-26-memory-fixes.md): every test loader registers its module (the need lasts until Python 3.15, measured), and the guard test covers test and eval loaders |

## Kill criteria

- A golden would have to change: stop and report.
- `jobs` would need to import a plugin module, or a cycle appears.
- A patch stops reaching its code.
- A self-check result differs from base.
- A file to clean exceeds about 60 findings in one dispatch: split it.
- `jobs.py` would import a plugin module other than `safe_io`.
- A Task 3 or 4 diff touches a file not on Task 1's list: stop and clean it first.
- `mem session-index` output differs from base for the auto, settle, capture and corroborate failure fixtures.
