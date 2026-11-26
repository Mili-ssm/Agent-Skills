# `mem-synthesize` logic into the engine (review A4, second part) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned · Branch: `refactor/memory-synthesize-split` (from `dev` 46d4317) · Date: 2026-11-26

**Goal:** `bin/mem-synthesize` becomes a thin launcher; its logic lives in engine modules that `mem-auto`, `mem-settle`, tests and evals import normally instead of loading the script with `exec_module`; behavior unchanged.

**Architecture:** the 1,384-line script moves, verbatim first, into four engine modules with no cycle: `synthesize_run.py` (constants `AGENT`, `ESTIMATE_*`, `FAILED_WORDS_PER_FAKE_ROW`, `HEADER`, `BACKFILL_HEADER`, `TOPIC_LINE`, `ATTACH_LINE`; the shared `TypedDict`s; `default_store`, `session_env`, `topics_without_synthesis`, `attach_lines`, `part_of`, `history_commit`, `_file_logger`, `_aligned`, `say`, `count_parts`, `_syntheses`), `synthesize_topics.py` (`new_row`, `add_references`, `_TopicRun`, `run_topic`, `_reference_status`, `_save_done_list`, `add_topic_references`, `table`, `_dry_run_line`, `_TopicBatch`, `_synthesize`, `run`), `synthesize_backfill.py` (`done_file`, `_backfill_row`, `_BackfillRun`, `backfill_one`, `backfill_table`, `_BackfillBatch`, `_backfill_root`, `_backfill_dry_run`, `_backfill_sessions`, `run_backfill`) and `synthesize_cli.py` (the self-check helpers, `FAKE_NOTE`, `_fake_claude`, `self_check`, `_parser`, `_check_args`, `main`). `synthesize_topics` and `synthesize_backfill` import `synthesize_run`, never each other (if the code needs it, the shared piece moves to `synthesize_run`); `synthesize_cli` imports the three. The launcher puts `engine/` on `sys.path` and calls `synthesize_cli.main()`. `mem-auto` and `mem-settle` import `synthesize_run`/`synthesize_topics` and drop their `SourceFileLoader` block. Existing engine modules `backfill.py` and `synth_pipeline.py` are unchanged.

**Tech Stack:** Python 3.11 for `bin/` and every engine module it imports (ADR 0033), 3.12 engine; Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** [refactor plan](2026-11-23-memory-refactor.md) task "`bin/` holds launchers only" (the `mem-synthesize` half; `bin/` through `uv` is a later plan, owner 2026-11-26); review A4 in the [project review](../../studies/2026-11-24-project-review.md); the [corroborate split](2026-11-26-memory-corroborate-split.md) is the precedent. Owner rule: code files over 1,000 lines get a split review (config plan § Deferred findings names this file). [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md), [ADR 0033](../../adr/0033-memory-bin-scripts-need-python-3-11.md).

## Global Constraints

- Behavior unchanged: same command line, output text, exit codes, files, log lines, commits; `mem-auto`/`mem-settle` output and status files unchanged.
- Moves are verbatim (names kept, underscores included); a rename or a body change is a separate commit after the move, only where lint requires it.
- New engine modules: Python 3.11-safe, added to `ruff.toml` `[per-file-target-version]` at `py311`; `test_bin_python_floor.py` reaches them through the launcher's imports (check it lists them).
- Imports: the engine modules import only stdlib, `config`, `jobs`, `headless`, `backfill`, `synth_pipeline`, `safe_io` and each other as above; no `yaml` at import time where the script had none.
- Monkeypatches and attribute chains in tests (`ms.bf`, `ms.extend`, `ms.run`, `ms.ESTIMATE_PER_BACKFILL`, …) are retargeted to the module where the name is looked up, in the same commit as the move; a patch that no longer reaches its code is a kill criterion.
- Clean (ADR 0031) on every touched file: `uvx ruff@0.17.6 check --no-fix`, `uvx ruff@0.17.6 format --check`, `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings`; no noqa, no `type: ignore`, no config edits beyond the py311 lines. Task 1 measures every file later tasks touch and cleans the unclean ones first, one commit each.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2,649 passed, 5 skipped at base) on default Python and `--python 3.12.0`; `--self-check` of `mem-synthesize`, `mem-auto`, `mem-settle` on 3.11.15 and default.
- No CHANGELOG line (pure refactor). Commits pass every hook; no `SKIP`.

## Review Focus

1. `mem-auto` run with the script's engine missing or broken: today it loads the script at start; after, an import error must fail the same way (same status/log line) — pin it before the move.
2. A test that patches `ms.X` keeps passing because it now patches a copy the code no longer reads.
3. `python3 bin/mem-synthesize` run from another working directory or through a symlink: the launcher finds `engine/`.
4. `--help`, `--dry-run` and the error text of bad arguments byte-identical.
5. A module-level side effect (logging setup, `sys.path` edits, environment reads at import) that ran once in the script now runs at import in `mem-auto`.

---

### Task 1: Inventory and clean what the move will touch

- [ ] List every importer and loader of `bin/mem-synthesize` (bin, engine/tests, evals, hooks) and every `ms.` / alias attribute each uses or patches; record lint counts of each file (Ruff, format, basedpyright). Clean the unclean ones, one commit each. Check: the list is in this plan under Task 1; lint zero on each.

### Task 2: Characterization tests of the command line

- [ ] `engine/tests/test_synthesize_cli_golden.py`: literal expected output and exit code of `--help`, a bad-argument call, the topic `--dry-run` and the backfill dry run on a fixture store, and of `mem-auto`'s synthesis path when the script's engine cannot be imported (Review Focus 1). Pass at base. Commit `test(memory): golden behavior of the mem-synthesize command line`.

### Task 3: Move into the four engine modules

- [ ] 3a `synthesize_run.py` + `synthesize_topics.py` + `synthesize_backfill.py` + `synthesize_cli.py` created by verbatim moves; the launcher becomes `sys.path` setup plus `synthesize_cli.main()`; `ruff.toml` py311 lines. Suite, goldens, self-check pass. Commit `refactor(memory): mem-synthesize logic in engine modules`.
- [ ] 3b `mem-auto` and `mem-settle` import the engine modules and drop the loader block. Commit.
- [ ] 3c Tests and `evals/synthesis/run_trials.py` import the engine modules instead of loading the script; patches retargeted. One commit per batch.

### Task 4: Gate and docs

- [ ] Full suite on 3.12.0, 3.13.5, 3.14.4, default; self-checks on 3.11.15 and default; `pre-commit run --from-ref dev --to-ref HEAD`; `python3 scripts/validate.py`; `claude plugin validate .`. Refactor plan progress line, backlog A4 row, config plan's split-review bullet, this plan's Status and deferred findings, resume state.

## Deferred findings

| Finding | Ruling |
|---|---|

## Kill criteria

- A golden would have to change.
- A cycle between the new modules, or one imports `yaml` at import time where the script did not.
- A patch stops reaching its code.
- A self-check result differs from base.
- A new module over 600 lines after formatting: split it before going on.
- A Task 3 diff touches a file not on Task 1's list: clean it first.
