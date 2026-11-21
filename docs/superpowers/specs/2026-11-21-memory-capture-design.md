# Memory capture from a session transcript: design

Status: the owner agreed to this design on 2026-11-21 (step L3 of [the learning loop study](../../studies/2026-11-21-memory-learning-loop.md); stage 9 and decision D20 of [the memory plugin design](2026-11-17-memory-plugin-design.md)). Phase A is planned in [the trial plan](../plans/2026-11-21-memory-capture-trial.md); phase B is built only if the trial passes.

## Goal

Lessons, pitfalls and decisions of a session reach the project's memory even when the main agent did not record them, without adding wrong or duplicate records and without the main session waiting.

## Decisions

| # | Decision | Reason |
|---|---|---|
| C1 | A candidate is kept only when it is tied to one signal: `owner_correction`, `failed_then_passed` (a check or command that failed and later passed), `verified_review_finding`, `repeated_tool_error`, `decision_with_reason` | A model that criticises itself with no outside signal does not improve (study, E1) |
| C2 | Each candidate carries a quote of its evidence, and code drops the candidate unless that quote occurs in one line of the extract it was given; for the two owner signals that line must be the owner's own (a subagent's report is a different line kind) | Stored experiences propagate their errors (E9); the check is mechanical, not a second opinion of the same model |
| C3 | The process reads the transcript, never the compaction summary | Notes written from a summary carry more errors (E3) |
| C4 | The model gets no Bash and no web: it reads the extract and writes one JSON file inside a work folder; code validates and writes | As `mem-settle` does; a background model cannot write on its own |
| C5 | Project scope only; kinds `lesson`, `pitfall`, `decision`; at most 5 candidates per run | A wrong record must not reach every project; a cap keeps the review queue short |
| C6 | A captured record has origin `transcript` and is shown as `from transcript, unconfirmed` until `mem confirm` is run on it; it is valid for 30 days | "Provisional" stays implicit in words agents already meet (`web, unconfirmed`, `mem confirm`); no new status, so no query that filters by status changes; an unconfirmed record expires by itself |
| C7 | The claims of the project's active memories are given to the model as "already recorded" | The main agent records too; an identical claim is already refused at writing |
| C8 | Haiku first; Sonnet only if the trial keeps too few | Cost; the trial decides |
| C9 | Phase A is offline: `mem-capture` writes candidates to a file and never to the store | Stage 9's adoption check comes before any hook |

## Phases

| Phase | Contents | Gate |
|---|---|---|
| A, trial | `capture.py` (extract, validate), `bin/mem-capture run --transcript ... --out ...`, a run over 10 past transcripts, the owner marks each candidate keep or drop | Adopt if at least 60% of the candidates are kept and no kept candidate duplicates an existing record; inconclusive below 15 candidates or 5 producing transcripts; else change the prompt or the model once, then stop. Figures go to ADR 0023 |
| B, wiring | Origin `transcript` and its tag; a curation category "from transcript, not confirmed"; `mem-capture run` writing through `mem remember`; an offset per session; launch from `PreCompact` and `SessionEnd` behind a plugin option `auto_capture` (off by default); a lock, a status file and a failure line as `mem-settle` has | A plan of its own, with a pre-mortem |

## Not in this design

Global records; notes; a signal during a run (L5); graduation of repeated lessons (L4).
