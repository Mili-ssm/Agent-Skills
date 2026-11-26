# `mem-corroborate` launcher split (first part of A4): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

Status: planned · Branch: `refactor/memory-corroborate-split` (stacked on `refactor/memory-config`, PR #199) · Date: 2026-11-26

**Goal:** `bin/mem-corroborate` becomes a thin launcher; its logic lives in engine modules, every touched file is clean under ADR 0031, and behavior is unchanged. Then A2 can put all seven `claude -p` launchers behind `headless.py`.

**Architecture:** the 1,873-line script holds the state folder, model sessions, journal and undo, the applier, the run (`execute`), three jobs (fill, reword, digest) and the commands. They move, verbatim first, into five engine modules ordered so no cycle exists: `corroborate_run.py` (state folder, sessions, `_ask`, helpers, journal and undo, `Applier`, `execute`), `corroborate_fill.py`, `corroborate_reword.py`, `corroborate_digest.py` (each imports `corroborate_run`), and `corroborate_cli.py` (the `cmd_*` functions, `self_check`, `main`; imports the four). `engine/corroborate.py` (pure decisions) is unchanged. The launcher keeps the guarded import and the `auto` failed-status path for an engine that cannot load (no `yaml`).

**Tech Stack:** Python 3.12, Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist, pre-commit.

**Spec:** "`bin/` holds launchers only" task of [the refactor plan](2026-11-23-memory-refactor.md) (review A4, Q8); owner rulings 2026-11-26: split before A2; [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md). **One-time exception (owner, 2026-11-26), not a project rule:** for this plan only, commits may skip the `ruff-check`, `ruff-format` and `basedpyright` hooks by name until the plan is finished; the last task and the pre-push gate run every hook on the whole range.

## Global Constraints

- Behavior unchanged: same commands, flags, output, exit codes, files written (state folder, journal, logs, run folders), model command lines and environments. No change to a test's assertions; only what a test loads and which module it patches may change.
- Cross-module calls inside the five modules go through the module attribute (`corroborate_run.run_session(...)`, never `from corroborate_run import run_session`), so a test's `monkeypatch.setattr(corroborate_run, "run_session", …)` reaches every caller. Same for `_ask`, `execute`, `MEM`, `apply_fill`, `fill_auto`, `reword_auto`, `digest_auto`.
- `test_import_graph.py` keeps passing: no cycle (jobs import `corroborate_run`; only `corroborate_cli` imports the jobs), no `importlib` in the engine.
- The launcher keeps: its shebang and mode, `sys.path` setup, the unguarded `auto_state`, `safe_io`, `capture_state` imports, the guarded engine import with `IMPORT_ERROR`, the "cannot load the engine" messages and `auto`'s failed-status write when the engine cannot load. `fake_plugin` in the tests copies only `bin/mem-corroborate` and links `engine/`: nothing new may live in `bin/`.
- Clean means: `uvx ruff@0.17.6 check --no-fix <files>`, `uvx ruff@0.17.6 format --check <files>`, `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings <files>` report nothing. No suppressions; no edit to lint configs.
- Recipes as in [the A1 plan](2026-11-26-memory-config.md) Global Constraints (logging for broad excepts, whole-try extraction, `ValueError` subclass for `TRY004`, explicit `check=False`, `\uXXXX` escapes, `**options: Unpack[...]` with `Required[]` and callers checked, PLR6201 tuples where the left side can be unhashable data, no `import x as x`).
- Commits: Task 1 commits with `SKIP=ruff-check,ruff-format,basedpyright` (the one-time exception). Tasks 2–7 each stage only the files they make clean, so their commits pass every hook; if one cannot, it uses the same `SKIP` and says why.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2,449 passed, 5 skipped at base); `plugins/memory/bin/mem-corroborate --self-check` passes.

## Review Focus

1. A test patch that silently stops reaching the code (patched on one module, called through another): each patched name in Task 1 is exercised by the test that patches it, and that test fails if the patch is removed.
2. `auto` with an engine that cannot load: still writes its failed status and exits as before.
3. `execute`'s order of journal writes, applies and log lines; undo of a run made before the split (same journal format).
4. `fill`, `reword`, `digest`: same run folders, state files and sheets; dry runs write nothing.
5. The detached `mem-capture` → `mem-corroborate auto` start still works (path and argv unchanged).

---

### Task 1: Verbatim move into five engine modules; thin launcher; tests patch the engine

**Files:** Create: `engine/corroborate_run.py`, `engine/corroborate_fill.py`, `engine/corroborate_reword.py`, `engine/corroborate_digest.py`, `engine/corroborate_cli.py`. Modify: `bin/mem-corroborate`, `engine/tests/test_mem_corroborate.py` (loaders and patch targets only).

- [ ] **Step 1:** Move each function, class and constant verbatim to its module (sections as named in Architecture); qualify cross-module calls per Global Constraints; the launcher becomes header, `sys.path`, guarded `import corroborate_cli` (plus what the failed-status path needs) and `main`.
- [ ] **Step 2:** In `test_mem_corroborate.py` replace launcher loads used for attribute access with engine imports and point each `monkeypatch.setattr` at the module that now defines the name; keep subprocess runs of the launcher as they are.
- [ ] **Step 3:** Prove Review Focus 1: for each patched name, remove its patch in a scratch copy and see its test fail; list the results in the report.
- [ ] **Step 4:** Suite passes; `--self-check` passes; `mem-corroborate --help` and each subcommand's `--help` byte-identical to base. Commit with the `SKIP` of the exception.

### Task 2: `corroborate_run.py` clean

- [ ] **Step 1:** Format, small rules, types, structural findings; suite after each function. Commit (stage this file only).

### Task 3: `corroborate_fill.py` clean

- [ ] **Step 1:** As Task 2.

### Task 4: `corroborate_reword.py` and `corroborate_digest.py` clean

- [ ] **Step 1:** As Task 2, both files.

### Task 5: `corroborate_cli.py` and the launcher clean

- [ ] **Step 1:** As Task 2; `--help` outputs byte-identical to base.

### Task 6: Tests split by job, clean

**Files:** Replace `engine/tests/test_mem_corroborate.py` with `test_corroborate_run.py`, `test_corroborate_fill.py`, `test_corroborate_reword.py`, `test_corroborate_digest.py`, `test_corroborate_cli.py` (shared helpers in `conftest.py` only if two or more files use them).

- [ ] **Step 1:** Move each test verbatim to the file of the job it covers; the count of collected tests is unchanged (`pytest --collect-only -q | tail -1` before and after).
- [ ] **Step 2:** Make every new file clean; suite passes. Commit.

### Task 7: Gate and docs

- [ ] **Step 1:** `pre-commit run --from-ref <plan base> --to-ref HEAD` passes with every hook; refactor plan: the "`bin/` holds launchers only" task notes mem-corroborate done; backlog A4 row and Q8 (`test_mem_corroborate.py` split) updated; this plan's Status. `python3 scripts/validate.py`. Commit.

## Kill criteria

- A test assertion must change, or a removed patch does not fail its test and cannot be made to reach the code: stop and report.
- A module would import another in a cycle: stop and re-cut the modules.
- Any `--help` or `--self-check` output differs from base: stop.
