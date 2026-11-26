# One home for the background-job lifecycle (`jobs.py`, review A3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

Status: planned · Branch: `refactor/memory-jobs` (stacked on `refactor/memory-headless`, PR #201) · Date: 2026-11-26

**Goal:** the background-job pieces that are copied identically across the memory plugin's background scripts live once, in `engine/jobs.py`; behavior unchanged.

**Architecture:** `engine/jobs.py` (stdlib only, Python 3.11-safe: `bin/` imports it, ADR 0033) receives the generic job pieces now in `engine/auto_state.py` (`STATUS_NAME`, `STALE_RUNNING_SECONDS`, `read_json`, `write_json`, `private_dir`, `take_run_lock`, `run_lock_held`, `failure`) and one copy of each piece that is duplicated identically. `auto_state.py` keeps only what is specific to `mem-auto` (`auto_dir`, its `failure_line`). Callers import `jobs` and call `jobs.X`; no re-export from `auto_state`.

**Tech Stack:** Python 3.12 engine, 3.11 for `bin/` and what it imports; Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist, pre-commit.

**Spec:** [refactor plan](2026-11-23-memory-refactor.md) task "One headless launcher and one job lifecycle" (the `jobs.py` half) and review A3 in the [project review](../../studies/2026-11-24-project-review.md); owner rulings 2026-11-26: a new `jobs.py`; **only identical copies move** (copies that differ stay where they are). [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md), [ADR 0033](../../adr/0033-memory-bin-scripts-need-python-3-11.md).

## What moves and what stays (inventory 2026-11-26)

| Piece | Copies | Moves to `jobs` |
|---|---|---|
| Generic pieces of `auto_state.py` (lock, `failure`, JSON, `private_dir`, constants) | 1, imported by about 10 modules | yes |
| State folder: `MEM_DATA`, else `XDG_STATE_HOME`, else `~/.local/state`, plus `agent-memory` | `bin/mem-capture` `data_dir`, `corroborate_state.data_dir`, `bin/mem-synthesize` `state_dir`, `research_pipeline` (verify identical) | yes, as `jobs.state_dir()`; callers keep their names as thin calls only if a test patches them |
| `mem.py` `data_dir(env)` (returns None without `HOME`) | 1 | no: a different contract |
| JSON-lines log, `O_APPEND`, mode 0600 | `bin/mem-capture`, `corroborate_state` | yes, if identical |
| `runs/*` older than 30 days by mtime | `bin/mem-auto`, `bin/mem-settle`, `research_pipeline` | yes, if identical |
| `failure_line` "Automatic X failed on DATE: REASON; log: L (Y ack clears this)." with strict date parse | `auto_state`, `settle_state` | yes, parameterized by job name and ack command |
| `failure_line` of capture (tolerant date parse), of corroborate (other text) | 1 each | no: they differ |
| `bin/mem-settle` `_lock_held` | duplicates `run_lock_held` | yes: call `jobs.run_lock_held` |
| `budget_of` (inf accepted or not, defaults 2.0 / 0.25), `save_status` (keeps or drops `failure: None`), prune "keep 20 / 14 days", text `log.txt` writers, `settle.locked` (raises `Busy`) | several, different | no |

## Global Constraints

- Behavior unchanged: same files, paths, modes, JSON keys, log lines, session-start lines, exit codes.
- "Identical" is proven, not assumed: Task 2's characterization tests run every copy that moves on the same inputs and compare outputs; a copy that differs in any output stays.
- `jobs.py` stdlib only and 3.11-safe; add `"plugins/memory/engine/jobs.py" = "py311"` to `ruff.toml` `[per-file-target-version]`; `test_bin_python_floor.py` covers it through the `bin/` scripts.
- Callers call `jobs.X` through the module attribute; tests that `monkeypatch.setattr(auto_state, ...)` a moved name are retargeted to `jobs` in the same commit (only the target changes).
- Clean (ADR 0031): every touched Python file passes `uvx ruff@0.17.6 check --no-fix`, `uvx ruff@0.17.6 format --check`, `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings`, no suppression. Known debt at plan base: `engine/settle_state.py` 4 Ruff, unformatted, one `type: ignore`; `engine/capture_state.py` 1 Ruff, unformatted; `engine/auto_state.py` unformatted; tests `test_capture_state.py` 9 Ruff / 6 basedpyright, `test_projects.py` 16 Ruff, `test_safe_io.py` 6 Ruff. Task 1 measures every file the later tasks touch and cleans what is unclean, one commit per file, before any move (lesson of A2: a signature or import change drags unclean callers in).
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

- [ ] **Step 1:** List every file that imports `auto_state` or calls a piece in the table's "yes" rows (engine, `bin/` extensionless scripts, `evals/`, tests) with its Ruff, format and basedpyright counts; record the list in the report.
- [ ] **Step 2:** Clean each unclean one, behavior unchanged, one commit each (`refactor(memory): <file> clean` / `test(memory): <file> clean`). Large ones (over ~40 findings) get their own dispatch.

### Task 2: Characterization tests of the pieces that move

**Files:** Create `plugins/memory/engine/tests/test_jobs_golden.py`.

- [ ] **Step 1:** For each "yes" row: run every copy on the same inputs and assert equal outputs, plus a literal expected value (state folder for env combinations incl. empty and unset; a JSON-lines append's file content and mode; prune with files at 29 and 31 days; `failure_line` text for auto and settle with a fixed status, a stale running state and no failure). A row whose copies differ: drop it from the move and say so in the report.
- [ ] **Step 2:** Run at base: pass. Commit `test(memory): golden behavior of the job pieces that move to jobs.py`.

### Task 3: `engine/jobs.py` with the generic pieces of `auto_state`

**Files:** Create `engine/jobs.py`, `engine/tests/test_jobs.py`; modify `engine/auto_state.py`, every importer of a moved name, `ruff.toml`.

- [ ] **Step 1:** Move `STATUS_NAME`, `STALE_RUNNING_SECONDS`, `read_json`, `write_json`, `private_dir`, `take_run_lock`, `run_lock_held`, `failure` verbatim; importers call `jobs.X`; patches retargeted. Unit tests for `jobs` only where no existing test covers a piece.
- [ ] **Step 2:** Suite, goldens, self-checks, lint pass. Commit `refactor(memory): jobs.py holds the generic job pieces of auto_state`.

### Task 4: One copy of each identical piece

- [ ] **Step 1:** `jobs.state_dir()`, the JSON-lines log, the 30-day prune and the parameterized `failure_line(kind, ack_command, ...)` replace the copies Task 2 proved identical; `bin/mem-settle` uses `jobs.run_lock_held`.
- [ ] **Step 2:** Goldens unchanged; suite, self-checks, lint pass. Commit `refactor(memory): one copy of the state folder, job log, prune and failure line`.

### Task 5: Gate and docs

- [ ] **Step 1:** `pre-commit run --from-ref <plan base> --to-ref HEAD`; `python3 scripts/validate.py`; `claude plugin validate .`.
- [ ] **Step 2:** Refactor plan: tick its "One headless launcher and one job lifecycle" task; backlog A3 row; this plan's Status and deferred findings. No CHANGELOG line (pure refactor). Commit.

## Kill criteria

- A golden would have to change: stop and report.
- `jobs` would need to import a plugin module, or a cycle appears.
- A patch stops reaching its code.
- A self-check result differs from base.
- A file to clean exceeds about 60 findings in one dispatch: split it.
