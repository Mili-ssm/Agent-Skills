# Memory: measure the effect of loaded lessons before adding mechanisms

Status: in progress · Date: 2026-11-26 · Branch: feat/memory-lesson-holdout (stacked on fix/skeptical-reviewer-p1-b1, PR #218)

Owner ruling (2026-11-26): proceed with the order the review of that day proposed. Why: the review found no measure that the plugin improves a task, three mechanisms that hardly act in real use, and 2026 studies in which memory did not beat a memory-off baseline. Figures and sources: project memories (`mem search "learning funnel"`, `mem search "VibeMemBench"`).

## Tasks

- [x] 1. The background curator can list unread short forms. `mem rules --unread` joins `MEM_ALLOWED` (`engine/synthesize/pipeline.py`), read-only form only (`rules --unread`, never `rules --read`). Check: the golden test of the session command line names the new rule; engine suite passes.
- [ ] 2. Hold-out of loaded lessons (design below). Check: its tests; `mem session-index --hook` with a session id and `MEM_RULES_HOLDOUT=30` prints a block without the held lessons and logs both lists as keys; the same id gives the same split twice.
- [ ] 3. `mem rules --effect`: the report of failed and worked cases per arm (design below). Check: its tests on a built log and records; on the real store it prints the "too few to read" line.
- [ ] 4. Outcome criteria proposed for the kill read of 2026-12-01, beside the accepted ones: plugin plan § Kill criteria and § Current state; backlog. Check: `python3 scripts/validate.py`.
- [ ] 5. Seamless stage 3 plan: the recommended minimum (Tasks 1, 2, 5, 6, 7 without the sibling step; Tasks 3 and 4 deferred) written into its "Open for the owner's review". Not executed. Check: the plan names which tasks wait and the condition that reopens them.
- [ ] 6. Not built here, needs a paid trial and its budget from the owner: matching by meaning for `mem-settle` and for new lessons (five nearest records, one Haiku judge per pair, verdict applied by code). Check: a design section with its trial rule and cost estimate, for the owner.

## Hold-out design (tasks 2 and 3)

Intent (owner's idea of 2026-11-24, plugin plan § Current state): leave a sample of the loaded lessons out of some sessions, so that what follows with and without each lesson can be compared. It is the usefulness signal C49 lacks: on 2026-11-26 the case logs held 4 cases dated after their lesson loaded.

| Decision | Choice | Reason |
|---|---|---|
| Unit | The pair (session, lesson). A lesson is held out of a session when `sha256(session id + NUL + handle)`, as an integer, modulo 100 is below the percent | Deterministic: the same session gets the same split at start, after `/clear` keeps its id or a compaction, and the report can recompute it |
| Where | After `rules.choose` filled the block: a held lesson is removed from `loaded` into `Choice.held`. It is in no index line and no count, and `mem rules --more` does not list it for that session | Removing before the fill would let another lesson take its place, so one lesson's arm would change which other lessons load |
| Never held | A lesson of weight `strong`; a session with no id (`mem rules`, a hook input without `session_id`) holds nothing | `strong` is the measure of grave (C63) |
| Option | `rules_holdout`, an integer percent, default 0 (off), capped at 50; the hooks pass it as `MEM_RULES_HOLDOUT` | Off by default: it withholds lessons on purpose, so the owner turns it on |
| Log | The `session-index` hook log line gains `session` (the id), `holdout` (the percent), `loaded` and `held` (lists of keys: the first 12 hex characters of `sha256(handle)`) | The hook log holds no text: a handle is a note title |
| Outcome | A lesson's case-log entry (`<date> session <id> worked\|failed`) whose session is an exposure row | The capture model sees every recorded lesson whatever the arm, so matching a case to a lesson does not depend on the arm |
| Report | `mem rules --effect [--since DATE]`: per arm (loaded, held) the exposures, the failed and the worked cases, the failed rate with a 95% Wilson interval, and the difference; then the lessons with at least one case. Below 200 exposures in either arm or 10 failed cases in all it prints "too few to read" above the table | Fixed before any data: a threshold after the fact can be chosen to fit |
| Reading | Aggregate first. A lesson is judged alone only at 30 exposures per arm. No automatic action on the result: it goes to the owner at the kill read and to `mem curate` only by a later plan | One user and a rare outcome: the first read is expected after about four weeks at 30% |

Limits, stated now: the outcome is rare (about one failed case per day over all loaded lessons on 2026-11-26), so the test has low power and may stay inconclusive; a faster complement is a paired offline trial built from the sessions that produced each lesson (with and without the lesson, same token budget), which costs model usage and is not in this plan. Sessions of one id that change project keep one split. A lesson held out cannot prevent its failure in that session: that cost is the price of the measure, bounded by the percent.

Kill criteria: the owner reports a failure a held lesson would have prevented and judges it too costly → set the option to 0; the hook's logged duration rises above its 0.5 s budget → remove the lists from the log line first; after eight weeks the report is still "too few to read" → stop the hold-out and build the offline trial instead.
