# Memory: measure the effect of loaded lessons before adding mechanisms

Status: in progress (task 8, the scenario with headroom) · Date: 2026-11-26, last worked 2026-11-27 · Branch: feat/memory-lesson-holdout for tasks 1–7; task 8 on a branch of its own, created when it starts

Owner rulings (2026-11-26): proceed with the order the review of that day proposed; the paired trial starts as a pilot capped at 3 USD; matching by meaning is built after it, its trial capped at 2 USD. Why: the review found no measure that the plugin improves a task, three mechanisms that hardly act in real use, and 2026 studies in which memory did not beat a memory-off baseline. Figures and sources: project memories (`mem search "after 5 days of automatic capture"`, `mem search "VibeMemBench"`).

## Where to resume

Owner rulings of 2026-11-27: adopt the `mem-settle` change (task 6); build the reduced scope of seamless stage 3 ([its task plan](2026-11-26-memory-seamless-stage-3-integration.md#reduced-scope-proposed-2026-11-26-accepted-by-the-owner-2026-11-27)); merge the pending pull requests (PR #218 merged that day); build a more serious scenario for the trial of the loaded lessons (task 8). Model usage spent on this plan before task 8: 1.53 USD (pilot 1.46, settle trial 0.065) of the 5 USD the owner allowed (3 for the pilot, 2 for the settle trial).

## Tasks

- [x] 1. The background curator can list unread short forms. `mem rules --unread` joins `MEM_ALLOWED` (`engine/synthesize/pipeline.py`), read-only form only (`rules --unread`, never `rules --read`). Check: the golden test of the session command line names the new rule; engine suite passes.
- [x] 2. ~~Hold-out of loaded lessons~~ and 3. ~~`mem rules --effect`~~: **dropped after the pre-mortem of 2026-11-26**, before any code (reasons below). Replaced by task 7.
- [x] 4. Outcome criteria proposed for the kill read of 2026-12-01, beside the accepted ones: plugin plan § Kill criteria and § Current state; backlog. Check: `python3 scripts/validate.py`.
- [x] 5. Seamless stage 3 plan: the recommended minimum (Tasks 1, 2, 5, 6, 7 without the sibling step; Tasks 3 and 4 deferred) written into its "Open for the owner's review". Not executed at that review; accepted by the owner on 2026-11-27. Check: the plan names which tasks wait and the condition that reopens them.
- [x] 6. Matching by meaning for `mem-settle`: its pair list looks at a lower floor (section below). Built and measured on 2026-11-27: by the trial's rule not adopted, on one count that rests on a reading of two records; **adopted by the owner on 2026-11-27** on that reading (Results). Check: the trial rule of that section, results under `## Results`.
- [x] 7. Paired offline trial of the loaded lessons (design below): the pilot ran on 2026-11-27 and the full trial is not run (see Results). Check: its `## Results` holds the table and the action its rule gives.
- [ ] 8. A scenario with headroom for the loaded lessons (owner, 2026-11-27: "a more serious scenario"): tasks the model fails without the lesson, found before any arm is compared. Check: its design section names how headroom is shown first, and a run's table is under `## Results`.

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

### Pilot (owner, 2026-11-26: cap 3 USD)

Four scenarios, arms N and L, 3 runs each, run one after another so no run in flight passes the cap: `plugins/memory/evals/lessons_effect/`. Arm L's session start text is what `mem rules --layout digest` prints for the owner's real lessons, read once before the first model call; a scenario whose lesson is not in that text is void, not a miss. No lesson text and no handle is stored in the repository: a scenario names its lesson by marker words.

| Scenario | The loaded lesson it tests (topic) | Outcome scored by code |
|---|---|---|
| `pipe-status` | shell: a test piped into `tail` before `&&` lets a failure through | A failing check with a clean-looking tail: no commit was made |
| `docs-against-code` | docs: review commands and options against the code before closing a docs change | The README's wrong option name is fixed or named in the reply |
| `real-data` | testing: reproduce the symptom with the real data source, not only fixtures | The tool runs on the real file after the fix |
| `keep-the-look` | ui: change only what was asked | The label changed and the stylesheet's bytes did not |

The pilot answers two things only: whether the harness measures (canary, void runs, scores that differ between runs), and whether arm N leaves room: a scenario that arm N already passes in 3 of 3 runs has no headroom and says nothing about its lesson (VibeMemBench recommends gating on headroom). It cannot support "the lessons help": 4 scenarios and 3 runs are below the reading rule above.

## Replay of real failures (task 8): the scenario with headroom

Problem: the pilot's four written tasks left no headroom (both arms 3 of 3), so they say nothing about the lessons. The owner asked on 2026-11-27 for a more serious scenario. The only tasks known to have headroom are the ones the model already failed: each lesson's case log names the sessions in which its practice failed, and those transcripts are still on disk.

Design, as amended by the pre-mortem of 2026-11-27: copy a real transcript up to the message just before the failing action, resume the copy headless, and score the model's next action, with the block of lessons printed again at the cut, once without the lesson and once with it. Nothing in the replay runs a tool.

| Decision | Choice | Reason |
|---|---|---|
| Points | One per `failed` case of a lesson whose session belongs to this repository and whose transcript still exists (11 cases in 7 sessions on 2026-11-27, more with the project-scope lessons). For each, the failing assistant message is located by hand and recorded with the cut in a private file under `target/` (git-ignored): session, cut, lesson, scoring rule. Checked per point without a model: the lesson's marker words are in no block of the copy before the cut; no compaction lies before the cut; the context at the cut, read from the usage of the last assistant entry, fits the model's window | Sessions of other projects hold client conversations and are never replayed. No transcript text, session id or lesson handle is tracked. A lesson already in the baseline, or a cut after a compaction, makes the arms equal for a mechanical reason |
| Scoring rule per point, written before any run | A yes or no question about the next assistant message (its text and the tool calls it asks for), answered by code where a trace decides it (a tool name, a command pattern, a length), else by a judge session that sees the question, the last owner turn and the message with any sentence that quotes the lesson removed, and never the arm. Two controls, both required: the rule fails the original failing message, and it passes one compliant message written by hand for the point. A rule that misses either is rewritten or its point dropped | The practices in the case log are mostly judgment (ask before building, check scope, read examples first). A rule that fails everything would pass a single control and read as "the lesson does nothing" |
| Replay | A copy of the transcript cut before the first entry of the failing message, session id and working folder rewritten, `cost-state` entries removed (measured: the copy otherwise carries the original session's cost into the result and the budget); `claude -p --resume <copy> --fork-session --no-session-persistence --max-turns 1`, prompt `Continue.` when the cut falls inside a turn; working folder: a detached worktree of this repository at the last commit before the cut's timestamp; a `PreToolUse` hook denies every tool, and a denied call is data, not an error (measured: it appears in the result's `permission_denials`). User plugins stay off (`--setting-sources project`): the real memory plugin would capture the replay at session end and write a `failed` case to the owner's store. The agent and skill listings are rebuilt with `--plugin-dir` for `agent-skills` only | Measured on 2026-11-27: the copy resumes; in an empty folder with plugins off the model first remarked that the repository and the agents were gone |
| Arms | R0: the block the session itself received at its start, taken from the copy, printed again at the cut by a `SessionStart` hook that matches `resume`. R: the same block with the lesson's line added under its topic | One line of difference, one shared prefix, and no dependence on today's store. It is the situation right after a compaction, the best position a lesson can have. The plugin never prints on resume (its matcher is `startup|clear|compact`), so this hook is the trial's own |
| Arm S, only after its spike | The lesson's line added to the block at the copy's start, against the copy as it was | The lesson at the start of a long session. Not built until the wire capture below shows that a resume sends the edited entry: it may rebuild its request from the recorded request entries, which hold a second copy of the block |
| Wire capture, before any paid run | Each arm resumed once against a local server that records the request and answers with an error (`ANTHROPIC_BASE_URL`): the two requests must differ by exactly the lesson's line, at the cut, with the same tools and agents | No model cost; it replaces trust in how a resume builds its request |
| Headroom gate | 3 runs of R0 per point; a point enters the comparison only when at least 2 of 3 fail again. The gate's runs are not reused, and a point's comparison follows its gate at once, while the prefix is still cached | A failure that does not repeat was chance ("Lessons from Luck", arXiv 2610.33029); gating on the arm the comparison uses keeps the headroom real; fresh runs avoid reading regression to the mean as an effect |
| Runs | 5 per arm per gated point, Sonnet. Per-run cap set from the point's context size, never below its first cache write | The pilot's cap of 0.20 USD a run is below the 0.38 USD measured for a first write |
| Reading, fixed here | A table per point (runs that follow the practice in R0 and in R), and a count of points where R is ahead, behind or level, one point per session in the count (the point with the smaller context). No p-value: with at most 7 sessions a sign test cannot go below 0.016 and one tie puts it out of reach. The lesson "helps when fresh" when R is ahead by 2 runs or more of 5 in at least 5 sessions and behind in none; "does not help" when it is ahead in at most 1; anything else is "not decided at this size" | Stated before spending: this size detects only a large effect |
| Canary | Without a model: R's hook text holds the lesson's line and R0's does not; both scoring controls pass. With a model, on the first point: the trace shows the hook's text in both arms | A broken harness must not read as "no effect" |

Action by the rule: helps when fresh → the lesson works when it is near the decision, so build arm S to learn whether it also works from the start; if not, print the block again at an interval or by topic. Does not help on failures that repeat → the short forms do not carry the practice: rewrite them with the situation and the action stated and rerun before any other mechanism.

Kill criteria: the wire capture shows the arms equal, or different anywhere but the lesson's line → fix before any paid run; fewer than 6 points pass the per-point checks → report the table of points and spend nothing; the gates of the first 3 points all pass (no failure repeats) → stop and re-plan; any change to the owner's store, case log or background-pass state during a run or 60 seconds after it → stop at once; the first two points cost more than twice their estimate → stop and ask the owner.

Measured cost (2026-11-27, two probes, 0.39 USD): a Sonnet replay at about 120,000 tokens of context cost 0.38 USD, nearly all of it the first write of the prefix to the cache; later runs on the same prefix read it. Contexts at the candidate cuts reach 190,000 to 590,000 tokens in six of the seven sessions, and the cost of a first write grows with them, so the estimate is made per point from its measured context before a cap is asked for. Rough bound today: gate plus comparison on one point, 13 runs on one prefix, 1 to 3 USD; eight points 10 to 25 USD. Estimates in this project were low by 3 to 5 times, so the cap bounds the spend and runs go one after another.

Limits, known before the run: one next message is scored, so a practice that shows only later in the turn is not measured and its point is dropped at the scoring-rule step; the worktree lacks whatever was uncommitted at the time; the lesson was written from this very failure, so the replay tests whether the lesson fixes its own case, the easiest case for it; points come from one repository and one owner and several share a session; the replay runs on Sonnet while the failures happened on a larger model, whose name the recorded system prompt still carries; `Continue.` is a message the original session did not have, the same in both arms.

Not started until the owner sets a cap: every paid run of this section. Built without a model: the harness, its self-check against a fake `claude`, the wire capture, the private points file with its per-point checks.

## Matching by meaning (task 6): settling looks at a lower floor

Problem, measured: `mem-settle` showed 1 pair in 65 real runs, because `records.pairs` (`engine/memories/matching.py`) keeps a pair only at a word containment of 0.6 and real paraphrases score 0.41 to 0.58 (plugin plan § Current state, owner's item of 2026-11-24). The run counts were read from the plugin's logs on 2026-11-26 and are recorded as project memories (`mem search "mem-settle production"`), not in a tracked file.

Measured on the owner's 226 live global memories outside quarantine on 2026-11-27, before choosing the means:

| Containment floor | Pairs |
|---|---|
| 0.6 (the queue's) | 0 |
| 0.5 | 5 |
| 0.4 | 11, one of them a true duplicate at 0.57 |
| 0.3 | 54 |
| 0.25 | 150 |

Built (owner, 2026-11-27: yes, its trial capped at 2 USD): the pair search takes its floor from `records.PairSearch` (`records.pairs_by`), and settling passes 0.4 (`PAIR_FLOOR` in `engine/settle/verdicts.py`); the curation queue, which people read, keeps 0.6. Everything after the pair list is `mem-settle` as it was measured in stage W: one session with no shell judges the pairs, code applies the verdicts (the older record is the one superseded, a flagged pair is never merged, nothing is overwritten), and `mem settle undo` restores a pair. This replaces the first design of this section (five nearest records, one session per pair, a second opinion), which built a second judging pass beside one that already passed its trial; the model was never the measured problem, the pair list was.

Scope: memories only. Lessons are already matched by meaning by `mem-corroborate` (C28, C39); their few sightings come from the two-project rule and the volume, not from the matching, so nothing changes there. Records that existed before this change are already counted as judged, so the eleven existing pairs are not offered: they reach the curation queue only by hand.

Trial, rule fixed on 2026-11-27 before the run (`plugins/memory/evals/settle/run_trial.py`, the stage W harness and its 55 base records under `target/`, which allow one derived record per base): 54 derived records written by a session that sees neither the settle brief nor the matching code: 18 paraphrases in other words, 18 versions that are both valid and must stay apart, 18 unrelated look-alikes; two runs. Adopt when no run takes a wrong action on more than 1 record, the queue shows at least 11 of the 18 paraphrases and at least 13 of the 18 are joined in each run (if fewer than 11 are shown the result is a retrieval finding: record it and try 0.3 once), and the two runs decide the same on at least 49 of 54. Estimate: about 0.05 USD a run from stage W (0.018 USD for 32 pairs); cap 2 USD.

Kill criteria after it is on, those of stage W in the seamless plan: a week of settling runs costs more than 1 USD, or the owner undoes 2 settlings in a week.

## Results

### Pilot, 2026-11-27 (`plugins/memory/evals/lessons_effect/run_trial.py --runs 3`, Sonnet, 24 sessions and 2 canary sessions, 1.46 USD of the 3 USD cap)

| Scenario | Arm N (no lessons) avoided the failure | Arm L (the loaded block) | Mean cost N / L (USD) |
|---|---|---|---|
| `pipe-status` | 3 of 3 | 3 of 3 | 0.053 / 0.052 |
| `docs-against-code` | 3 of 3 | 3 of 3 | 0.054 / 0.061 |
| `real-data` | 3 of 3 | 3 of 3 | 0.058 / 0.068 |
| `keep-the-look` | 3 of 3 | 3 of 3 | 0.056 / 0.060 |

The canary passed in both arms, no run was an error, and the owner's folders did not change. By the pilot's own rule every scenario has **no headroom**: the model without lessons already set `pipefail`, ran the tool on the real file, named the README's wrong option and left the stylesheet alone (read in the traces of run 1, and re-scored afterwards on the 24 kept projects with stricter checks: no commit and one reflog entry; the total printed for the real file with the data untouched; the button's class and the stylesheet unchanged). In `docs-against-code` every session of both arms named the right option in its reply and none corrected the README, which the scenario counts as avoided because the task asked only for one added sentence. So the pilot says the harness measures and says **nothing about whether the lessons help**. Mean cost over the 12 runs of each arm: 0.055 USD without and 0.060 USD with the block, about 10% more on tasks this small (the block is a larger share of a tiny session than of a real one); three runs a cell cannot separate that from noise.

What it changes:

- The full trial as designed (ten scenarios of this kind) would repeat this: a small isolated task does not reproduce a failure that happened deep in a long session. It is not run.
- The lessons were captured from long sessions under load. A scenario with headroom has to start from that state: the candidate design is a replay, the real session up to the turn before the recorded failure, continued with and without the lesson, on the sessions whose `failed` case produced each lesson. Open: whether a headless session can be continued from a cut copy of a transcript with a different session start text, and its cost per run (a long context, not 0.06 USD). To be designed with the owner before any build.
- Until a scenario with headroom exists, the outcome rows proposed in the plugin plan's kill criteria cannot be read; the cost row can.

### Settling at a floor of 0.4, first two runs, 2026-11-27 (0.036 USD)

The derived records as written: paraphrases at a median containment of 0.61 with their base (11 of 18 at 0.6 or more, 4 between 0.4 and 0.6, 3 below), versions 0.42, unrelated 0.39. So the old floor already showed 11 of the 18 paraphrases and the new one can add 4: the writer kept the terms a fact needs (commands, identifiers, numbers).

| | Run 1 | Run 2 |
|---|---|---|
| Records written | 41 of 54 | 41 of 54 |
| Paraphrases shown, of the 14 written | 12 | 12 |
| Paraphrases joined | 6 | 6 |
| Wrong actions | 1 (a version merged) | 1 (the same one) |
| Same decision in both runs | 52 of 54 | |

**By the rule: not adopted** (6 joined, 13 needed), and the trial itself was incomplete: the harness wrote no source, and `mem remember` refuses a `finding` without one, so 13 records (4 of them paraphrases) were never written.

What the runs showed, read in the verdict files: the judge called all 12 shown paraphrases the same fact. It merged the 6 whose pair had no flagged word and answered `nothing` on the 6 that had one ("same status, but the flagged word not makes a merge unsafe"): `flagged_words` lists a negation present on one side only, the brief forbids a merge for such a pair, and the brief offers `supersede` only for a correction. A fact reworded from "does not keep" to "drops" is flagged. So the limit on settling is no longer the pair list alone: a reworded duplicate with a negation on one side has no decision that joins it.

One revision, declared before its runs (the same records, since new ones would cost another writer and the change is not fitted to them; that it is the same set is a limit of the result):

- The harness gives a `finding` a source, so all 54 records are written.
- The brief lets `supersede` join a flagged pair that states the same fact: the newer wording stays active and the older record is kept as superseded, which `mem settle undo` restores. Code already allows `supersede` on a flagged pair; only the brief's meaning of the word changes.
- Same rule, same thresholds.

### Settling at a floor of 0.4, after the revision, 2026-11-27 (0.029 USD; 0.065 USD for the four runs, cap 2 USD)

| | Run 1 | Run 2 | Rule |
|---|---|---|---|
| Records written | 54 of 54 | 54 of 54 | |
| Paraphrases shown | 15 of 18 | 15 of 18 | at least 11 |
| Paraphrases joined | 14 (6 merged, 8 superseded) | 14 (6 merged, 8 superseded) | at least 13 |
| Wrong actions | 1 | 2 | at most 1 in each run |
| Same decision in both runs | 52 of 54 | | at least 49 |
| Unrelated look-alikes acted on | 0 of 18 | 0 of 18 | |

**By the rule: not adopted**, on one count: run 2 took 2 wrong actions. The three paraphrases never shown score below 0.4 with their base.

The wrong actions are two records labelled `version`, joined to their base (one in both runs, the other in run 2 only). Read after the runs: both restate their base's fact and add no case of their own (one repeats a rule about reading and writing a folder; the other states the positive side of the base's sentence about what a rename rewrites), and the judge's reasons say so ("same rule ... stated in other words"). By that reading they are paraphrases the writer mislabelled, and joining them loses nothing. A label changed after the result is not a measure, so the rule's verdict stands and the reading was put to the owner, who adopted the change on it on 2026-11-27: adopted on the reading, the rule not met.

Limits: one set of records, used for the runs before and after the revision; the writer and the judge are models of one family; 11 of the 18 paraphrases already passed the old floor, so the trial says more about the brief's revision than about the floor (on the 14 paraphrases written in both rounds, 12 shown each time: 6 joined before the revision, 12 after; recounted from the kept result files under `target/`); the trial holds no pair of opposite claims in which the newer one is the wrong one, a case the brief's `supersede` cannot tell from a correction and that stage W did not test either; with the lower floor more runs find a pair and start a session (about 0.015 USD each, at most one per `auto_settle_minutes`), which the weekly kill criterion bounds; no run on the real store (records that exist there are already counted as judged).

State: the owner adopted the floor (`PAIR_FLOOR`) and the brief's revision on 2026-11-27, on the reading above of the two `version` records; the trial's rule on its own did not pass, and the limits above stand. Unreleased; it acts only where `auto_settle` is on. Kill criteria: those of the section "Matching by meaning".
