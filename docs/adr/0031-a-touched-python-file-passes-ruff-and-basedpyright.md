# 0031 A touched Python file passes Ruff and basedpyright

Status: accepted · Date: 2026-11-25

## Context

The repository holds about 51k lines of Python (the memory engine, `scripts/`, eval runners) with no linter or type checker. The owner wants Ruff for lint and static analysis and Pyright-family type checking, and wants the existing code cleaned gradually, as it is touched, rather than in one pass. Measured on a copy of `dev` at c93bbda, after `ruff format` and Ruff's safe fixes: 2,308 Ruff findings in 129 files under the rules below (`plugins/memory/engine/mem.py` 331; `C901` 182, `PLR2004` 681), and 524 basedpyright errors in mode `standard`.

## Decision

- `ruff.toml` and `pyrightconfig.json` at the root configure every Python file except the generated `ports/` and the ignored `target/`. Ruff rules are the owner's usual set (`A`, `ASYNC`, `C4`, `C90` with complexity 6, `D201`/`D202`/`D204`, `I`, `ISC`, `LOG`, `N`, `PERF`, `PIE`, `PL`, `PYI`, `RET`, `RUF`, `TC` strict, `TID`, `UP`) plus `B` and `SIM`; line length 100, preview on. Type checking uses basedpyright in mode `standard`.
- `python3 scripts/lint_touched.py` is the gate: every `.py` file changed against the merge-base with `origin/dev` (committed, staged, unstaged or untracked) must pass `ruff format --check`, `ruff check` and basedpyright with no finding. Untouched files are not checked. `--fix` formats and applies safe fixes first. The opt-in pre-push hook runs it.
- Tools run through `uvx` at pinned versions (constants in the script), so the repository needs no `pyproject.toml` or virtual environment.

The owner chose "a touched file is fully clean, every rule" after seeing that touching `mem.py` then means about 400 fixes, including complexity refactors (2026-11-25).

## Alternatives

| Alternative | Why not |
|---|---|
| Per-file ratchet (counts may only fall) | Lets a touched file keep its debt; the owner wants a touched file clean |
| Only changed lines must be clean | Same reason; also needs custom diff filtering |
| Relaxed rules (`C901`, `PLR2004`, `PLR09xx` off) in legacy files | The owner kept the full set |
| Clean the whole repository now | Hundreds of changes mixed with other work |
| Pyright | basedpyright is the same engine and config, installs through `uvx` without Node |
| Run it in `validate.py` | `validate.py` stays fast and offline; the tools download on first use |

## Consequences

- The first edit of a large file costs a full cleanup of that file (format, lint, types); plan it into the task that touches it.
- `ruff format` rewrites a file the first time it is touched, so that diff mixes formatting with the change; a separate formatting commit keeps review readable.
- The gate is local: no CI runs it (N5); a machine without `uvx` skips it.
- A clone with neither `origin/dev` nor `dev` cannot compute the touched set: the script exits 2 and the pre-push hook reports it as a failure.

## Revisit if

- A rule's findings are mostly noise across three touched files: drop it from `ruff.toml` with a `## Review` here.
- A touched-file cleanup blocks a small urgent fix twice: consider the changed-lines alternative.
