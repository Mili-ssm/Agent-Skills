# Quiet synthesis curation: a named writer and a script-driven pipeline

Owner, 2026-11-17: curation is too verbose and costly when the main session relays every report; a named agent should write syntheses (general-purpose writers showed as such in the interface). Builds on the lean loop measured in `2026-11-17-memory-prompts-and-loop.md` (Haiku writer, one fix round, about 0.25 USD per synthesis at medium effort; the owner then set high effort, unmeasured).

**Status:** implemented; the trigger case fires 1 of 2.

## Decisions

| Decision | Reason |
| --- | --- |
| A named agent `memory-synthesizer` (Haiku, high effort) writes a synthesis for one topic from the tuned writer brief | The interface names it; model and effort are fixed in its file instead of chosen at each dispatch |
| A command runs the whole pipeline per topic (writer → checker → one fix → scoped check → delete leftovers → attach notes → history commit) as headless sessions, with no main session relaying reports; the caller sees one line at launch and one table at the end | The 2026-11-17 curation's cost and noise came from relaying about a hundred reports |
| The command changes the store only through `mem` (every step undoable with `mem restore`) and commits the history before it starts and when it ends | Reversibility |
| It runs on demand (the owner or an agent launches it), never from a hook, and takes a budget | The owner controls when model usage is spent |
| The trial script and the command share one pipeline module | One implementation of the loop to keep correct |

## Tasks

- [x] Agent `plugins/memory/agents/memory-synthesizer.md` (body from the tuned writer brief; README subagent row; a trigger eval case seen to fire). Check: `scripts/validate.py`, `claude plugin validate plugins/memory`.
- [x] Shared pipeline module and the command `plugins/memory/bin/mem-synthesize [--topic T]... [--budget USD] [--dry-run]`: topics default to those `mem curate --notes` lists without a synthesis; prints one table (topic, parts, notes attached, claims fixed and deleted, cost) and writes a log file; `--self-check` without a model. Check: self-check passes; one real run on a temporary copy of a store for one small topic ends with `mem check` 0, notes attached and a history commit in the copy.
- [x] Skills: `memory-curation` and `memory-synthesis` name the command for topics without a synthesis (bodies only). Check: validators pass.

## Results

**Where things live.** Pipeline module `plugins/memory/engine/synth_pipeline.py` (the lean loop, the parsers and `run_session`) with the checker and fixer briefs in `plugins/memory/engine/synth_briefs/`; `evals/synthesis/run_trials.py` imports them and keeps only its own writer brief; `--self-check` passes in both scripts. The command's writer is `claude -p --agent memory:memory-synthesizer` (the flag exists), so the agent file is the single source of the writer prompt; the caller's prompt gives topic, slug, store, work folder and the skill file path.

**Trigger case** `evals/trigger/memory-synthesizer` (Sonnet main, 2 runs, 0.11 USD): fired 1 of 2. Not below any record (new case), but short of the 2/2 bar of the protocol; a rerun at 6 runs and a description change were not made (outside this task's budget). Run 1 did not delegate.

**Real run** on a copy of the owner's store (history initialised in the copy, the `human-memory` synthesis deleted and its notes detached), `--topic human-memory --budget 1`, about 9 minutes wall:

| topic | parts | notes attached | claims fixed | claims deleted | mem check | cost USD |
| --- | --- | --- | --- | --- | --- | --- |
| human-memory | 6 | 6 | 7 | 1 | 0 | 0.260 |

Two history commits in the copy (`mem-synthesize: before human-memory`, `after`). Per session (USD): writer 0.055, checker 0.125, fixer 0.038, scoped checker 0.020, deleter 0.023. The owner's store showed no change from this work.

**Findings during the run**
- A first attempt was cut by a shell `timeout` at 580 s (the pipeline takes about 9 minutes per topic): launch it in the background, and the cost estimate for `--dry-run` (0.5 USD per topic) is conservative against 0.26 measured.
- The plugin's `SessionEnd` hook would commit the store after every headless session, so the command writes `disableAllHooks: true` into the sessions' settings and gives `MEM_STORE` in their environment (the brief's `pluginConfigs` is also passed). Hooks do not run in those sessions.
- The fixer changed parts outside the reported ones in this run (`scope_violations` in the log); the guard only records, as in the trial. Not measured further.
- Default store resolution: `--store`, else `MEM_STORE`, else the default XDG store; a store set only in the plugin's config file is not found (pass `--store`).

## Extension (owner, 2026-11-17): the curator applies, and an automatic run

The owner chose all three ways to make curation quiet: A (the curator applies in one dispatch), B (above, built), C (an automatic run), with one condition for C: a failure must be made visible. The owner watches usage and switches C off if it grows.

### Decisions

| Decision | Reason |
| --- | --- |
| A: `memory-curator` gains an apply mode, used only when the caller's prompt says "apply": it runs the reversible actions of a safe subset — `mem merge` without `--force` (the tool refuses claims that differ in a negation, a number or an opposite), `mem synthesis attach` of a note to a part whose `Sources:` line already links it — and reports counts plus one line per item left. Everything else stays a proposal | A wrong merge costs more than a duplicate; the subset is the part the tool itself guards, and every action is undone by `mem restore` |
| C: an option of the plugin (`auto_curation`, off by default) lets a session start launch one detached background run when curation is due, no other run holds the lock, the last run is older than 20 hours and the day's budget is not spent. The run: the curator in apply mode, then `mem-synthesize` with a budget (default 2 USD per run) | Automatic, bounded, one at a time |
| C never runs git or a model inside the hook itself: the hook only starts the detached process and returns | The session-start budget is 0.5 s |
| C's result goes to a status file (time, ok or failed, reason, cost, log path). After a failure, the next session's start text carries one line naming the failure and the log until `mem auto ack`; after a success nothing is added | The owner's condition; the measured session text is unchanged unless a run failed |
| The headless sessions of a run disable hooks and take the lock, so a run cannot start another | No recursion |
| In `mem-synthesize`, a fixer that changes a part outside its report gets that part put back from the text before the fix | Seen once in the real run of B; until now only logged |

### Tasks

- [x] A: apply mode in `agents/memory-curator.md` (body; its description says it proposes and applies nothing, so that line changes and is measured on `evals/trigger/memory-curator-due`), one line in `skills/memory-curation/SKILL.md`. Check: on a temporary store seeded with one exact duplicate pair, one pair differing in a number and one attachable note, an apply dispatch merges the first, leaves the second, attaches the third, and `mem restore` undoes each.
- [x] The out-of-scope guard in the pipeline, with a self-check case (`guard_parts` in `synth_pipeline.py`; `reverted` column in the table).
- [x] C: `plugins/memory/bin/mem-auto` (run, status, ack), the launch from the session-start hook, the option in `plugin.json`, the failure line in the session text, tests for due/lock/budget/failure line, and a spike first: can a session-start hook start a detached process that outlives it and finds the `claude` binary. Check: with the option off nothing starts; with it on and a fake `claude`, one run starts, a second session start does not start another, a failing run leaves the status and the next session text shows the line, `mem auto ack` removes it.
- [x] Docs: README section; kill criteria: a run that costs over its budget, two failures in a week, or the owner's word turn the option off.

### Pre-mortem of the extension, 2026-11-17, and what changed

| Risk | Change (binding for the tasks above) |
| --- | --- |
| A killed run leaves no status and relaunches at the next start, adding cost | Under the lock and before any model call the run writes `started` and reserves the day's budget; a `running` older than 1 hour counts as failed and is shown; the spike covers closing the terminal, finding `claude` and credentials |
| Several session starts race the lock | The child takes `flock -n` as its first action and exits quietly when busy |
| The safe subset lived only in the curator's prompt (Bash unrestricted; the refusal message suggests `--force`; opposites in other words pass the guard) | A new engine command `mem curate apply --safe` reads action lines (`merge <keep> <drop>`, `attach <note> s:<h>#<section>`) and enforces the subset in code: merge only when the claims are equal after normalization, never `--force`; attach only when the part's `Sources:` line links the note; anything else is listed as left. The curator's apply mode and `mem-auto` act only through it |
| The run and the owner write the store at once (commits take in the owner's edits; log trimming can drop an entry being appended) | One store-wide run lock; `curate --done` trimming and the session-end commit skip while a run holds it; trimming runs under the commit lock |
| The option test is "non-empty", so `"false"` turns it on; a store set only as an option is missed by the run | The option counts only when it is exactly `true`; the hook passes the resolved store with `--store` |
| The trigger counts project memories while the run writes store syntheses; a failing topic is retried every 20 hours | C's own due test (a topic with 8 notes and no synthesis, or a non-empty global queue); a topic that failed twice is skipped until `mem auto ack`; the run never records `curate --done` |
| A killed run or a success shows nothing; transcripts sit in a world-readable folder forever | Run folders are created with mode 0700 and kept 30 days; `mem auto status` shows the last run, its cost and result |

Kill criteria for C: more than one run in a day, a day's spend above its budget, or two failures in a week turn the option off.

### Owner, later the same day (replaces C's launch and due rules)

1. **Launch** from the `SessionEnd` hook, after its commit (not from session start): the next session then starts with the memory already curated. The spike showed a detached process survives from `SessionEnd` and finds `claude` (see Results).
2. **Trigger** is a threshold, not every session: global memories plus notes written since the last automatic run started (or the last curation pass, whichever is later) reach `auto_curation_threshold` (default 10); `mem curate --new-since EPOCH` counts them (file times; an edit counts). After a run starts the count restarts from its start.
3. **Fewer restrictions** (the owner is the only user): no 20-hour rule, no per-day budget or reservation, no skip list. Kept: `flock -n` first, the per-run budget (default 2 USD), status at start and end with `running` over 1 hour shown as failed, the failure line until `mem-auto ack`, folders 0700 and 30-day pruning, the option read as exactly `true`, `--store`, the run lock respected by `curate --done` trimming and the session-end commit, hooks off in the run's sessions.

Pre-mortem rows that no longer apply: the one on the 20-hour rule and day budget reservation (row 1, partly: only the `running` and stale part stays), the due test and skip list (row 6: the threshold replaces the due test, there is no skip list, so `ack` clears only the failure). Rows 2, 3, 4, 5 and 7 stand.

The trigger case of `memory-synthesizer` fired 1 of 2, then 6 of 6 at the protocol's rerun (0.39 USD): kept.

### Results of C

**Spike** (Haiku, one-word prompt, about 0.01 USD each, throwaway plugin under `target/`): a hook that starts `setsid nohup bash -c 'sleep 25; ...' &` with stdio redirected survives the `claude -p` session from both `SessionStart` and `SessionEnd` (child alive after the session exited, reparented, own session id, finished 25 s later). In the hook environment: `HOME` and `CLAUDE_PLUGIN_OPTION_<NAME>=true` (a boolean option arrives as `true`) are present; `CLAUDE_CODE_EXECPATH` is not (with a clean environment) and `claude` is not on `PATH` in this setup; `/proc/$PPID/exe` is the claude binary, so the hooks fall back to it. **Built: launch from `SessionEnd`** (owner's preference), in `hooks/session-end.sh` after the commit.

**Built.** `bin/mem-auto` (`run`, `status`, `ack`, `due`, `--self-check`), `engine/auto_state.py` (state folder, run lock, failure line), `mem curate --new-since EPOCH` (the trigger count), lock checks in `curate --done` (trimming now under the commit lock) and in the session-end commit, the failure line in `mem session-index`, options `auto_curation`, `auto_curation_budget`, `auto_curation_threshold`; `mem-synthesize` run() takes `root` and `rows_out`. Tests: `engine/tests/test_auto_curation.py` plus two in `test_store_git.py`; suite 942 passed, 4 skipped.

**Real run** on a copy of the owner's store under `target/` (history initialised, placeholder syntheses so only `genetics` was due, option forced on through env, budget 0.6): status `ok`, cost 0.150 USD (curator 0.004: applied 0, left 2; genetics synthesis 4 parts, 2 notes attached, 7 claims fixed, 1 deleted, `mem check` 0), history commits `mem-auto: before/after curation` found nothing to commit and `mem-synthesize: after genetics` was made, run folders mode 0700. The run's own attaches counted as new records (2) on a first count from its start, so the count now starts from the run's end.

