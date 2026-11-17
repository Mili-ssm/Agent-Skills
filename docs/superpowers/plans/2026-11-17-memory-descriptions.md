# Memory plugin descriptions: measured changes

Four `description` changes proposed by the prompt audit of 2026-11-17 (`2026-11-17-memory-prompts-and-loop.md`, section Audit). Each is measured before and after and lands in its own commit, so one can be reverted alone (CLAUDE.md: N6, eval protocol). The owner asked for the tests on 2026-11-17.

**Status:** in progress.

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

- [ ] The two new cases, modeled on the existing trigger cases, each seen to run.
- [ ] Changes 1 to 4, each: baseline, change, new run, table row below, own commit (or a recorded revert).

## Results

Pending.
