# Ruff and basedpyright: a touched Python file must be clean

Status: in progress (2026-11-25) · Branch: `chore/ruff-pyright` · Decision: ADR 0031

## Owner rulings (2026-11-25)

| Ruling | Kind |
|---|---|
| Ruff for lint and static analysis, basedpyright for types | functional, hard |
| A Python file changed against `dev` must pass `ruff format --check`, `ruff check` and basedpyright with no finding; untouched files are not checked | technical, hard |
| Rules: the owner's usual set (from another project of theirs) plus `B` and `SIM`, line length 100, preview on; pyright mode `standard` | technical, soft: revisit if a rule mostly yields noise |
| `ruff format` applies when a file is touched, never repo-wide in one commit | technical, soft |

Measured before the change (copy of HEAD, after format and safe fixes): 2,308 Ruff findings in 129 files (`mem.py` 331; C901 182, PLR2004 681); basedpyright standard 524 errors. Touching `mem.py` therefore means cleaning it whole: accepted by the owner.

## Tasks

- [x] 1 Config: `ruff.toml`, `pyrightconfig.json` at the root (exclude `ports/`, `target/`); check: both tools run on one file and report the expected rules
- [x] 2 `scripts/lint_touched.py`: list the `.py` files changed against the merge-base with `origin/dev` (committed, staged, unstaged, untracked; not deleted; not `ports/`), run the three checks on them, exit non-zero on any finding, pinned tool versions; `--fix` formats and applies safe fixes; tests in `scripts/tests/`; check: tests pass, a dirty touched file fails, no touched file passes
- [x] 3 Wire and document: pre-push hook step, `CLAUDE.md` Commands row, README § Develop row, ADR 0031; check: `validate.py`, hook runs the step
- [ ] 4 Review (`skeptical-reviewer`), PR to `dev`
