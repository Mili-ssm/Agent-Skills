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
