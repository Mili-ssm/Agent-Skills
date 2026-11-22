# Memory capture, stage B4: loaded rules and reminders

**Status (2026-11-22): designed and ruled on by the owner; decisions C40 to C50 of the spec. First release, reminders: [its plan](2026-11-22-memory-reminders.md). Second release, loaded rules: no plan yet.** This file is the handoff for the session that designs and plans B4. Replace the sections below with a `writing-plans` plan once the design is settled with the owner.

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

## Recall and research (2026-11-22)

What the owner's memory and outside sources say, and what each changes in the design. Papers dated after mid 2026 were read by a research worker only; check a number at its source before it carries a decision.

| Finding | Source | What it changes |
|---|---|---|
| Context files gave no general gain in task success and raised cost by about 20%; agents did follow what the file named | arXiv 2602.11988; the learning loop study, E4 | The loaded text stays small, and a rule that does not apply to the session is cost only |
| Instruction following falls as instructions grow: about 98 to 100% at 10, 95 to 98% at 100, 49 to 69% at 500; earlier instructions are favoured | IFScale, arXiv 2507.11538 | A few tens of rules at most; the strongest first |
| Rewriting a whole playbook with a model loses detail ("context collapse", "brevity bias"); entries added one by one with helpful and harmful counters did better | ACE, arXiv 2510.04618 | The loaded rules are assembled from records by code, never rewritten whole by a model; a counter per lesson (Q6) |
| "Load identifiers, fetch detail when needed" is the vendor's own advice; no controlled comparison against full text was found | Anthropic, "Effective context engineering" (2025-09-29) | Supports R4: a summary line and a command for the full text |
| An intention stored with an optional activation condition and a type, once or recurring, retired when acted on, missed fewer intentions than baselines (miss rate 0.063 against 0.248 on PM-Bench) and still gave false alarms (0.38 to 0.42 on another benchmark). Closing on "the agent answered" is not proof the work was done | Pro-Memory, arXiv 2611.05731; PM-Bench, arXiv 2607.12385 | The record shape of a reminder; closing one states what was done |
| Products trigger by time, a few by event; expiry features (mem0, LangGraph) only hide a record. None documents what the model sees at session start, a rule for a reminder shown and not acted on, or a measure of reminders acted on | ChatGPT tasks, Claude Code scheduled tasks, Cursor and Devin automations, mem0, LangGraph docs | R4, the count of R5 and "shown against done" have no prior art found: measure them ourselves |
| Agents miscompute relative times ("now + 1 hour") | A Letta forum post, low rank | `mem` computes every date and count; the agent passes "in 3 sessions" or a date, never arithmetic |
| The session start text is capped at 1500 characters; no count of sessions exists; the hook receives `source` (`startup`, `clear`, `compact`) and only logs it; `resume` loads no text | `session_index`, `cmd_session_index` in `plugins/memory/engine/mem.py`; `plugins/memory/hooks/hooks.json` | Where the count of R5 and the summary line go |
| First real logs: one capture (8 written, 190 s, 0.11 USD), two passes from reviewed groups, none with model sessions yet | `<data>/capture/log.jsonl`, `<data>/corroborate/log.jsonl` | Nothing to correct before B4; the first pass with model sessions is still to be read |

## Design

The owner ruled on 2026-11-22; the decisions are C40 to C50 of [the capture design](../specs/2026-11-21-memory-capture-design.md), which is their one home.

| Release | Scope | Decisions | Plan |
|---|---|---|---|
| First | Reminders, the session count, the summary line, the measure of showings | C40 to C45, C50 | [reminders](2026-11-22-memory-reminders.md) |
| Second | Loaded rules, the line for lessons that did not load, usefulness of a released lesson, the limits of the whole text | C46 to C49, C50 | Not written |

To settle before the second release: whether lessons in quarantine count in the line of C47 (the author's reading, not yet the owner's word), and where a lesson's topic and short form are written (at capture, at triage, or by the corroboration pass).

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

- [x] Recall: `mem search` for loaded rules, reminders, session start budget; then research outside what the memory does not cover (scheduled or deferred intents in agent memory systems; how loaded context is kept small and acted on)
- [x] Read the first real runs: `<data>/capture/log.jsonl` and `<data>/corroborate/log.jsonl`
- [x] Settle Q1 to Q7 with the owner; decisions C40 to C50 in the design
- [x] First release: task plan and pre-mortem, in [its plan](2026-11-22-memory-reminders.md)
- [ ] Second release: task plan and pre-mortem, after the first release's measure has data
