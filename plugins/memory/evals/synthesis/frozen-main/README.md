# frozen-main

One file: `checker-brief.md`, the checker brief exactly as it is on `main` (commit `7d190a1`,
`plugins/memory/engine/synth_briefs/checker-brief.md`). It is the judge's brief for every arm of the synthesis trial
(`../run_trials.py`): the judge reads each synthesis with its references removed, so the count of unsupported claims
means the same for a pipeline before and after inline references.

It is frozen because the engine's checker brief will change with the references; the judge must not move with it. Do not
edit it.

Arm M is not made from frozen texts any more: `run_trials.py` runs `main`'s own harness from a git worktree of `main`,
so the control is `main` as shipped (its skill, agents, `mem` and loop), and this folder only supplies the judge.
