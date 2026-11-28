# 0031 A touched Python file passes Ruff and basedpyright

Status: accepted · Date: 2026-11-25

## Context

The repository holds about 51k lines of Python (the memory engine, `scripts/`, eval runners) with no linter or type checker. The owner wants Ruff for lint and static analysis and Pyright-family type checking, and wants the existing code cleaned gradually, as it is touched, rather than in one pass. Measured on a copy of `dev` at c93bbda, after `ruff format` and Ruff's safe fixes: 2,308 Ruff findings in 129 files under the rules below (`plugins/memory/engine/mem.py` 331; `C901` 182, `PLR2004` 681), and 524 basedpyright errors in mode `standard`.

## Decision

Current gate: pre-commit (`.pre-commit-config.yaml`), per the last Review; the second and third bullets describe the first, superseded gate.

- `ruff.toml` and `pyrightconfig.json` at the root configure every Python file except the generated `ports/` and the ignored `target/`. Ruff rules are the owner's usual set (`A`, `ASYNC`, `C4`, `C90` with complexity 6, `D201`/`D202`/`D204`, `I`, `ISC`, `LOG`, `N`, `PERF`, `PIE`, `PL`, `PYI`, `RET`, `RUF`, `TC` strict, `TID`, `UP`) plus `B` and `SIM`; line length 100, preview on; `plugins/memory/bin/*` targets py310 because those scripts run with the system `python3`. Type checking uses basedpyright in mode `standard`.
- *Superseded:* `python3 scripts/lint_touched.py` is the gate: every `.py` file changed against the merge-base with `origin/dev` (committed, staged, unstaged or untracked) must pass `ruff format --check`, `ruff check` and basedpyright with no finding. Untouched files are not checked. `--fix` formats and applies safe fixes first. The opt-in pre-push hook runs it.
- *Superseded:* tools run through `uvx` at pinned versions (constants in the script), so the repository needs no `pyproject.toml` or virtual environment.

The owner chose "a touched file is fully clean, every rule" after seeing that touching `mem.py` then means about 400 fixes, including complexity refactors (2026-11-25).

## Alternatives

| Alternative | Why not |
|---|---|
| Per-file ratchet (counts may only fall) | Lets a touched file keep its debt; the owner wants a touched file clean |
| Only changed lines must be clean | Same reason; also needs custom diff filtering |
| Relaxed rules (`C901`, `PLR2004`, `PLR09xx` off) in legacy files | The owner kept the full set |
| Clean the whole repository now | Hundreds of changes mixed with other work |
| Pyright | basedpyright is the same engine and config, installs without Node (now a pinned pre-commit `language: python` hook) |
| Run it in `validate.py` | `validate.py` stays fast and offline; the tools download on first use |

## Consequences

- The first edit of a large file costs a full cleanup of that file (format, lint, types); plan it into the task that touches it.
- `ruff format` rewrites a file the first time it is touched, so that diff mixes formatting with the change; a separate formatting commit keeps review readable.
- The gate is local (N5): a commit made with `--no-verify`, or in a clone without pre-commit installed, skips it until a push from a clone with pre-commit installed, or `pre-commit run --from-ref origin/dev --to-ref HEAD` (the `core.hooksPath` fallback runs no Ruff or basedpyright).

## Revisit if

- A rule's findings are mostly noise across three touched files: drop it from `ruff.toml` with a `## Review` here.
- A touched-file cleanup blocks a small urgent fix twice: consider the changed-lines alternative.

## Review 2026-11-25

The owner asked for the pre-commit framework. `.pre-commit-config.yaml` holds two local hooks that call the repo's own scripts, so tool versions stay pinned only in `scripts/lint_touched.py`: on commit `lint_touched.py --fix` (formats, safe-fixes, then blocks on what remains), on push `scripts/hooks/pre-push`. `pre-commit install` refuses to run while `core.hooksPath` is set; `git config core.hooksPath scripts/hooks` stays the push-only path for a clone without pre-commit. (The two script-calling hooks were superseded by the later Review.)

Also 2026-11-25: "Python file" includes extensionless scripts whose shebang names python (the six `plugins/memory/bin/mem-*` scripts, about 4,000 lines), which the gate first missed.

## Review 2026-11-25 (later): pre-commit replaces the script

On the owner's proposal, `scripts/lint_touched.py` and its tests are removed: pre-commit selects the files natively. `.pre-commit-config.yaml` runs `ruff-check --fix` and `ruff-format` (`astral-sh/ruff-pre-commit`) and basedpyright `--warnings` (a local `language: python` hook pinned to `basedpyright==1.40.2`) on the staged files at commit and on the pushed commits' files at push; `pre-commit run --from-ref origin/dev --to-ref HEAD` checks a whole branch. pre-commit's file typing recognises python-shebang scripts when they are executable (all of `plugins/memory/bin/` is), and `exclude: ^(ports|target)/` keeps the generated and ignored trees out. Versions are pinned only in that file (`pre-commit autoupdate` moves Ruff). It supersedes the Decision's second and third bullets (the script, `uvx`) and the Consequences line on a machine without `uvx`. The rule itself is unchanged: a touched Python file must be fully clean; a file is checked when it is committed, so unstaged or untracked work is checked at its commit, not before. A commit made with `--no-verify` or without pre-commit installed skips the check until the push hook or the branch-wide run.


## Review 2026-11-26: `mem.py` clean

`plugins/memory/engine/mem.py` and `tests/test_curation.py` now pass the gate with no finding, behavior unchanged. Plan: [mem.py clean](../superpowers/plans/done/2026-11-26-mem-py-ruff-clean.md). It unblocked one user-visible change: the session start text names `memory:memory-curator` when curation is due.

| Measure | Before | After |
|---|---|---|
| `mem.py` Ruff findings (after safe fixes; 361 at `dev`) | 333 | 0 |
| `mem.py` basedpyright errors | 62 | 0 |
| `test_curation.py` Ruff / basedpyright | 50 / 3 | 0 / 0 |
| `mem.py` lines | 6,102 | 10,532 |
| Top-level functions and classes | n/a | 616 (66 functions split into helpers) |
| Tests | 2,272 passed, 5 skipped | 2,272 passed, 5 skipped |
| Golden run on a copy of the owner's store (about 50 read commands, 12 write scenarios) | n/a | identical to `dev` except the session start sentence |

**How.** 12 tasks. Whole-file passes in sequence (format and imports, small rules, types, the test file), then a pilot group of functions, then six groups decomposed in parallel git worktrees and merged without conflict. No suppression comment, no config change. 15 broad `except Exception` handlers stay broad with `logger.debug(..., exc_info=True)` (owner decision, 2026-11-26). Functions over 5 parameters with outside callers take typed `**options` (`Unpack[TypedDict]`), so no calling file changed. 104 names that live in `check`, `notes` and `index` remain readable as `mem.<name>` through a module `__getattr__`.

**Cost in shape.** The file grew by about 73% (formatter line length 100 plus helper extraction): the gate was met by more, smaller functions, not by a shorter file.

**Defect caught by review.** An "unused" variable in `unify_notes` was an implicit refusal of a note resolved outside the store; removing it as dead code changed behavior. Neither the tests nor the golden run covered it. Restored explicitly in `841f436`.

**Lesson for the next large file** (`check.py`, `notes.py` and others are not clean yet): record a golden comparison on a copy of real data before the first edit, and decompose one pilot group before the parallel fan-out, so the recipe (helpers, `**options`, logging) is settled once. Treat every "unused" or "unreachable" finding as a possible implicit behavior and ask what it did before deleting it.
