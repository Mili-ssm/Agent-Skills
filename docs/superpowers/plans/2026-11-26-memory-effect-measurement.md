# Memory: measure the effect of loaded lessons before adding mechanisms

Status: in progress · Date: 2026-11-26 · Branch: feat/memory-lesson-holdout (stacked on fix/skeptical-reviewer-p1-b1, PR #218)

Owner ruling (2026-11-26): proceed with the order the review of that day proposed. Why: the review found no measure that the plugin improves a task, three mechanisms that hardly act in real use, and 2026 studies in which memory did not beat a memory-off baseline. Figures and sources: project memories (`mem search "after 5 days of automatic capture"`, `mem search "VibeMemBench"`).

## Tasks

- [x] 1. The background curator can list unread short forms. `mem rules --unread` joins `MEM_ALLOWED` (`engine/synthesize/pipeline.py`), read-only form only (`rules --unread`, never `rules --read`). Check: the golden test of the session command line names the new rule; engine suite passes.
- [x] 2. ~~Hold-out of loaded lessons~~ and 3. ~~`mem rules --effect`~~: **dropped after the pre-mortem of 2026-11-26**, before any code (reasons below). Replaced by task 7.
- [x] 4. Outcome criteria proposed for the kill read of 2026-12-01, beside the accepted ones: plugin plan § Kill criteria and § Current state; backlog. Check: `python3 scripts/validate.py`.
- [x] 5. Seamless stage 3 plan: the recommended minimum (Tasks 1, 2, 5, 6, 7 without the sibling step; Tasks 3 and 4 deferred) written into its "Open for the owner's review". Not executed. Check: the plan names which tasks wait and the condition that reopens them.
- [x] 6. Design only, written below; nothing built: it needs a paid trial and its budget from the owner: matching by meaning for `mem-settle` and for new lessons (five nearest records, one Haiku judge per pair, verdict applied by code). Check: a design section with its trial rule and cost estimate, for the owner.
- [ ] 7. Paired offline trial of the loaded lessons (design below). Waits for the owner's budget. Check: its `## Results` holds the table and the action its rule gives.

## Why the hold-out was dropped (pre-mortem, 2026-11-26)

The design withheld a deterministic sample of the loaded lessons per session and compared failed cases between sessions with and without each lesson (the owner's rotation idea of 2026-11-24). The pre-mortem checked it against the code and the real logs:

| Finding | Evidence |
|---|---|
| It cannot answer at this volume | 17 global lessons load; their cases dated after they loaded are 1 failed and 1 worked. At about 58 held (session, lesson) pairs a day, a 50% reduction in failures needs about 20,000 pairs per arm, close to a year; eight weeks reads only a reduction of about 80% or more |
| It corrupts what is already built | The case log has no arm, and `got_worse` (`engine/memories/sightings.py`) feeds the automatic rewording and the "balance got worse" queue: a failure in a session that never saw the lesson would reword a good lesson |
| The held arm is not "absent" | In the digest layout a topic heading written from all its lessons still prints, and `mem search` returns held lessons |
| Exposure counts are inflated | 66 `session-index` rows fell within one minute on 2026-11-26 and 33 within another (scripted sessions, inferred); capture covered 39 sessions in all |
| Cases cluster by session | 51 cases come from 17 sessions, one holds 12: intervals per pair would treat them as independent |

Kept from it: the rotation idea stays in the plugin plan's list to investigate, with this section as its evidence; it becomes viable when loaded lessons and sessions are several times more, and it then needs the arm written into the case entry.

## Paired offline trial of the loaded lessons (task 7)

Question: when a loaded lesson bears on the task, does the session follow it more often than with no lessons, and what does the block cost when none bears? It measures behavior on built tasks, not the net benefit in real work: that limit is stated in the result.

Base: `plugins/memory/evals/rules_layout/run_trial.py` (headless Sonnet sessions in a fresh git project, practices scored by code, the owner's folders checksummed before and after) and the measurement of 2026-11-22 (three rules, 0 of 3 runs without and 3 of 3 with, about 0.06 USD a run; capture design C53). What C53 did not measure is what this trial adds: the real block, many lessons, a token-matched control, tasks where no lesson bears.

| Decision | Choice | Reason |
|---|---|---|
| Lessons | The loaded lessons whose practice leaves a trace code can score (a command run, a tool called, a file written, an order of steps). Chosen and listed before any run, with the scoring rule of each; a lesson with no such trace is listed as not measured | A judge model would add its own error; C53 scored by code |
| Scenarios | One small task per chosen lesson in which the practice bears and is not asked for, plus one third as many tasks in which no lesson bears | The second kind measures cost and over-application |
| Arms | N: no lessons. L: the block as `mem session-index` prints it for the real store's lessons (layout `digest`, the owner's setting). P: a block of the same length made of lessons from other topics, the scenario's lesson removed | P matches the tokens, so L against P separates the lesson from the extra text ("Are Online Skill and Memory Modules Always Worth Their Tokens?", arXiv 2606.15017) |
| Runs | 5 per scenario and arm, Sonnet, same flags; a session that fails or runs out of turns is an error and is rerun once, never a wrong answer | Three runs showed a collapse only (the harness's own README) |
| Measures | Practice followed (primary); the task's own check passed; cost and turns per run | |
| Reading, fixed here | Per scenario the difference in runs that followed the practice, L minus P and L minus N; over scenarios a paired permutation test on those differences. The lessons "help when they bear" when L minus P is at least 30 points on average with p below 0.05. The block "costs" when cost on the no-lesson tasks rises by more than 10% from N to L, or their task check fails more often in L than in N by 2 runs or more (a coarse bar over about 15 runs an arm: it catches a collapse, not a small harm) | Paired differences on the same items give the tighter interval (store notes on paired comparison and small eval sets) |
| Canary | Before the paid run: one scenario at one run per arm must show the block in arm L's session start text and not in arm N's, and a deliberately broken scorer must score 0 | A broken harness must not read as "no effect" |

Action by the rule: help and no cost → keep the loaded block, and the rotation idea waits for volume. No help → the short forms are the suspect (they drop the situation; VibeMemBench, arXiv 2609.23570, reports that memory systems reach the relevant history and lose in how they render it): rewrite a sample with the situation and the action stated and rerun before any other mechanism. Cost without help → lower `RULES_LIMIT` or load only by topic.

Cost estimate: 10 lesson scenarios and 3 without, 3 arms, 5 runs: 195 runs at about 0.06 USD (2026-11-22) is about 12 USD; estimates in this project were low by 3 to 5 times, so the cap bounds the spend, and in-flight runs pass a cap unless each command's cap is set below the total. A pilot of 4 scenarios, arms N and L, 3 runs is 24 runs, about 1.5 USD.

## Matching by meaning: design for the owner (task 6, not built)

Problem, measured: `mem-settle` showed 1 pair in 65 real runs and corroboration added 7 sightings to 107 transcript lessons in five days, because `records.pairs` (`engine/memories/matching.py`) keeps a pair only at a word containment of 0.6 and real paraphrases score 0.41 to 0.58 (plugin plan § Current state, owner's item of 2026-11-24). The run and lesson counts were read from the plugin's logs and the default store on 2026-11-26 and are recorded as project memories (`mem search "after 5 days of automatic capture"`, `mem search "mem-settle production"`), not in a tracked file. So duplicates stay apart, a lesson seen again in other words gains no sighting, and 90 general lessons wait in quarantine with a 30-day expiry.

Proposal, in the shape the owner sketched on 2026-11-24:

| Step | Who | Rule |
|---|---|---|
| Candidates | Code | For each record not yet judged, its five nearest live records of the same kind family by containment, with a floor of 0.25 in place of 0.6; pairs already marked `distinct` are skipped |
| Judgment | One Haiku session per pair, no shell, no web (`core/headless.py`, as `mem-settle`) | A one-sentence reason first, then `same`, `newer state`, `different`; anything else applies nothing |
| Second opinion | A second session with its own brief, only for `same` and `newer state` | Applied only when both agree (seamless plan, stage 3 amendment A4: Haiku verdicts flipped on about 13 pairs in 100; C39 asks for a proposer and an independent verifier) |
| Action | Code | Memories: the existing judged mode of `mem curate apply` (the older record is the one superseded, never an overwrite). Lessons: a sighting on the existing lesson, never a merge of wordings (C39). Every action is logged and undone with one command |

Trial before it is turned on, rule fixed here: 60 pairs built from real records on a store copy (20 paraphrases written by a session that does not see the judge's brief, 20 valid versions that must stay apart, 20 unrelated look-alikes above the 0.25 floor), two runs. Adopt when no run applies a wrong action on more than 1 pair of 60, at least 14 of the 20 paraphrases are joined, and the two runs agree on at least 54 of 60. The result is preliminary if the paraphrase writer reused more than half of the base's content words (measured by containment), the limit the stage W trial named for its own paraphrases; the half is this plan's choice.

Cost estimate: one session per pair costs about 0.004 USD at Haiku (the measured cost of one short-form session of `mem-corroborate`, 2026-11-26); the stage W trial judged 32 pairs in one session for 0.018 USD, about 0.0006 USD a pair, but one case at a time is what C39 found a small model judges better. The trial: 60 pairs, two runs, a second session on the positives, about 160 sessions, about 0.65 USD, capped at 2 USD. A daily run over about 30 new records with five candidates each is about 150 sessions, about 0.6 USD; batching the candidates of one record into one session would cut that to about 0.1 USD and is the first thing to compare in the trial. The 0.004 USD is taken from a session of another kind and the number of second sessions depends on how many pairs are judged positive, so both are assumptions the trial replaces with measured figures. Earlier estimates in this project were low by 3 to 5 times.

Open for the owner: the budget; whether the pass replaces `mem-settle`'s pair source or runs beside it; whether a lesson joined this way counts as a sighting when both wordings came from one session (proposed: no).
