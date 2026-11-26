# Memory engine into feature packages (backlog A14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned, pre-mortem 2026-11-26 applied · Branches: one per task, stacked (`refactor/memory-pkg-<name>`, first from `dev` ae8bae3) · Date: 2026-11-26

**Goal:** every engine module except the entry points lives in a feature package under `plugins/memory/engine/`, with tests beside it and an import rule per package; behavior unchanged ([ADR 0034](../../adr/0034-memory-engine-is-organized-in-feature-packages.md)).

**Architecture:** the `synthesize/` pilot ([plan](2026-11-26-memory-synthesize-split.md), PR #206) is the method: `git mv`, imports package-qualified (`from corroborate import state`), calls through the module attribute, `__init__.py` a docstring only, tests in `engine/tests/<package>/` without `__init__.py`. Target map (module → package/module; a module named like its package takes a role name):

| Package | Modules |
|---|---|
| `corroborate/` | `corroborate` → `decide`, `corroborate_cli` → `cli`, `_digest` → `digest`, `_fill` → `fill`, `_reword` → `reword`, `_run` → `run`, `_state` → `state` |
| `research/` | `research_checks` → `checks`, `research_pipeline` → `pipeline` |
| `capture/` | `capture` → `extract`, `capture_state` → `state` |
| `settle/` | `settle` → `verdicts`, `settle_state` → `state` |
| `digest/` | `digest` → `lessons` |
| `session/` | `handoff`, `session_notices` → `notices` |
| `core/` | `config`, `safe_io`, `headless`, `jobs`, `auto_state` (infrastructure of the background jobs; imports stdlib and `core` only) |
| `store/` | `records`, `syntheses`, `project_syntheses`, `store_git`, `index`, `notes`, `check`, `rules`, `shortcheck`, `digest_text` → `fingerprints` (both `rules` and `digest` import it; in `digest/` it would make a store↔digest cycle) |
| root | `mem.py` (entry point; A5 splits it), `run.py` (the `bin/mem` launcher) |

Order (fewest importers first; each task is one pull request on the previous branch): corroborate, research, the four small packages, core, store. `store/` goes last because `records` has 56 importers; A6 then splits `records` inside it.

**Tech Stack:** Python 3.11 for `bin/` and what it imports (ADR 0033), 3.12 engine; Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** owner rulings 2026-11-26 (feature packages; "continue with the rest of the refactors"); ADR 0034; [refactor plan](2026-11-23-memory-refactor.md); backlog A14.

## Global Constraints

- Import convention (pre-mortem): import a moved module under its old name as alias, `from capture import state as capture_state`, `from corroborate import run as corroborate_run`, so call sites and alias-based patches stay unchanged and two `state` modules never rebind one name; bare role names (`state`, `run`, `cli`, `text`, `digest`, `lessons`) are not used as import names.
- Base edges between the planned packages (AST, 2026-11-26), frozen as the only allowed cross-package edges: corroborate → capture (`capture_state`), corroborate → digest, corroborate → synthesize, research → synthesize, research → root `mem` (`mem.tokenize`; A5 removes it), digest → store, session → store; core → core only; store → core, store only. Every other package edge is new and fails its rule.

- Behavior unchanged: CLI text, output, exit codes, files, log lines; `mem session-index` output.
- Each task first measures every file it will touch with `ruff check --no-fix` (ruff.toml sets `fix = true`; a plain `check` rewrites files) and cleans the unclean ones before any move, test files in their own dispatch. Measured after safe fixes (pre-mortem): about 560 findings in the test files these moves touch (test_remember 34, test_case_log 27, test_settle 26, …), plus `project_syntheses` 10, `safe_io` 9, `store_git` 8, `index` 5, `session_notices` 4, `shortcheck` 1, `evals/rules_layout/run_trial.py` 16, `evals/signal/score.py` 1, `bin/mem-research` (format, RUF100). Known at plan base: `corroborate.py` 20 Ruff + unformatted + 7 basedpyright; `capture.py` 17 + unformatted + 4; `check.py` 35 + unformatted + 3; `syntheses.py` 46 + unformatted + 13. Over ~40 findings: own dispatch.
- Moves keep content except import lines and `__file__`-relative paths: grep `__file__` in every moved module and moved test (`.parent.parent` too, not only `parents[`); known: `corroborate_run.py` `MEM` (`.parent.parent/"bin"/"mem"`), `settle_state.py` `parents[1]`.
- String references, retargeted by name in their task and each given a positive control (the blocked or patched name is really used when not blocked): `bin/mem-capture` `importlib.import_module("capture")` (a stale name would import the empty package without error), `test_capture_state.py` `sys.modules['capture']` block, `test_import_graph.py` hardcoded names and `STORE_MODULES`, `mem.py`/`corroborate_digest.py` `import digest`.
- Evals are importers too (`signal/score.py`, `research/run_trial.py`, `rules_layout/run_trial.py` (lazy), `synthesis/audit_refs.py`, `synthesis/run_trials.py`, `settle/run_trial.py`), and `evals/project_syntheses/run_trials.py` answer keys name `memory/engine/records.py`, `syntheses.py`, `project_syntheses.py`: retarget in the owning task; run each harness's `--self-check` or `--help`.
- `monkeypatch` targets: a module object patched through an alias keeps working; string targets (`"corroborate_run.x"`), `sys.modules` keys and `importlib.import_module("name")` strings change; every changed patch is proven by removing it in a scratch copy.
- `ruff.toml` `[per-file-target-version]` entries follow moved files (`engine/headless.py`, `engine/jobs.py` → `engine/core/...`; packages that `bin/` imports at `py311`).
- `test_import_graph.py` gets one rule per package as it lands: `core` imports only stdlib and `core`; `store` imports only stdlib, `core` and `store`; a feature package imports no other feature package except edges present at base (listed in the task's commit, then frozen). Each rule proven by a temporary violating import.
- Test placement: a test file moves into `tests/<package>/` only when it imports no other test file (pytest prepend mode puts only its own folder on `sys.path`); shared helpers that tests import from other test files (`test_find_new`, `test_rules_session`, `test_check`, `test_curation`, `test_search_stats`, `test_show`, `test_mem_capture`, `test_capture_auto`, `test_case_log`, `test_store_git`) move first into helper modules, beside the tests that use them (a helper moves with its package's tests, as `tests/corroborate/corroborate_world.py` did); basenames stay unique. Check: every moved test file passes alone.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2,663 passed, 5 skipped at base) on default Python and `--python 3.12.0`; collected count unchanged by moves; self-checks of `mem-auto`, `mem-settle`, `mem-corroborate`, `mem-synthesize`, `mem-capture` (if it has one) on 3.11.15 and default.
- No CHANGELOG line (pure refactor). Commits pass every hook; no `SKIP`.

## Review Focus

1. A string module name the grep for `import x` misses: `importlib.import_module("x")`, `monkeypatch.setattr("x.y", …)`, `sys.modules["x"]`, subprocess `python -m x`, hook scripts, `-c` snippets.
2. A `__file__`-relative path that now points one level off (templates, briefs, `bin/mem`, plugin root).
3. A test file whose basename collides with another after moving into a subfolder (pytest prepend mode).
4. `bin/` scripts on Python 3.11 reaching a moved module that is not at `py311`.
5. Hooks (`hooks/*.sh`) or docs agents follow that name a moved file path.

---

### Task 1: `corroborate/`
- [x] First commit: `test_import_graph.py` builds MODULES from every `engine/**/*.py` outside tests (dotted names, packages by `__init__.py`) and asserts its size equals the file count; `test_notes_imports_no_other_engine_module` uses the same set; the frozen edge list above becomes a test. Then clean `corroborate.py`; move the seven modules; importers, patches, `ruff.toml`, tests to `tests/corroborate/`; rule. Check: suite, goldens of `mem-corroborate` (`tests/test_corroborate_cli.py` and the self-check), collected count.

### Task 2: `research/`
- [x] Move `research_checks`, `research_pipeline`; a rule that no package except `research` (frozen, until A5) imports root `mem` or `run`; importers (`bin/mem-research`), tests to `tests/research/`; rule. Check: suite; `bin/mem-research --help` byte-identical.

### Task 3: `capture/`, `settle/`, `digest/`, `session/`
- [ ] Clean `capture.py`; one commit per package; tests beside each; rules. Check: suite; `mem session-index` output on a fixture store byte-identical (a golden first if none exists).

### Task 4: `core/`
- [ ] Move `config`, `safe_io`, `headless`, `jobs`, `auto_state`; `ruff.toml` py311 entries; the core-imports-only-core rule. Check: suite; self-checks on 3.11.15.

### Task 5: `store/`
- [ ] Clean `check.py`, `syntheses.py`; move the nine modules; the store rule (store imports only stdlib, core, store). Check: suite on 3.12.0 and default; self-checks.

### Task 6: Gate and docs
- [ ] Full matrix (3.12.0, 3.13.5, 3.14.4, default); self-checks on 3.11.15; `pre-commit run --from-ref dev --to-ref HEAD`; `validate.py`; `claude plugin validate .`. Docs: ADR 0034 `## Review` with the final layout; the memory plugin's README and resume state where they name engine files; backlog A14; this plan.

## Deferred findings

| Finding | Ruling |
|---|---|
| Cleanups grew `check.py` to 1,396 lines and `syntheses.py` to 1,313 (owner's 1,000-line split review); `corroborate.py` 891 | Split reviews with Task 5 + A6 (`store/`), where both land |
| Cleanup review: `capture._Scan` control flow (old `continue`/`break` as `return True/False`) not traced line by line; tests pass | Open, low |
| Test-cleanup review: `== ""` became `not x` (Ruff PLC1901) in test_reword, test_quarantine, test_settle (also passes on None); `INDEX_TOPICS`/literal 80 in test_digest; `EXIT_REFUSED` means 3 in one test file and 2 in others; test_fetch_sources' `mem.time` stub has no `monotonic` | Open, low: the values are strings; a stub miss fails loudly |
| `project_syntheses.write_part` takes `NewPart` (`Part` already names the parsed part) | Accepted |
| Intermittent errors in `test_capture_auto`, `test_capture_sweep`, `test_compact_log` when several suites run at once from worktrees: they share the real uv cache by design (`tests/conftest.py`), `bin/mem` runs `uv run` (inferred, not reproduced) | Open, low: only in parallel agent runs; a per-session `UV_CACHE_DIR` costs about 0.35 s per `bin/mem` launch |
| Task 1 review: `corroborate`'s allowed dependencies listed `config` and `auto_state` (not base edges); a relative import would hide an edge from every rule | Fixed: the list equals the measured imports; `test_engine_uses_no_relative_imports` (proven) |
| Task 1 review: the module-count assertion compares two sets from the same glob | Open, low: it catches name collisions, not a file the glob skips |
| Task 1 review: frozen edge `digest → store` is not a literal import at base | Rejected: base `digest.py` imports `records`, `rules`, `shortcheck`, which are `store` modules in this plan |
| Store-only lint debt (28 test files, about 304 findings) | Task 5 runs together with A6 (`records` split), which touches the same tests |

## Kill criteria

- A golden or `--help` text changes.
- A cycle between packages, or a rule that only passes by allowing a new cross-feature edge.
- A collected-test count changes across a move.
- A patch stops reaching its code.
- A file to touch is unclean and over ~60 findings in one dispatch: split the cleanup.
- A task's touched files exceed ~150 Ruff findings: the cleanup becomes its own pull request first.
- The MODULES count in `test_import_graph.py` falls after a move.
- A moved test passes only in the full run, not alone.
- An old module name still resolves (to a package `__init__`) anywhere: grep before merge.
