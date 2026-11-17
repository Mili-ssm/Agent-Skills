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

- Store: a fresh copy of the owner's default store per pipeline under `target/` (trial fixture), where the script deletes the topic's synthesis file and any note that synthesis created (`--note-slug` notes), clears `part_of` of the topic's notes, and freezes the coverage denominator (the topic's knowledge notes at that moment) before the writer starts; the self-check asserts `mem synthesis new` then succeeds for the topic. The real store is never touched.
- Topics: 4 with 6 to 12 knowledge notes (e.g. human-memory, time-series-forecasting, llm-evaluation, mental-health).
- Briefs: the writer and checker briefs of 2026-11-17 (the hardened versions with the accuracy rules and the stop rule), moved into `plugins/memory/evals/synthesis/` with placeholders, unchanged in substance.
- Arms, each run as separate headless sessions driven by a script, no main session relaying:
  - **S (today's pipeline):** writer Sonnet → one checker Haiku → fixer Sonnet (a session that reads the checker's report file and applies it).
  - **H (cheap loop):** writer Haiku → checker Haiku → fixer Haiku, repeated until the checker reports 0 unsupported claims or 2 fix rounds have run; the loop always ends on a check, whose count is logged beside the judge's.
- Judge, the same for both arms and blind to the arm: one Sonnet fact-check session per final synthesis, with the same checker brief, counting claims checked and unsupported, and marking each note cited in a `Sources:` line as used (a part states something from it) or unused. This is the quality measure; the arms' own checkers are not.
- Sessions: every session gets `Bash(mem *)`, `Read`, `Grep`, `Glob` and `Write` limited to its work folder (body files), `--shrink` allowed for fixes, no web; the smoke asserts that every write exited 0 and no permission was denied.
- Measures per pipeline: unsupported claims per 100 checked (judge), claims checked, words, parts, coverage (knowledge notes of the frozen denominator that the judge marks used / the denominator), `mem check` exit, cost per model summed from `modelUsage` over every session including failed ones, wall time.
- Runs: 4 topics × 2 arms × 2 runs = 16 pipelines plus 16 judge sessions. Estimated cost 6 to 12 USD.
- Decision rule, written before the runs: adopt arm H for synthesis curation when its judged unsupported rate is at most arm S's plus 2 points (per 100 claims, pooled over topics and runs), its claims checked are at least 80% of arm S's (a short, hedged document does not win), its coverage at least arm S's minus 10 points, every H synthesis passes `mem check`, and its total cost is at most half of arm S's; otherwise keep the writer on Sonnet and record the gap; inconclusive (no change) when the two runs of either arm on one topic differ by more than 2 points of unsupported rate pooled over topics.

## Tasks

- [ ] Briefs moved into `plugins/memory/evals/synthesis/` with placeholders (no private paths), and the trial script `run_trials.py` on the `trial_env` fixture: `--self-check` without a model (store copy, synthesis removed and notes detached in the copy, real store untouched), arms S and H, the judge, per-pipeline rows and the rule. Check: self-check passes; one smoke pipeline per arm on the smallest topic, judge included, shows every measure.
- [ ] Run the pipelines in the background; write `## Results` with the table and the action the rule gives.
- [ ] If adopted: the curation skill and the synthesis skill name the cheap loop as the way to write syntheses (bodies only), else record why not.

## Pre-mortem of 2026-11-17 and what changed

| Risk | Change |
| --- | --- |
| The old synthesis leaks or blocks `synthesis new` | Delete the file and its created notes, clear `part_of`, freeze the denominator; self-check asserts `new` succeeds |
| A short, hedged document scores 0 unsupported | Claims checked, words and parts recorded; H needs 80% of S's claims |
| Coverage gamed by unused citations | The judge marks cited notes used or unused; only used ones count |
| The loop ends on an unchecked fix; a refused `edit` fails silently | Loop ends on a check; `--shrink` allowed; arm checker logged beside the judge |
| One claim is 3 points, above the margin | Both arms 2 runs per topic; inconclusive above 2 points |
| A denied write breaks a run silently | Smoke asserts writes exit 0, no denials; cost summed over all sessions |

## Results

Pending.
