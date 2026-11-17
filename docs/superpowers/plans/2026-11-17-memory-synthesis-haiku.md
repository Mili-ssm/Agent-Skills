# Synthesis writing on Haiku with a checker loop: experiment plan

**Goal:** Find out whether a synthesis written by Haiku, checked and fixed in a loop by Haiku, is as accurate and complete as one written by Sonnet with one Haiku fact-check (the pipeline of the 2026-11-17 curation), and at what cost. Owner's open items 1 (cost of curation) and 3 (an independent cheap checker that iterates with the writer).

**Status:** planned 2026-11-17; not started.

## Decisions already taken (owner, 2026-11-17)

| Decision | Reason |
| --- | --- |
| Measure the synthesis writer on Haiku first (not the recorder) | It was the large cost of the curation: about 25 Sonnet writers plus checks and fixes used about 30% of a 5-hour window |
| A cheap independent checker that iterates with the writer is to be tested | The 2026-11-17 pipeline relayed every report through the expensive main session |
| Cost is planned and stated before runs | The owner's usage limits |

## Design, fixed before any run

- Store: a fresh copy of the owner's default store per pipeline under `target/` (trial fixture), with the topic's existing synthesis removed and its notes detached in the copy only; the real store is never touched.
- Topics: 5 with 6 to 12 knowledge notes and an existing synthesis to compare with (e.g. human-memory, time-series-forecasting, llm-evaluation, mental-health, philosophy-of-science).
- Briefs: the writer and checker briefs of 2026-11-17 (the hardened versions with the accuracy rules and the stop rule), moved into `plugins/memory/evals/synthesis/` with placeholders, unchanged in substance.
- Arms, each run as separate headless sessions driven by a script, no main session relaying:
  - **S (today's pipeline):** writer Sonnet → one checker Haiku → fixer Sonnet (a session that reads the checker's report file and applies it).
  - **H (cheap loop):** writer Haiku → checker Haiku → fixer Haiku, repeated until the checker reports 0 unsupported claims or 2 rounds have run.
- Judge, the same for both arms and blind to the arm: one Sonnet fact-check session per final synthesis, with the same checker brief, counting claims checked and unsupported. This is the quality measure; the arms' own checkers are not.
- Measures per pipeline: unsupported claims per 100 checked (judge), coverage (knowledge notes of the topic cited in some `Sources:` line / knowledge notes of the topic), parts, `mem check` exit, cost per model and total (sum of the sessions' `result` events), wall time.
- Runs: 5 topics × 2 arms × 1 run, plus a second run of the arm-H pipeline on 2 topics to see its variance. Estimated cost 4 to 9 USD (judge included).
- Decision rule, written before the runs: adopt arm H for synthesis curation when its judged unsupported rate is at most arm S's plus 2 points (per 100 claims, pooled over topics), its coverage at least arm S's minus 10 points, every H synthesis passes `mem check`, and its total cost is at most half of arm S's; otherwise keep the writer on Sonnet and record the gap; inconclusive (no change) when the two H runs of one topic differ by more than 5 points of unsupported rate.

## Tasks

- [ ] Briefs moved into `plugins/memory/evals/synthesis/` with placeholders (no private paths), and the trial script `run_trials.py` on the `trial_env` fixture: `--self-check` without a model (store copy, synthesis removed and notes detached in the copy, real store untouched), arms S and H, the judge, per-pipeline rows and the rule. Check: self-check passes; one smoke pipeline per arm on the smallest topic, judge included, shows every measure.
- [ ] Run the pipelines in the background; write `## Results` with the table and the action the rule gives.
- [ ] If adopted: the curation skill and the synthesis skill name the cheap loop as the way to write syntheses (bodies only), else record why not.

## Results

Pending.
