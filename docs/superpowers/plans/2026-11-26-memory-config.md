# Memory store resolution in one place (A1): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

Status: implemented, merged to dev 2026-11-26 (PR #199); § Deferred findings stays open · Branch: `refactor/memory-config` (stacked on `refactor/memory-a7-a1-a3`, PR #198) · Base: `6046218` · Date: 2026-11-26

**Goal:** one pure module, `engine/config.py`, decides where the note store and the config files are, every Python entry point and every hook uses it, and the two owner rulings of 2026-11-26 hold everywhere.

**Architecture:** four Python copies resolve the store today (`mem.py` `store_source`/`resolve_root`, `records.py` `default_store`/`global_memories_root`, `research_pipeline.py` `default_store`, `bin/mem-synthesize` `default_store`, which `bin/mem-settle` and `bin/mem-auto` reuse as `ms.default_store`), plus four shell copies in hooks. Task 1 pins every entry point's current answer in a table test. Tasks 2–5 make the files the change will touch clean under ADR 0031, with behavior unchanged. Task 6 adds `config.py`, points every Python copy at it and flips the table rows the rulings change. Task 7 does the same for the hooks with one sourced shell file.

**Tech Stack:** Python 3.12, Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist, bash hooks, pre-commit.

**Spec:** step 2 of [the structure study](../../studies/2026-11-23-memory-plugin-structure.md) and the "Config" task of [the refactor plan](2026-11-23-memory-refactor.md); [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md). Owner rulings 2026-11-26: (1) every entry point resolves the store as `--root`/`--store` > `MEM_STORE` > config file (`<XDG_CONFIG_HOME or ~/.config>/agent-memory/store`) > default store; (2) the default store (`<XDG_DATA_HOME or ~/.local/share>/agent-memory/store`) counts only when it holds `mem-store.yaml`; (3) lint cleanup only for the files a change touches.

## Out of scope, with reasons

- The data and state folder (`data_dir`, `MEM_DATA`, `XDG_STATE_HOME`; copies in `mem.py`, `bin/mem-capture`, `bin/mem-corroborate`, `bin/mem-synthesize`): it is part of the job lifecycle that A3's `jobs.py` takes, and two of its copies sit in `bin/mem-corroborate`, which needs A4's launcher split before it can be cleaned.
- Plugin options read as `CLAUDE_PLUGIN_OPTION_*` in Python (`AUTO_CAPTURE`, `AUTO_CURATION`, `AUTO_REWORD`…) and the `--claude` default: A2 and A3 own the launchers that read them.
- `bin/mem-capture` and `bin/mem-corroborate` are not edited: they reach the store through `records.global_memories_root`, which Task 6 changes.

## Measured start (2026-11-26, pinned tools)

| File | Lines | Ruff | basedpyright |
|---|---|---|---|
| `engine/records.py` | 1,350 | 40 | 5 |
| `engine/research_pipeline.py` | 586 | 28 | 7 |
| `bin/mem-synthesize` | 564 | 56 | 5 |
| `engine/mem.py` | 10,532 | 0 | 0 |

Suite at base: 2,288 passed, 5 skipped.

## Global Constraints

- Tasks 1–5 change no behavior: same return values, output, exit codes and files written. No change to an existing test's assertions. A failing test means the step changed behavior: revert it and take a smaller one. Task 6 changes exactly the behavior the two rulings name, and nothing else.
- Clean means: `uvx ruff@0.17.6 check --no-fix <files>` and `uvx ruff@0.17.6 format --check <files>` report nothing, and `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings <files>` reports 0 errors and 0 warnings. Plain `ruff check` applies fixes (`fix = true`). An extensionless `bin/` script is checked by passing its path.
- No `# noqa`, `# ruff: ignore`, `# type: ignore`, `# pyright: ignore`; no edit to `ruff.toml`, `pyrightconfig.json` or `.pre-commit-config.yaml` (ADR 0031).
- Touch only the files a task lists; another Python file stops the task. Never touch `bin/mem-corroborate` or `bin/mem-capture`.
- Names other modules use stay importable under the same name with the same return value: `records.default_store`, `records.memories_root`, `records.global_memories_root`, `mem.store_source`, `mem.resolve_root`, `mem.NO_STORE`, `research_pipeline.default_store`, and every top-level name of `bin/mem-synthesize` (`bin/mem-settle` and `bin/mem-auto` load it as a module, `ms`, and call `ms.default_store` and others). Before renaming any top-level name in a task, `grep -rn` it across `plugins/memory`.
- `engine/config.py` imports no engine module and reads no `os.environ`: every function takes `env: Mapping[str, str]`. One exception, kept for behavior: a `~` in a configured path is expanded with `Path.expanduser()` as `mem.resolve_root` does today (it reads the process `HOME`; `test_store.py` relies on it). `test_import_graph.py` must keep passing.
- Controller ruling, 2026-11-26: with no `HOME` and no `XDG_DATA_HOME` in the environment, every entry point finds no default store, as `mem` does today; `research_pipeline` and `bin/mem-synthesize` lose their `Path.home()` (passwd) fallback. Reason: the owner ruled one resolution for every entry point; only an environment without `HOME` sees it.
- After any signature change, also run basedpyright on every file that calls the changed function (e.g. `mem.py` calls `records.write_memory`); a `total=False` options `TypedDict` marks required keys with `Required[]`.
- Recipes (as in [the A7 plan](2026-11-26-memory-import-direction.md)): `BLE001`/`S110` keep the broad handler and log `logger.debug("<what failed>", exc_info=True)`; `PLW0717` extract the whole try body into a helper; `TRY004` a `ValueError` subclass with the same message; `PLW1510` explicit `check=False`; `RUF001` `\uXXXX` escapes with the character's name in a comment; `PLR0913`/`PLR0917` `**options: Unpack[<Name>Options]` (`total=False`, defaults applied inside) so no call site changes; structural findings: private helpers along real seams, named for what they do; never `import x as x` (PLC0414), re-export with `__all__`.
- Commits: `refactor(memory): …`, one per task; a format-and-small-rules task whose structural findings the next task owns commits with `SKIP=ruff-check,basedpyright git commit …` (never `--no-verify`); every other task with all hooks on.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto`.

## Review Focus

1. Precedence rows the rulings do not name must not move: `--root` over everything, an empty `MEM_STORE` treated as unset, a config file whose first line is empty (mem.py reads the first line only; `records.memories_root` reads the first non-empty line of the memories file: each keeps its rule), `~` expansion, no `HOME` and no `XDG_*`.
2. `mem init` must still create the default store where it did (`records.default_store` keeps returning the path, marker or not).
3. A default folder without the marker: after Task 6 `mem` says `NO_STORE` instead of using it, and `records.global_memories_root` no longer reads memories from it.
4. Hooks: an option set, an option cleared (the config file is removed), no option with and without a marked default store; `session-env.sh`'s `mem init` bootstrap and its 4 s bound keep working.
5. `bin/mem-synthesize` is loaded as a module by `mem-settle` and `mem-auto`: a renamed or re-signatured top-level name breaks them at runtime, not at lint time.

---

### Task 1: Precedence table test, current behavior

**Files:**
- Create: `plugins/memory/engine/tests/test_store_precedence.py`

**Interfaces:**
- Produces: `CASES`, a list of `(case_id, setup, expected)` rows and one parametrized test per entry point: `mem.store_source` and `mem.resolve_root` (with and without a `--root`), `records.global_memories_root`, `research_pipeline.default_store`, and `default_store` of `bin/mem-synthesize` loaded the way the existing tests load bin scripts (find that pattern with `grep -rn "spec_from_file_location\|SourceFileLoader" plugins/memory/engine/tests`). Cases cover: `--root` only; `MEM_STORE` set and set to `""`; config file only; config file whose first line is blank; default store with marker; default folder without marker; nothing; `MEM_STORE` with `~`; no `HOME` and no `XDG_*`. Each row records today's answer, including where entry points disagree. Rows without `HOME` set `HOME` to `""` in the environment and `monkeypatch.setattr(Path, "home", …)` to a `tmp_path` folder, so no row depends on the machine.

- [x] **Step 1:** Write the test with today's answers (build each case in `tmp_path`, set the environment with `monkeypatch`; the functions that read `os.environ` get it through `monkeypatch.setenv`/`delenv`).
- [x] **Step 2:** Run it. Expected: PASS on the base code. Mark in a comment beside each row that Task 6 will flip, with its reason: ruling 1 (config file honoured: `research_pipeline`, `mem-synthesize`, `records.global_memories_root`), ruling 2 (unmarked default folder: `mem.store_source`/`resolve_root`; not `global_memories_root`, whose `memories_root` already ignores an unmarked store), or the HOME-less ruling of Global Constraints.
- [x] **Step 2b:** List every other test that builds a default store folder without `mem-store.yaml` and expects it used: `grep -rn "agent-memory" plugins/memory/engine/tests | grep -v mem-store.yaml` and read the hits; known one: `test_store.py` `test_default_store_is_the_last_resort_and_only_when_it_exists`. Name them in the commit message; Task 6 updates exactly those.
- [x] **Step 3:** Gate: the file is clean; full suite passes. Commit.

### Task 2: `records.py` format and small rules

**Files:** Modify: `plugins/memory/engine/records.py`

- [x] **Step 1:** `uvx ruff@0.17.6 format` and safe fixes; run the suite.
- [x] **Step 2:** Fix every non-structural Ruff finding and every basedpyright error with the recipes; run the suite.
- [x] **Step 3:** Gate: only structural findings left; suite passes. Commit with `SKIP=ruff-check,basedpyright`.

### Task 3: `records.py` structural findings, file clean

**Files:** Modify: `plugins/memory/engine/records.py`

- [x] **Step 1:** Decompose each function with a structural finding, running the suite after each.
- [x] **Step 2:** Gate: `records.py` clean; suite passes. Commit, all hooks on.

### Task 4: `research_pipeline.py` clean

**Files:** Modify: `plugins/memory/engine/research_pipeline.py`

- [x] **Step 1:** Format, small rules, types, then structural findings, running `pytest plugins/memory/engine/tests -q -k "research or fetch or synth"` after each function and the suite at the end.
- [x] **Step 2:** Gate: file clean; suite passes. Commit, all hooks on.

### Task 5: `bin/mem-synthesize` clean

**Files:** Modify: `plugins/memory/bin/mem-synthesize`

- [x] **Step 1:** List its top-level names used elsewhere: `grep -rn "ms\.\|mem_synthesize\|mem-synthesize" plugins/memory`. None of them changes name or signature.
- [x] **Step 2:** Format, small rules, types, then structural findings; run `plugins/memory/bin/mem-synthesize --help`, `plugins/memory/bin/mem-settle --help`, `plugins/memory/bin/mem-auto --help` and any `--self-check` the scripts offer, plus the suite.
- [x] **Step 3:** Gate: file clean; the commands above behave as before; suite passes. Commit, all hooks on.

### Task 5b: `evals/synthesis/run_trials.py` clean (owner ruling 2026-11-26)

Task 5 moved `add_references` past its fifth parameter to `**options`; the synthesis trial harness called it with eight positionals (`run_trials.py`, `reference_backfill`), and no test covered that path. Owner, 2026-11-26: fix the call and make the whole file clean (ADR 0031, no exception).

**Files:** Modify: `plugins/memory/evals/synthesis/run_trials.py`; `plugins/memory/bin/mem-synthesize` (review fixes: `encoding="utf-8"` on every remaining text read and write; `_unit_text` builds its part index once per call)

- [x] **Step 1:** The `add_references` call passes `settings`, `log` and the budget by keyword; a smoke check imports the harness and calls `reference_backfill` with `add_references` stubbed, asserting the keywords it receives.
- [x] **Step 2:** Format, small rules, types, structural findings (2,162 lines, 226 Ruff, 41 basedpyright at start), across several dispatches that hand over an uncommitted tree; one commit at the end with all hooks on.
- [x] **Step 3:** Gate: file clean; `python3 plugins/memory/evals/synthesis/run_trials.py --help` (or its documented dry entry) runs; suite passes.

### Task 6: `config.py`, every Python copy points at it, rulings applied

**Files:**
- Create: `plugins/memory/engine/config.py`, `plugins/memory/engine/tests/test_config.py`
- Modify: `engine/mem.py`, `engine/records.py`, `engine/research_pipeline.py`, `bin/mem-synthesize`, `engine/tests/test_store_precedence.py` (flipped rows only), `engine/tests/test_store.py` (the unmarked-default assertion and the tests Task 1 step 2b named, only), `plugins/memory/CHANGELOG.md`, `plugins/memory/README.md` (the "Store (notes)" row)

**Interfaces:**
- Produces, in `config.py` (pure; docstring states the precedence and the two rulings with their date):
  - `config_dir(env: Mapping[str, str]) -> Path | None`: `<XDG_CONFIG_HOME>/agent-memory`, else `<HOME>/.config/agent-memory`, else None.
  - `config_lines(env: Mapping[str, str], name: str) -> list[str]`: the lines of `config_dir/name`, `[]` when missing or unreadable.
  - `default_store_path(env: Mapping[str, str]) -> Path | None`: `<XDG_DATA_HOME>/agent-memory/store`, else `<HOME>/.local/share/agent-memory/store`, else None (no existence check).
  - `default_store(env: Mapping[str, str]) -> Path | None`: `default_store_path` when it holds `mem-store.yaml` (`STORE_MARKER = "mem-store.yaml"`).
  - `store_source(arg: str | None, env: Mapping[str, str]) -> Literal["--root", "MEM_STORE", "config file", "default"] | None` and `resolve_store(arg: str | None, env: Mapping[str, str]) -> Path | None`, the ruled precedence; the config file is its first line, stripped, as `mem.py` reads it today; `~` expanded as today.
- `mem.store_source`, `mem.resolve_root`, `records.default_store` (returns `config.default_store_path`, for `mem init`), `records.global_memories_root` (store from `config.resolve_store(None, env)`), `research_pipeline.default_store()` and `bin/mem-synthesize`'s `default_store()` (both `config.resolve_store(None, os.environ)`) become thin delegates; `records.memories_root` reads its file through `config.config_lines`; `records.forbidden_file` builds on `config.config_dir`; `records.global_memories_root` keeps its `is_dir()` guard. `mem.NO_STORE` keeps its text, and when the default folder exists without `mem-store.yaml` `mem` adds one line after it: `mem: <folder> has no mem-store.yaml, so it is not used; add the file by hand only if you own that folder and mean to write to it.` (test it). Remove the copies they replace (`mem._config_file`, `mem._config_store`, `mem._default_store`, `records._config_base`) after grepping that nothing else uses them.

- [x] **Step 1:** Write `test_config.py` for each `config` function (the cases of Task 1 plus marker present/absent). Run: FAIL (no module).
- [x] **Step 2:** Write `config.py`; run `test_config.py`. Expected: PASS.
- [x] **Step 3:** Point the copies at it. Run `test_store_precedence.py`: exactly the rows marked in Task 1 fail. Update those rows, and the `test_store.py` assertions Task 1 step 2b named, to the ruled answers, nothing else; run the suite.
- [x] **Step 4:** `CHANGELOG.md` under `## [Unreleased]`, `### Changed`, written for users: background commands and `mem-research`/`mem-synthesize` now use the store named in the config file when `MEM_STORE` is unset, as `mem` does; the default store counts only with its `mem-store.yaml` marker (an unmarked folder there is no longer used; `mem` says how to adopt it); with no `HOME` and no `XDG_DATA_HOME`, no entry point uses a default store; `signal.sh` (parked) now falls back to the default store like the other hooks (from Task 7). README "Store (notes)" row: state the precedence in one line.
- [x] **Step 5:** Gate: every touched Python file clean; `test_import_graph.py` passes; suite passes. Commit, all hooks on.

### Task 7: Hooks source one store file

**Files:**
- Create: `plugins/memory/hooks/store-env.sh`
- Modify: `hooks/session-env.sh`, `hooks/session-index.sh`, `hooks/post-compact.sh`, `hooks/session-end.sh`, `hooks/signal.sh`; a hook test in `engine/tests/` if none covers the cases of Review Focus 4 (find the existing hook tests with `grep -rln "session-index.sh\|session-env.sh" plugins/memory/engine/tests`)

**Interfaces:**
- `store-env.sh`, sourced like `find-claude.sh`, defines `default_store_dir` (echoes the default store folder when it holds `mem-store.yaml`, else nothing) and `export_store_env` (exports `MEM_STORE` from `CLAUDE_PLUGIN_OPTION_STORE`, else from `default_store_dir`; exports `MEM_MEMORIES` from `CLAUDE_PLUGIN_OPTION_MEMORIES`). The four hooks that duplicate the snippet call `export_store_env`; `session-env.sh` uses `default_store_dir` in its `default_store` bootstrap and its settle block. Each hook computes `$here` before the store lines and calls it as `. "$here/store-env.sh" 2>/dev/null; type export_store_env >/dev/null 2>&1 && export_store_env`, so a missing file prints nothing (hook tests assert empty stderr, `test_plugin_shell.py`) and the hook still exits 0.

- [x] **Step 1:** Write or extend the hook test for the cases of Review Focus 4; run it on the current hooks: PASS.
- [x] **Step 2:** Create `store-env.sh` and switch the hooks; run the hook test and the suite.
- [x] **Step 3:** `bash -n` every changed hook; `claude plugin validate plugins/memory`. Commit.

### Task 8: Docs

**Files:** Modify: `docs/superpowers/plans/2026-11-23-memory-refactor.md` (Config task), `docs/backlog.md` (A1 row, dates), `docs/studies/2026-11-23-memory-plugin-structure.md` (finding 2: the `MEM_RULES_LAYOUT` harm it names is already fixed, `conftest.py` clears every `MEM_*` and `CLAUDE_PLUGIN_OPTION_*`), this plan's Status line

- [x] **Step 1:** Config task ticked with a link to this plan and what stays for A3 (data folder); backlog A1 row closed the way A7's was; study note; Status. `python3 scripts/validate.py`. Commit.

### Task 9: Config files editable by hand (owner ruling 2026-11-26)

Owner, 2026-11-26, after the final review: the `store` config file is user-editable, not hook-managed. Until now `session-env.sh` wrote `$cfg/store` and `$cfg/memories` from the options and deleted them whenever an option was empty, and every hook exported the default store as `MEM_STORE`, so a hand-written file never worked inside sessions.

**Files:** Modify: `plugins/memory/hooks/session-env.sh`, `plugins/memory/hooks/store-env.sh`, `plugins/memory/engine/tests/test_hooks_store_env.py`, `plugins/memory/CHANGELOG.md`, `plugins/memory/README.md` (the sentence on where options are written)

**Interfaces:**
- `session-env.sh` `handle` records what it writes: next to `$cfg/<name>` a file `$cfg/<name>.hook` holding the exact value written. Option set: write `$cfg/<name>` and the record only when `$cfg/<name>` is missing or its content equals the record (hook-owned); a file that differs (written or edited by hand) is kept; the option is exported either way. Option empty: remove `$cfg/<name>` only when its content equals the record; always remove the record. Applies to `store` and `memories` alike.
- `store-env.sh` gains `config_store` (prints the first line of `${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory/store`, stripped, or nothing). `export_store_env` and `session-env.sh`'s `default_store` export the default store only when no option is set AND `config_store` prints nothing; when the config file names a store, the hooks export that value as `MEM_STORE` (config file > default; changed after the Task 9 review so `session-end.sh`'s `MEM_STORE` gate still starts auto curation and settle).
- Hooks stay silent and exit 0 in every case.

- [x] **Step 1:** Tests first (fail on the current hooks): hand-written `store` file with the option empty survives a session start and no `MEM_STORE` is exported (session-env and the printing hooks); a hook-written file is still removed when the option is cleared; the option set with a different hand-written file keeps the file and exports the option; the option set with no file writes file and record; same for `memories`; a config file plus a marked default store: no `MEM_STORE` exported.
- [x] **Step 2:** Implement; run the hook tests and the suite; `bash -n`; `claude plugin validate plugins/memory`.
- [x] **Step 3:** CHANGELOG (`### Changed`, for users): the config files under `~/.config/agent-memory/` can be edited by hand; the hooks no longer delete or overwrite a file they did not write, and no longer export the default store when the `store` file names one. Migration: a file written by an older version has no record, so after clearing the `store` option remove `~/.config/agent-memory/store` by hand if it still names the old store. README: replace the sentence added in `81e5399` accordingly. Commit, all hooks on.

## Deferred findings

- `**options` keys are type-checked only: an unknown key passed to `records.write_memory`, `add_sighting`, `match_memories`, `research_pipeline` steps or `mem-synthesize`'s `run`/`run_backfill` is ignored at runtime (PEP 692 trade-off; callers are type-checked).
- `bin/mem-synthesize --self-check` fails on its last assertion (`mem history commit` makes no "after one, two" commit); it fails the same at `65e901a`, before this plan. Fixed in the [fixes plan](2026-11-26-memory-fixes.md): the self-check's fake wrote an empty note that the commit gate rightly held back.
- Split reviews due (owner rule: code files over 1,000 lines): `bin/mem-synthesize` grew 564 → 1,339 lines (about 400 from formatting, 24 → 81 functions) and belongs to A4 (logic into the engine; done: [synthesize split](2026-11-26-memory-synthesize-split.md), modules of 152 to 528 lines); `evals/synthesis/run_trials.py` grew 2,162 → 4,345 lines.
- No CHANGELOG line for `signal.sh`: `mem` already resolved the default store itself, so its new export changes nothing a user sees (dropped after the Task 7 review). Inside sessions the hooks own the config file (written from the `store` option, removed when it is cleared), so the default store exported by the hooks never competes with it; ruling 1 matters for commands run by hand.
- Shell `config_store` reads a CR-only line end differently from `config.py`'s `splitlines` (low).
- Low review notes: `records._parse` special-cases `FieldTypeError`'s name to keep stored error text; formatter-placed comments inside `Memory` fields; `research_pipeline.budget_of` raises `TypeError` for a non-string (argparse never passes one); `run_trials.one_row` raises `ValueError` before the budget call when arm M has no control; single-use helpers in `mem-synthesize`; `mem --root` help omits the default store (pre-existing).

## Kill criteria

- A task needs `bin/mem-corroborate`, `bin/mem-capture` or another unlisted Python file: stop and report.
- Task 6 step 3 fails rows not marked in Task 1: a behavior the rulings do not name changed; revert and report.
- Task 3 or 5 cannot clear a structural finding without renaming a name another module uses, or without making a positional parameter of an `ms.*` function at index 5 or lower keyword-only (`bin/mem-auto` passes five positionals): stop and report.
- A Task 1 row gives different answers on two machines: fix it before Task 6.
- Any hook test sees stderr after Task 7: revert the hook switch.
