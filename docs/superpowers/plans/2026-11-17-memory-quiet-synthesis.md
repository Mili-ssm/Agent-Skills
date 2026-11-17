# Quiet synthesis curation: a named writer and a script-driven pipeline

Owner, 2026-11-17: curation is too verbose and costly when the main session relays every report; a named agent should write syntheses (general-purpose writers showed as such in the interface). Builds on the lean loop measured in `2026-11-17-memory-prompts-and-loop.md` (Haiku writer, one fix round, about 0.25 USD per synthesis at medium effort; the owner then set high effort, unmeasured).

**Status:** in progress.

## Decisions

| Decision | Reason |
| --- | --- |
| A named agent `memory-synthesizer` (Haiku, high effort) writes a synthesis for one topic from the tuned writer brief | The interface names it; model and effort are fixed in its file instead of chosen at each dispatch |
| A command runs the whole pipeline per topic (writer → checker → one fix → scoped check → delete leftovers → attach notes → history commit) as headless sessions, with no main session relaying reports; the caller sees one line at launch and one table at the end | The 2026-11-17 curation's cost and noise came from relaying about a hundred reports |
| The command changes the store only through `mem` (every step undoable with `mem restore`) and commits the history before it starts and when it ends | Reversibility |
| It runs on demand (the owner or an agent launches it), never from a hook, and takes a budget | The owner controls when model usage is spent |
| The trial script and the command share one pipeline module | One implementation of the loop to keep correct |

## Tasks

- [ ] Agent `plugins/memory/agents/memory-synthesizer.md` (body from the tuned writer brief; README subagent row; a trigger eval case seen to fire). Check: `scripts/validate.py`, `claude plugin validate plugins/memory`.
- [ ] Shared pipeline module and the command `plugins/memory/bin/mem-synthesize [--topic T]... [--budget USD] [--dry-run]`: topics default to those `mem curate --notes` lists without a synthesis; prints one table (topic, parts, notes attached, claims fixed and deleted, cost) and writes a log file; `--self-check` without a model. Check: self-check passes; one real run on a temporary copy of a store for one small topic ends with `mem check` 0, notes attached and a history commit in the copy.
- [ ] Skills: `memory-curation` and `memory-synthesis` name the command for topics without a synthesis (bodies only). Check: validators pass.

## Results

Pending.
