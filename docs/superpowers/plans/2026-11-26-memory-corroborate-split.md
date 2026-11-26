# `mem-corroborate` launcher split (first part of A4): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

Status: in progress — Tasks 1, 2a, 2b committed (752b633, f2c6abe); Task 2 review running; next Task 3 · Branch: `refactor/memory-corroborate-split` (stacked on `refactor/memory-config`, PR #199) · Date: 2026-11-26

**Goal:** `bin/mem-corroborate` becomes a thin launcher; its logic lives in engine modules, every touched file is clean under ADR 0031, and behavior is unchanged. Then A2 can put all seven `claude -p` launchers behind `headless.py`.

**Architecture:** the 1,873-line script holds the state folder, model sessions, journal and undo, the applier, the run (`execute`), three jobs (fill, reword, digest) and the commands. They move, verbatim first, into six engine modules ordered so no cycle exists: `corroborate_state.py` (stdlib, `auto_state`, `safe_io` and `capture_state` only, no `yaml`: `data_dir`, `corroborate_dir`, `budget_of`, `save_status`, `append_log`, `write_private`, `write_private_bytes`, `Journal`, `undo_run`, `forget_run`, and the constants these use), `corroborate_run.py` (sessions, `_ask`, shared job helpers `_fill_world` and `_cell`, the briefs, `*_MODEL`, `SETTLE_*`, `MEM`, `Applier`, `execute`, `read_object`, `digest`, `read_bytes`), `corroborate_fill.py`, `corroborate_reword.py`, `corroborate_digest.py` (each imports `corroborate_run`; never each other), and `corroborate_cli.py` (the `cmd_*` functions, `self_check`, `main`; imports the rest). `engine/corroborate.py` (pure decisions) is unchanged. The launcher imports `corroborate_state` (and `auto_state`, `safe_io`, `capture_state`) unguarded and `corroborate_cli` guarded: when the engine cannot load, `auto` still writes its failed status and log line through `corroborate_state` exactly as `execute`'s `IMPORT_ERROR` branch does today, and `status`, `ack`, `undo`, `--help` and `--self-check` keep working, as at base.

**Tech Stack:** Python 3.12, Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist, pre-commit.

**Spec:** "`bin/` holds launchers only" task of [the refactor plan](2026-11-23-memory-refactor.md) (review A4, Q8); owner rulings 2026-11-26: split before A2; [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md). **One-time exception (owner, 2026-11-26), not a project rule:** for this plan only, commits may skip the `ruff-check`, `ruff-format` and `basedpyright` hooks by name until the plan is finished; the last task and the pre-push gate run every hook on the whole range.

## Global Constraints

- Behavior unchanged: same commands, flags, output, exit codes, files written (state folder, journal, logs, run folders), model command lines and environments. No change to a test's assertions; only what a test loads and which module it patches may change.
- Cross-module calls inside the five modules go through the module attribute (`corroborate_run.run_session(...)`, never `from corroborate_run import run_session`), so a test's `monkeypatch.setattr(corroborate_run, "run_session", …)` reaches every caller. Same for `_ask`, `execute`, `MEM`, `apply_fill`, `fill_auto`, `reword_auto`, `digest_auto`.
- `test_import_graph.py` keeps passing: no cycle (jobs import `corroborate_run`; only `corroborate_cli` imports the jobs), no `importlib` in the engine.
- Name-to-module table (Architecture) is binding; `IMPORT_ERROR` branches leave the moved code (their behavior moves to the launcher): the one non-verbatim change of Task 1.
- `MEM = Path(__file__).parent.parent / "bin" / "mem"` with NO `resolve()` (comment why: `fake_plugin` links `engine/`, and a resolved path would reach the real `bin/mem`).
- `--help` texts: capture every `--help` output at base before Task 1 (scratchpad); `main` keeps the launcher's description text exactly (pass it in or copy the first docstring line).
- Positional order frozen for patched names: `_ask` keeps `name` at index 2 (a test reads `args[2]`), `run_session(cmd, work)`, `apply_fill`'s call shape. PLR6201: keep tuple membership where the left side comes from JSON or YAML (e.g. `load not in ("yes", "index", "no")` from the owner-edited fill file); Task 3 adds a test with `"load": ["yes"]`. Review the auto-fix diff of every hook run.
- Test assertions: mechanical rewrites that keep meaning are allowed (named constants with the same value for PLR2004; `PLC1901` only where the value cannot be `None`); any other rewrite is an assertion change (controller ruling 2026-11-26).
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

- [x] **Step 1:** Move each function, class and constant verbatim to its module (sections as named in Architecture); qualify cross-module calls per Global Constraints; the launcher becomes header, `sys.path`, guarded `import corroborate_cli` (plus what the failed-status path needs) and `main`.
- [x] **Step 2:** In `test_mem_corroborate.py` replace launcher loads used for attribute access with engine imports and point each `monkeypatch.setattr` at the module that now defines the name; keep subprocess runs of the launcher as they are.
- [x] **Step 3:** Prove Review Focus 1: for each patched name, remove its patch in a scratch copy and see its test fail; list the results in the report.
- [x] **Step 3b:** Add a test of the engine-unloadable path: `fake_plugin` with a stub `yaml` that raises on import; `auto` writes `status.json` failed with reason `engine import error`, appends its log line with the same keys as base, exits as base; `status` and `ack` still work. Run it at base first (it must pass there).
- [x] **Step 4:** Suite passes; `--self-check` passes; `mem-corroborate --help` and each subcommand's `--help` byte-identical to base. Commit with the `SKIP` of the exception.

### Task 2a: `corroborate_state.py` and `corroborate_run.py` except `execute`, clean

- [x] **Step 1:** Format, small rules, types, structural findings outside `execute`; suite after each function; repeat Task 1 Step 3 at the end. Commit (stage the clean file(s) only; `corroborate_run.py` with `execute` still unclean uses the exception's `SKIP`).

### Task 2b: `execute` clean

- [x] **Step 1:** Decompose `execute` (about 310 lines, closures) along its phases; suite after each step; repeat Task 1 Step 3. Commit with every hook.

### Task 3: `corroborate_fill.py` clean

- [ ] **Step 1:** As Task 2b, plus the `"load": ["yes"]` test.

### Task 4: `corroborate_reword.py` and `corroborate_digest.py` clean

- [ ] **Step 1:** As Task 2b, both files.

### Task 5: `corroborate_cli.py` and the launcher clean

- [ ] **Step 1:** As Task 2b; `--help` outputs byte-identical to base.

### Task 6: Tests split by job, clean

**Files:** Replace `engine/tests/test_mem_corroborate.py` with `test_corroborate_run.py`, `test_corroborate_fill.py`, `test_corroborate_reword.py`, `test_corroborate_digest.py`, `test_corroborate_cli.py` (shared helpers in `conftest.py` only if two or more files use them).

- [ ] **Step 6a:** Move each test verbatim to the file of the job it covers; shared helpers (57 functions and the `w` fixture) go to a helper module `engine/tests/corroborate_world.py` imported by the five files (fixtures through a `conftest.py` in no wider scope than needed); the count of collected tests is unchanged (`pytest --collect-only -q | tail -1` before and after). Commit with the exception's `SKIP`.
- [ ] **Steps 6b–6g:** one dispatch per file (the helper module and the five test files): make it clean (150 Ruff, 43 basedpyright findings across them at base, 68 of them PLR2004), suite passes; commit with every hook.

### Task 7: Gate and docs

- [ ] **Step 1:** `pre-commit run --from-ref <plan base> --to-ref HEAD` passes with every hook; refactor plan: the "`bin/` holds launchers only" task notes mem-corroborate done; backlog A4 row and Q8 (`test_mem_corroborate.py` split) updated; this plan's Status. `python3 scripts/validate.py`. Commit.

## Kill criteria

- A test assertion must change, or a removed patch does not fail its test and cannot be made to reach the code: stop and report.
- A module would import another in a cycle: stop and re-cut the modules.
- Any `--help` or `--self-check` output differs from base: stop.
- A `fake_plugin` test passes only after `fake_plugin` itself changes: `MEM` points to the wrong place; stop.
- The engine-unloadable behavior needs more than about 40 lines in `bin/`: re-cut.
- Reword would import fill, or digest reword: stop and re-cut.
- A Task 6 dispatch runs out of turns, or more than 5 assertions need a non-mechanical rewrite: stop and ask the owner.
