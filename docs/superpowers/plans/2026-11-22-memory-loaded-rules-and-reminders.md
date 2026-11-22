# Memory capture, stage B4: loaded rules and reminders

**Status (2026-11-22): design open, nothing built.** This file is the handoff for the session that designs and plans B4. Replace the sections below with a `writing-plans` plan once the design is settled with the owner.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md), phase B4; decisions C13, C15, C18, C19, C20, C38. Earlier stage: [B3, plan and results](2026-11-22-memory-capture-corroboration.md). Evidence: [the learning loop study](../../studies/2026-11-21-memory-learning-loop.md) (E4: context files raised cost with no gain in success) and ADR 0023, "Stage B3".

## Goal of B4

Two things load by themselves at session start, under one small budget, and are designed together because they compete for it (the owner, 2026-11-22):

| Part | What it is |
|---|---|
| Loaded rules | Established lessons, as a file generated from the lesson records under a token limit, with space per lesson by its importance and corroboration (C18, C19) |
| Reminders | Temporary records that ask for a piece of work in a later session, shown only as a very short summary |

## Reminders: the owner's idea and rulings (2026-11-22)

| # | Ruling | Source |
|---|---|---|
| R1 | A reminder is a temporary note or memory with an optional start date and an optional end date. It loads by itself when a new session starts, may hold for many sessions, and may stay silent for some sessions until it is due | The owner |
| R2 | Once it no longer takes effect it is removed | The owner |
| R3 | Purpose: to trigger work in a later session or after several compactions, for example a refactoring, a project review, a check of the documentation, a look for new or updated studies and posts | The owner |
| R4 | Against noise, what loads is metadata, kept very short: how many reminders there are, their topics, and how many sessions have passed since each was created, or something of that kind. Not the reminders' full text | The owner, answering the risk below |
| R5 | A compaction counts as a session for that count, because a compaction means time or work has passed | The owner |
| R6 | Designed with B4 and documented with it | The owner |

## Proposals, not decided

The author's, for the design session to keep, change or drop.

| Topic | Proposal | Reason |
|---|---|---|
| Record | A kind of record in the project or the global scope, written with `mem`, as memories are | One store, one set of commands, history and undo for free |
| When it is due | By date, or after a number of sessions (R5 counts compactions); nothing else at first | The two cover every example in R3 |
| What the agent does | Does the work, puts it off for N sessions, or closes it; a recurring one arms itself again ("look for new studies every 30 days") | A reminder that can only be shown again becomes noise |
| Removal (R2) | Retired and restorable, not deleted | As every other record of the plugin |
| Who writes one | The owner, the agent when it defers something (a finding of a review, an item left open), and triage or curation | The B3 stage alone left about twelve deferred items that live only in a plan's table |
| Wording at session start | It asks for the work after the current task, as the "Curation due" line does | A reminder must not derail the work in progress |
| One shown several times with no action | It asks the owner, or lapses | Text shown at every start trains the reader to ignore it |
| Order of building | Reminders before loaded rules | Small, useful at once, and a place to measure whether text loaded at session start is acted on (shown against done) |

## Open design questions

| # | Question |
|---|---|
| Q1 | The exact summary line of R4: its fields, its length limit, and how the agent reads a reminder's full text when it decides to act (a `mem` command) |
| Q2 | Where the session count lives and what raises it: each session start, each compaction (R5), per project or per data folder |
| Q3 | How the budget is split between loaded rules and the reminder summary, and what is dropped first when it is exceeded |
| Q4 | What makes a reminder "no longer in effect" (R2): its end date, the work done, an explicit close, a number of showings |
| Q5 | Loaded rules: which lessons qualify (established; accepted at triage or not), the token limit, the space per lesson, and when the file is regenerated |
| Q6 | Usefulness of a released lesson: reading sightings later than its `released` date as "true but not followed", and whether evidence against a lesson gets a counter (ExpeL removes an insight whose count reaches zero; see ADR 0023, "Stage B3") |
| Q7 | Whether the corroboration pass or curation may write reminders by itself (for example "a lesson in quarantine lapses in 5 days") |

## Facts to reuse

| Fact | Where |
|---|---|
| The session start text is built in one place, has a 4 second budget, and already carries count lines (`Curation due`, `Triage`) and failure lines | `session_index` and `cmd_session_index` in `plugins/memory/engine/mem.py`; `plugins/memory/hooks/session-index.sh` |
| The session start hook also fires after a compaction (matcher `startup\|clear\|compact`), so R5's count can be raised there | `plugins/memory/hooks/hooks.json` |
| A record may carry `valid_until`, and a lapsed record is no longer live | `records.is_live` |
| `released`, `triage` and `owner_confirmed` on a global lesson; quarantine hides an unconfirmed one | `plugins/memory/engine/records.py`; design C31, C38 |
| A background command must find its folders as `mem` does, and at least one test must run with the environment its real launcher gives it | The defect fixed in 0.4.1: [B3 results](2026-11-22-memory-capture-corroboration.md#results) |
| A dry run with the real model on a copy of real records found defects that unit tests and reviews had not | The same results |
| Text that is always loaded raised an agent's cost by over 20% with no gain in success | The learning loop study, E4 |

## Next steps

- [ ] Recall: `mem search` for loaded rules, reminders, session start budget; then research outside what the memory does not cover (scheduled or deferred intents in agent memory systems; how loaded context is kept small and acted on)
- [ ] Read the first real runs: `<data>/capture/log.jsonl` and `<data>/corroborate/log.jsonl`
- [ ] Settle Q1 to Q7 with the owner, one at a time with a recommendation; add the decisions to the design as C40 onward
- [ ] Write the task plan here (`writing-plans`), then a pre-mortem before execution
