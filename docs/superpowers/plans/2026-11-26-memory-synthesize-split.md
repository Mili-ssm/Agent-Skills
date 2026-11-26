# `mem-synthesize` into an `engine/synthesize/` package (review A4, second part; package pilot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned (pre-mortem 2026-11-26 applied) · Branch: `refactor/memory-synthesize-split` (from `dev` 46d4317) · Date: 2026-11-26

**Goal:** the synthesis job lives in one feature package, `engine/synthesize/`; `bin/mem-synthesize` becomes a thin launcher; `mem-auto`, `mem-settle`, tests and evals import the package instead of loading the script with `exec_module`; behavior unchanged. This is the pilot of the owner's ruling to organize `engine/` into feature packages (2026-11-26); the other packages follow in a later plan, one package per pull request.

**Architecture:** package `engine/synthesize/` (`__init__.py` empty):

| Module | From | Holds |
|---|---|---|
| `pipeline.py` | `engine/synth_pipeline.py` (moved whole) | the topic pipeline (`run_session`, lean loop, briefs path) |
| `references.py` | `engine/backfill.py` (moved whole) | reference backfill sessions (`select`, `session_cmd`, …) |
| `briefs/` | `engine/synth_briefs/` | the brief `.md` files |
| `run.py` | `bin/mem-synthesize` | constants (`AGENT`, `ESTIMATE_*`, `FAILED_WORDS_PER_FAKE_ROW`, `HEADER`, `BACKFILL_HEADER`, `TOPIC_LINE`, `ATTACH_LINE`), `default_store`, `session_env`, `topics_without_synthesis`, `attach_lines`, `part_of`, `history_commit`, `_file_logger`, `_aligned`, `say`, `count_parts` |
| `backfill.py` | `bin/mem-synthesize` | `done_file`, `_backfill_row`, `_BackfillRun`, `backfill_one`, `backfill_table`, `_BackfillBatch`, `_backfill_root`, `_backfill_dry_run`, `_backfill_sessions`, `run_backfill`, `BackfillRunOptions`, `BackfillOneOptions`, `BackfillBatchOptions` |
| `topics.py` | `bin/mem-synthesize` | `new_row`, `add_references`, `_TopicRun`, `run_topic`, `_reference_status`, `_save_done_list`, `add_topic_references`, `table`, `_dry_run_line`, `_TopicBatch`, `_synthesize`, `run`, `RunOptions`, `TopicOptions`, `ReferenceOptions`, `TopicReferenceOptions` |
| `cli.py` | `bin/mem-synthesize` | self-check helpers, `FAKE_NOTE`, `_fake_claude`, `self_check`, `_parser`, `_check_args`, `main(description)` |

Import edges (no cycle): `run` imports `pipeline`; `backfill` imports `run`, `references`; `topics` imports `run`, `backfill`, `pipeline` (one edge `topics → backfill`, never the reverse: `add_references` and `_save_done_list` call `backfill_one`/`done_file`); `cli` imports all. `syntheses.py` and `project_syntheses.py` stay in `engine/` (the store's document model, 14 importers; they move with a later `store/` package).

**Tech Stack:** Python 3.11 for `bin/` and everything it imports (ADR 0033), 3.12 engine; Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** [refactor plan](2026-11-23-memory-refactor.md) task "`bin/` holds launchers only" (the `mem-synthesize` half; `bin/` through `uv` is a later plan); review A4 ([project review](../../studies/2026-11-24-project-review.md)); [corroborate split](2026-11-26-memory-corroborate-split.md) is the precedent; owner rulings 2026-11-26: A4 first, as a package pilot; code grouped by feature (memory `m:organize-source-folders-by-feature-or-component-what`). [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md), [ADR 0033](../../adr/0033-memory-bin-scripts-need-python-3-11.md).

## Global Constraints

- Behavior unchanged: same command line, `--help` text, output, exit codes, files, log lines, commits for `mem-synthesize`, `mem-auto`, `mem-settle`, `mem`.
- Moves are verbatim (function names kept, underscores included). Named non-verbatim changes only: `_syntheses()`'s `importlib.import_module` becomes a top-level `import syntheses` (yaml already loads at base through `synth_pipeline`/`backfill`; `test_import_graph.py` bans dynamic imports in the engine); the script's `sys.path.insert` stays in the launcher only; `_parser` takes the description from `main(description)`, which the launcher passes its own `__doc__`.
- Imports: absolute and package-qualified (`from synthesize import run`, `from synthesize import references as bf`), calls through the module attribute (`run.history_commit(...)`, `backfill.backfill_one(...)`), never `from synthesize.x import _name` (patch reach; Ruff PLC2701). The engine root stays on `sys.path` as today (script folder for `mem.py`, launchers, `tests/conftest.py`).
- `ruff.toml` `[per-file-target-version]`: `plugins/memory/engine/synthesize/*` at `py311`; `test_bin_python_floor.py` reaches the package through the launcher's imports (it follows `from synthesize import x`; extend `_closure` if it does not).
- Patches retargeted in the same commit as their move, each proven by removing it in a scratch copy and seeing its test fail: `ms.backfill_one` (test_synthesize_references) → `synthesize.backfill`; `ms.history_commit` (test_backfill) → `synthesize.run`; `ms.bf.select` → `synthesize.references`; every `monkeypatch.setattr(sp, …)`/`bf` patch on the moved engine modules → their new module.
- Kept names for callers: `evals/synthesis/run_trials.py` keeps `load_synthesize()` (now returning `synthesize.topics`, which carries `ReferenceOptions` at runtime).
- An import rule in `test_import_graph.py`: store modules (`records`, `syntheses`, `project_syntheses`, `store_git`, `index`, `notes`, `check`) never import `synthesize`.
- Clean (ADR 0031) on every touched file: `uvx ruff@0.17.6 check --no-fix`, `uvx ruff@0.17.6 format --check`, `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings`; no noqa, no `type: ignore`, no config edits beyond the py311 line.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2,649 passed, 5 skipped at base) on default Python and `--python 3.12.0`; `--self-check` of `mem-synthesize`, `mem-auto`, `mem-settle` on 3.11.15 and default.
- No CHANGELOG line (pure refactor). Commits pass every hook; no `SKIP`.

## Review Focus

1. Engine load failure: today `mem-auto`/`mem-settle` load the script unguarded at start, so a broken engine (e.g. no `yaml`) exits 1 with a traceback before argparse and writes no `status.json` or log; after the move the same (pinned with a stub `yaml` that raises: exit code, empty stdout, no state files; not the traceback text).
2. A patch on a moved name that no longer reaches its code.
3. `bin/mem-synthesize` run from another directory or through a symlink finds `engine/`.
4. `--help` of `mem-synthesize`, `mem-auto`, `mem-settle` byte-identical.
5. `synth_pipeline.BRIEFS` (a path beside the module) still finds the briefs after the folder move; `mem` commands that read the briefs unchanged.

---

### Task 1: Inventory and goldens

- [x] List every importer, loader and patch of `bin/mem-synthesize`, `synth_pipeline`, `backfill` and `synth_briefs` (engine, bin, evals, hooks, tests); record each file's lint counts; clean an unclean one in its own commit. Known extra touches: `ruff.toml`, `test_bin_python_floor.py` (its `"mem-synthesize" in _closure(mem-settle)` edge becomes `synthesize/run.py`), `test_import_graph.py`, `test_auto_curation.py`, `test_run_trials_harness.py`. Write the list under this task.
- [x] `engine/tests/test_synthesize_cli_golden.py`: literal `--help` of the three scripts, a bad-argument call, topic and backfill dry runs on a fixture store, and Review Focus 1 with a stub `yaml`. Pass at base. Commit `test(memory): golden behavior of the synthesis command lines`.

**Inventory (2026-11-26, base b991a19).** Paths under `plugins/memory/`. Lint = Ruff findings / format / basedpyright errors; all `0/ok/0` unless noted. `sp` = `synth_pipeline`, `bf` = `backfill`, `ms` = the loaded `mem-synthesize`.

| File | Uses | Lint |
|---|---|---|
| `bin/mem-synthesize` | `import synth_pipeline as sp` (L44), `import backfill as bf` (L41); the code to move | 0/ok/0 |
| `bin/mem-auto` | `import synth_pipeline as sp`; `SourceFileLoader("mem_synthesize", HERE/"mem-synthesize")` as `ms` (`ms.state_dir`, `session_env`, `history_commit`, `topics_without_synthesis`, `run`, `default_store`) | 0/ok/0 |
| `bin/mem-settle` | same as `mem-auto` (`ms.state_dir`, `session_env`, `default_store`; `sp.mem/brief/parse/MEM/NO_COST`) | 0/ok/0 |
| `bin/mem-capture` | `importlib.import_module("synth_pipeline")` at module level, guarded by `IMPORT_ERROR` (keep the guard: a broken engine must not fail `mem-capture` hard) | 0/ok/0 |
| `engine/backfill.py` | `import synth_pipeline as sp`; moves whole | 0/ok/0 |
| `engine/synth_pipeline.py` | `BRIEFS = parent / "synth_briefs"` (L32); comment naming `synth_briefs/` (L190); moves whole | 0/ok/0 |
| `engine/research_pipeline.py`, `engine/corroborate_run.py` | `import synth_pipeline as sp`; `research_pipeline` also reads `sp.BRIEFS` (its own brief files live in `synth_briefs/`) | 0/ok/0 |
| `engine/safe_io.py`, `engine/tests/test_shortcheck.py` | prose mentions only (no import) | not touched |
| `engine/tests/test_backfill.py` | `import backfill as bf`, `import synth_pipeline as sp`; fixture `ms` = `SourceFileLoader` of the script (`ms.*`, 20 uses); `setattr(bf, "save_done")` L346; argv `"mem-synthesize"` L331 | 0/ok/0 |
| `engine/tests/test_synthesize_references.py` | `sp`; `ms` fixture from `test_backfill`; `setattr(sp, "run_session"/"lean_loop")` L81-82, `setattr(ms.bf, "select")` L187, `setattr(ms, "backfill_one")` L226, L238 | 0/ok/0 |
| `engine/tests/test_synth_pipeline_refs.py` | `sp`; `setattr(sp, "mem"/"run_session"/"brief")` L54, L194, L278 | 0/ok/0 |
| `engine/tests/test_synth_session.py` | `sp`; `setattr(sp.subprocess, "run")` L21 | 0/ok/0 |
| `engine/tests/test_auto_curation.py` | `import synth_pipeline as sp`; `setattr(sp, "run_session")` L476 (the `mod` patches hit `mem-auto` names: unchanged) | 0/ok/0 |
| `engine/tests/test_headless_golden.py` | `import backfill`, `import synth_pipeline`; `load_bin("mem-synthesize")` (SourceFileLoader) -> `mem_synthesize.session_env` | 0/ok/0 |
| `engine/tests/test_jobs_golden.py` | `load_bin("mem-synthesize")` -> `mem_synthesize.state_dir` (also loads `mem-auto`, `mem-settle`) | 0/ok/0 |
| `engine/tests/test_store_precedence.py` | `BIN = bin/mem-synthesize`, `SourceFileLoader("mem_synthesize_precedence")` -> `default_store` | 0/ok/0 |
| `engine/tests/test_mem_synthesize_self_check.py` | runs `bin/mem-synthesize --self-check` as a subprocess | 0/ok/0 |
| `engine/tests/test_bin_python_floor.py` | `"mem-synthesize" in _closure(mem-settle)` L101; comment on the SourceFileLoader edge L51 | 0/ok/0 |
| `engine/tests/test_run_trials_harness.py` | loads `evals/synthesis/run_trials.py`; `harness.load_synthesize()` (`ReferenceOptions`, `add_references`) | 0/ok/0 |
| `engine/tests/test_import_graph.py` | gets the new store-never-imports-synthesize rule (Task 4) | 0/ok/0 |
| `evals/synthesis/run_trials.py` | `import synth_pipeline as sp`, two `from synth_pipeline import (...)`; `load_synthesize()` `SourceFileLoader` of `bin/mem-synthesize` (L571-573); runs the script as a subprocess (L1962) | 0/ok/0 |
| `evals/synthesis/audit_refs.py` | `import synth_pipeline as sp` | 0/ok/0 |
| `evals/research/run_trial.py` | `import synth_pipeline as sp  # noqa: E402` | **37 / format diff / 2** |
| `evals/settle/run_trial.py` | `import synth_pipeline as sp  # noqa: E402`; runs `bin/mem-settle` | **21 / format diff / 1** |
| Not code: `ruff.toml` (py311 line), `skills/memory-synthesis/SKILL.md`, `skills/memory-curation/SKILL.md`, `evals/synthesis/frozen-main/README.md`, `README.md`, `CHANGELOG.md` | prose or config | n/a |

No `hooks/` file imports them (`session-end.sh` launches `bin/mem-auto`/`mem-settle`); no string path to `synth_briefs` outside `synth_pipeline.py`.

**Unclean files (ADR 0031), not cleaned in Task 1:** the two eval harnesses above. Findings: shebang not executable, unsorted imports, unused `noqa`, magic values, too-many-arguments, `complex-structure` (`grade` 14, `trial` 9, `final_verdict` 9), too-many-locals/statements (`main` 69 > 50), `subprocess.run` without `check`; plus a format diff and pyright `log_message` override / `splitlines` on `None`. Clearing them needs function splits, not mechanical edits. Task 2 touches both (the `sp` import), so they need a ruling first.

**Goldens:** `engine/tests/test_synthesize_cli_golden.py` (9 cases; passes on 3.12.0, 3.13, 3.14 and default; run with `NO_COLOR=1`, `COLUMNS=80`).

### Task 2: Move the engine modules into the package

- [ ] `git mv` `synth_pipeline.py` → `synthesize/pipeline.py`, `backfill.py` → `synthesize/references.py`, `synth_briefs/` → `synthesize/briefs/`; every importer and patch retargeted; `BRIEFS` path follows. Suite, goldens, self-checks pass. Commit `refactor(memory): synthesis pipeline and reference backfill in engine/synthesize/`.

### Task 3: Split `bin/mem-synthesize` into the package

- [ ] 3a `synthesize/run.py`, `backfill.py`, `topics.py`, `cli.py` by verbatim moves plus the named changes; the launcher is the docstring, `sys.path` setup and `sys.exit(cli.main(__doc__))`; py311 line. Commit `refactor(memory): mem-synthesize logic in engine/synthesize/`.
- [ ] 3b `mem-auto` and `mem-settle` import `synthesize.run`/`synthesize.topics` and drop the `SourceFileLoader` block. Commit.
- [ ] 3c Tests and `run_trials.py` import the package instead of loading the script; the `ms` fixture of `test_backfill.py` becomes module imports; patches retargeted and each proven. One commit per batch.

### Task 4: Boundary rule and test placement

- [ ] The store-never-imports-synthesize rule in `test_import_graph.py`, proven by a temporary violating import. Move the synthesis tests into `engine/tests/synthesize/` (names stay unique; `tests/conftest.py` still applies). Commit each.

### Task 5: Gate and docs

- [ ] Full suite on 3.12.0, 3.13.5, 3.14.4, default; self-checks on 3.11.15 and default; `pre-commit run --from-ref dev --to-ref HEAD`; `python3 scripts/validate.py`; `claude plugin validate .`. Refactor plan progress line; backlog A4 row plus a new row "engine into feature packages" (the rest, after this pilot); config plan's split-review bullet; this plan's Status and deferred findings; resume state.

## Deferred findings

| Finding | Ruling |
|---|---|
| Task 1 review: the dry-run goldens build their fixture with `mem.py`, so they run on 3.12+ only; the `--help`, bad-argument and broken-engine goldens run on 3.11 too | Accepted: the 3.11 floor is covered by the self-checks |
| Pre-mortem: `bin/` scripts already need PyYAML at import time through `synth_pipeline`/`backfill` → `syntheses`; the lazy `_syntheses()` did nothing | Recorded; the import becomes top-level (Global Constraints) |

## Kill criteria

- A golden would have to change, or `--help` of any of the three scripts differs.
- `synthesize.backfill` needs anything from `synthesize.topics`, or any other cycle.
- `test_import_graph.py` or `test_bin_python_floor.py` needs an assertion change beyond the ones named in Task 1.
- Removing a retargeted patch does not fail its test.
- A self-check result differs from base.
- A module over 550 lines after formatting: split it (`_TopicRun` off `topics`) before going on.
- A diff touches a file not on Task 1's list: clean it first.
