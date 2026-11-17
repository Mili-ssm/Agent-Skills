# Memory plugin descriptions: measured changes

Four `description` changes proposed by the prompt audit of 2026-11-17 (`2026-11-17-memory-prompts-and-loop.md`, section Audit). Each is measured before and after and lands in its own commit, so one can be reverted alone (CLAUDE.md: N6, eval protocol). The owner asked for the tests on 2026-11-17.

**Status:** done 2026-11-17; all four changes kept.

## Rules

- Baseline first (the description as on `main`), then the new text, same case, same flags, Sonnet as the main model, 2 runs; a case that is not 2/2 or falls below its baseline reruns at 6 on both sides; a drop of 2 or more of 6 reverts that change.
- Every eval session uses temporary store and data folders (`MEM_STORE`, `MEM_MEMORIES`, `XDG_DATA_HOME`, `MEM_DATA` under `target/`), never the owner's store.
- Total budget 8 USD; stop and report when the running total passes it. Results are written into this file as they come.

## Changes

| # | File | Change | Cases |
| --- | --- | --- | --- |
| 1 | `skills/memory-synthesis/SKILL.md` | Typo "or or when" → "or when" | `evals/trigger/memory-synthesis` |
| 2 | `skills/memory/SKILL.md` | Cut the how-clause "in three cheap steps (…), and records what was learned in one call"; keep every "Use when" trigger | `evals/trigger/memory`, then `evals/routing/run_trials.py` (9 cases) |
| 3 | `agents/memory-recorder.md` | Append a trigger: "or when a summary lists items marked 'not yet recorded'" | new case `evals/trigger/memory-recorder-after-compaction`: a prompt that carries a compaction summary with three such items; fired = an `Agent` call to `memory-recorder`, or `mem remember` calls for the items |
| 4 | `agents/memory-curator.md` | Name the notes queue: "and notes (`mem curate --notes`)" | new case `evals/trigger/memory-curator-due`: a session told "Curation due"; fired = an `Agent` call to `memory-curator` |

## Tasks

- [x] The two new cases, modeled on the existing trigger cases, each seen to run.
- [x] Changes 1 to 4, each: baseline, change, new run, table row below, own commit (or a recorded revert).

## Results

Sonnet main model, `--ablation none`, temporary store and data folders under `target/`. Fired = the case's grader matched.

| # | Case | Baseline | New | Decision |
| --- | --- | --- | --- | --- |
| 1 | `trigger/memory-synthesis` | 2/2 | 2/2 | kept |
| 2 | `trigger/memory` | 2/2 | 2/2 | kept |
| 2 | `routing/run_trials.py` (9 cases) | 9/9 | 9/9 | kept |
| 3 | `trigger/memory-recorder-after-compaction` | 2/2 | 2/2 | kept |
| 4 | `trigger/memory-curator-due` | 1/2, rerun at 6: 3/6 | 1/2, rerun at 6: 2/6 | kept (drop of 1 of 6, below the revert threshold) |
| 5 | `trigger/memory-curator-due` (curator description states the apply mode, 2026-11-17) | 1/2, rerun at 6: 4/6 | 1/2, rerun at 6: 4/6 | kept (no change; the case stays weak and noisy) |

Cost: about 1.6 USD for the `claude plugin eval` runs (reported by the tool, including the first runs of the new cases); the 18 routing sessions report no cost, estimated at most 3 USD. Running total stays under the 8 USD budget.

Limits of the measurement:

- The routing run for change 2 used the text before a punctuation fix (" -, and" became " - and"); the trigger case ran on the final text.
- `memory-recorder-after-compaction` is not discriminating: the baseline already fires 2/2, mostly through the `memory` skill and `mem remember` (the grader accepts either), not through the `memory-recorder` agent. Bash is denied in the eval, so the session reports it could not write.
- `memory-curator-due` is weak at baseline (3/6): a session-start notice inside the user prompt is a weaker signal than the real hook text. The change is not shown to help or hurt within this noise.
