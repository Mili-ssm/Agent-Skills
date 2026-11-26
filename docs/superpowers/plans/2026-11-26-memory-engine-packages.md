# Memory engine into feature packages (backlog A14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: planned · Branches: one per task, stacked (`refactor/memory-pkg-<name>`, first from `dev` ae8bae3) · Date: 2026-11-26

**Goal:** every engine module except the entry points lives in a feature package under `plugins/memory/engine/`, with tests beside it and an import rule per package; behavior unchanged ([ADR 0034](../../adr/0034-memory-engine-is-organized-in-feature-packages.md)).

**Architecture:** the `synthesize/` pilot ([plan](2026-11-26-memory-synthesize-split.md), PR #206) is the method: `git mv`, imports package-qualified (`from corroborate import state`), calls through the module attribute, `__init__.py` a docstring only, tests in `engine/tests/<package>/` without `__init__.py`. Target map (module → package/module; a module named like its package takes a role name):

| Package | Modules |
|---|---|
| `corroborate/` | `corroborate` → `decide`, `corroborate_cli` → `cli`, `_digest` → `digest`, `_fill` → `fill`, `_reword` → `reword`, `_run` → `run`, `_state` → `state` |
| `research/` | `research_checks` → `checks`, `research_pipeline` → `pipeline` |
| `capture/` | `capture` → `extract`, `capture_state` → `state` |
| `settle/` | `settle` → `verdicts`, `settle_state` → `state` |
| `digest/` | `digest` → `lessons`, `digest_text` → `text` |
| `session/` | `handoff`, `session_notices` → `notices` |
| `core/` | `config`, `safe_io`, `headless`, `jobs`, `auto_state` (infrastructure of the background jobs; imports stdlib and `core` only) |
| `store/` | `records`, `syntheses`, `project_syntheses`, `store_git`, `index`, `notes`, `check`, `rules`, `shortcheck` |
| root | `mem.py` (entry point; A5 splits it), `run.py` (the `bin/mem` launcher) |

Order (fewest importers first; each task is one pull request on the previous branch): corroborate, research, the four small packages, core, store. `store/` goes last because `records` has 56 importers; A6 then splits `records` inside it.

**Tech Stack:** Python 3.11 for `bin/` and what it imports (ADR 0033), 3.12 engine; Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** owner rulings 2026-11-26 (feature packages; "continue with the rest of the refactors"); ADR 0034; [refactor plan](2026-11-23-memory-refactor.md); backlog A14.

## Global Constraints

- Behavior unchanged: CLI text, output, exit codes, files, log lines; `mem session-index` output.
- Each task first measures every file it will touch (ADR 0031: a renamed file is touched) and cleans the unclean ones, one commit each, before any move. Known at plan base: `corroborate.py` 20 Ruff + unformatted + 7 basedpyright; `capture.py` 17 + unformatted + 4; `check.py` 35 + unformatted + 3; `syntheses.py` 46 + unformatted + 13. Over ~40 findings: own dispatch.
- Moves keep content except import lines and `__file__`-relative paths (one level deeper: `parents[n+1]`); grep every `Path(__file__)` in moved modules.
- `monkeypatch` targets: a module object patched through an alias keeps working; string targets (`"corroborate_run.x"`), `sys.modules` keys and `importlib.import_module("name")` strings change; every changed patch is proven by removing it in a scratch copy.
- `ruff.toml` `[per-file-target-version]` entries follow moved files (`engine/headless.py`, `engine/jobs.py` → `engine/core/...`; packages that `bin/` imports at `py311`).
- `test_import_graph.py` gets one rule per package as it lands: `core` imports only stdlib and `core`; `store` imports only stdlib, `core` and `store`; a feature package imports no other feature package except edges present at base (listed in the task's commit, then frozen). Each rule proven by a temporary violating import.
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
- [ ] Clean `corroborate.py`; move the seven modules; importers, patches, `ruff.toml`, tests to `tests/corroborate/`; rule. Check: suite, goldens of `mem-corroborate` (`tests/test_corroborate_cli.py` and the self-check), collected count.

### Task 2: `research/`
- [ ] Move `research_checks`, `research_pipeline`; importers (`bin/mem-research`), tests to `tests/research/`; rule. Check: suite; `bin/mem-research --help` byte-identical.

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

## Kill criteria

- A golden or `--help` text changes.
- A cycle between packages, or a rule that only passes by allowing a new cross-feature edge.
- A collected-test count changes across a move.
- A patch stops reaching its code.
- A file to touch is unclean and over ~60 findings in one dispatch: split the cleanup.
