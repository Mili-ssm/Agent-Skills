# `bin/` scripts run through `uv` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned, two pre-mortems 2026-11-26 applied, owner chose the shared launcher · Branch: `refactor/memory-next` (from `dev` 9380eda) · Date: 2026-11-26

**Goal:** every script in `plugins/memory/bin/` runs through `uv` with one interpreter policy and one cached environment, `bin/` holds launchers only, and a missing `uv` is reported instead of failing silently.

**Architecture:** the six python scripts (`mem-auto` 477 lines, `mem-capture` 1,230, `mem-corroborate` 213, `mem-research` 16, `mem-settle` 549, `mem-synthesize` 28) become bash launchers like `bin/mem`: `command -v uv` or exit 127 with the `bin/mem` message, then `exec uv run --quiet --script "$ENGINE/run.py" --bin <name> "$@"`. `engine/run.py` (the only PEP 723 header, so one `uv` environment) dispatches `--bin <name>` to `<package>.cli.main(argv)` and anything else to `mem.main()` (`--bin` is never a `mem` argument; `mem settle` stays a `mem` subcommand). The python bodies are entry points like `mem.py`, not feature code: they move verbatim into a new top-level package `engine/entry/` (`auto.py`, `capture.py`, `corroborate.py`, `settle.py`; each keeps its bin file's docstring as its module docstring, because `--help` prints `__doc__`), a layer above the feature packages that may import any of them and that only `run.py` imports; `mem-research` and `mem-synthesize` dispatch straight to `research.pipeline.main` and `synthesize.cli.main` (the latter gets the bin file's docstring passed explicitly). `run.py` sets `sys.argv = [name, *rest]` before calling an entry (argparse takes `prog` from `sys.argv[0]`, so `--help` stays byte-identical and the bodies need no `argv` parameter) and imports `mem` only on the `mem` branch, with one static import per branch (`importlib` is banned in engine modules). Launch sites that prefix an interpreter (`sys.executable bin/mem-settle` in `engine/settle/state.py`, the `Popen` of `mem-corroborate` in `capture`) execute the `bin/` launcher. `hooks/session-index.sh` (the hook that prints the session-start text; `session-env.sh` is silent by design) prints one notice in its existing "mem did not answer" branch when `command -v uv` fails, so every silent failure (the background jobs and `mem` itself) is visible once.

**Tech Stack:** uv (PEP 723), Python 3.12–3.14 for the whole engine, bash launchers, Ruff 0.17.6, basedpyright 1.40.2, pytest.

**Spec:** refactor plan [2026-11-23-memory-refactor.md](2026-11-23-memory-refactor.md) targets "every `bin/` script runs through `uv`" and "`bin/` holds launchers only"; ADR 0033 § Revisit if; ADR 0034; owner ruling 2026-11-26 (shared launcher over a header per script or deferring).

## Global Constraints

- Behavior unchanged apart from the interpreter: CLI output, `--help` byte-identical, files written, exit codes, hooks' time budgets; synchronous hook paths gain no `uv` start.
- Measured by the pre-mortem: `uv` keys script environments by script path (one header per script would mean seven environments per plugin version); a cold start prints `Installed …` on stderr unless `--quiet`; a cold cache offline fails; warm start-up 0.03 s; parallel cold starts share one install.
- Verbatim moves; ADR 0031 on every touched Python file (`ruff check --no-fix` for read-only runs); tests retargeted to the engine entry points, plus launch-path tests through the real launchers.
- A new ADR supersedes 0033 (both Status lines); a CHANGELOG `[Unreleased]` line for users (no system `python3` needed; `uv` required for the background passes, as for `mem`; offline cold cache after an update fails until online).
- Commits pass every hook; no `SKIP`. PR to `dev`; merge only on the owner's word.

## Review Focus

1. `mem` arguments colliding with the dispatch (`--bin` must never reach `mem.main`; `mem settle` keeps working).
2. A launch site still prefixing `python3`/`sys.executable` before a `bin/` launcher (a bash file run by Python fails).
3. Tests that ran `sys.executable bin/<script>` silently testing nothing after the switch; `importlib`/`exec_module` loads of `bin/` files.
4. The hook environment: `uv` on a PATH the hook does not have (a user with `uv` only in `~/.local/bin`); test with a shim PATH and an empty `UV_CACHE_DIR`.
5. `__file__`-relative paths in the moved bodies: `HERE`/`MEM`/`CORROBORATE` (`bin/mem-capture`) must point at `<plugin>/bin/`; every `sys.path.insert(… engine)` is dropped; `sp.MEM` is already plugin-relative.
6. Launchers copy `bin/mem`'s `readlink` loop (symlinked installs), not a bare `dirname`.

---

### Task 1: Dispatch and the three small scripts
- [x] `engine/run.py` `--bin` table (argv rewrite, lazy `mem`); `entry/` package with its graph rules in `test_import_graph.py` (`entry` may import every feature package, only `run` imports it); `mem-research`, `mem-synthesize`, `mem-corroborate` become bash launchers, their bodies in their packages. Check: suite; a golden `--help` of all six saved before Task 1 and diffed after every task; self-checks through the launchers; `bin/mem` unchanged in behavior (`mem settle log`).

### Task 2: `mem-auto` and `mem-settle`
- [x] Bodies to `entry/auto.py` and `entry/settle.py`; launchers; tests that load the bin files with `SourceFileLoader` (`test_auto_curation.py:507`) load the entry module; `settle/state.py` executes `bin/mem-settle`. Check: as Task 1, plus the detached start path in a hook-like environment.

### Task 3: `mem-capture`
- [x] Body to `entry/capture.py` (size review after the move, split by cohesion only if needed); launcher; `MEM`/`CORROBORATE` point at `<plugin>/bin/`; the yaml import fallback and its test retire (uv provides pyyaml); `SourceFileLoader` tests (`test_mem_capture.py:124-131`, `test_capture_auto.py:643`) load the entry module; `test_capture_auto.py:335-343` runs the entry with the test Python and keeps only `bin/mem` without uv. Check: as Task 1; capture goldens.

### Task 4: Notice, tests, lint, decision record
- [x] `session-index.sh` notice when `uv` is missing (one line, through the existing session-start output); launch-path tests: each launcher under a shim PATH without `uv` exits 127 with the message, and with `uv` runs `--help` (warm cache; a cold-cache case is gated as needing the network); `test_bin_python_floor.py` replaced by a test that every `bin/` file is a bash launcher whose `--bin` name is in `run.py`'s table (prove it bites); `ruff.toml` `py311` entries removed after a `--target-version py312` spike (over ~20 findings outside `bin/`: own PR); the "3.11-safe / without uv" docstrings; ADR superseding 0033; CHANGELOG; README. Check: suite on default, 3.12.0–3.14.4; validate.py; `claude plugin validate .`; pre-commit from `origin/dev`.

## Deferred findings

| Finding | Ruling |
|---|---|
| `mem --bin X` now dispatches to a job instead of an argparse error (Task 1 review) | accepted: `mem` has no `--bin` option and nobody types it |
| `entry/capture.py` 1,201 lines holds three subcommands (offline trial, auto, sweep) sharing the apply helpers (Task 3) | kept whole: in the size band and one CLI; split into `entry/capture/` if it grows |
| The floor test's `synthesize/run.py` closure assert dropped (Task 2 review) | accepted: the 3.11 floor ends in Task 4 |

## Kill criteria

- The import-graph tables need more than the `entry` rules; a synchronous hook path gains a `uv` start; a hook-started job fails with no notice; `--help`, stdout or a golden changes; the cold launch-path test exceeds 2 s; `mem settle` or any `mem` subcommand changes behavior.
