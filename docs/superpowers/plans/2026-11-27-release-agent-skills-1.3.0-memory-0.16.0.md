# Release agent-skills 1.3.0 and memory 0.16.0

Owner rulings 2026-11-27: run both pending paid evals before merging (total cap 7 USD: integrate trial 1 USD, lessons replay 6 USD); versions agent-skills 1.3.0, memory 0.16.0; delete only the obsolete branch `worktree-agent-af277e2c1ede63629` (keep `test/repo-gate`, `idea/memory-reminders`).

- [x] Delete obsolete branch (its commits are already in `dev`; the locked worktree folder belongs to a live session and stays)
- [x] Self-checks of both harnesses pass (`run_trial.py --self-check`, `replay_run.py --self-check`)
- [x] Integrate trial (PR #221), run at 0.30 USD: pass, 0 of 17 appends placed (30ac0e4)
- [x] Lessons replay (PR #220), cap 6 USD: 3.016 USD, no verdict below six points (fb54544)
- [x] Merge #220 and #221 into `dev` (checks green after each; backlog conflict resolved by hand)
- [x] Release prep on `dev`: bump `plugin.json`, CHANGELOG `[Unreleased]` → version + date, `validate.py --release` passes (also tool-fold 0.1.1: `validate.py --release` requires a bump for its refactor commit)
- [x] Release PR `dev` → `main` (#222), merged; tags `agent-skills-v1.3.0`, `memory-v0.16.0`, `tool-fold-v0.1.1` pushed
- [x] Installed plugins updated and versions confirmed (1.3.0, 0.16.0, 0.1.1); offload table unchanged, nothing to re-paste
