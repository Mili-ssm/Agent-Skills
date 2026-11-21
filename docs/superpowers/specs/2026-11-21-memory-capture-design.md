# Memory capture from a session transcript: design

Status: the owner agreed to this design on 2026-11-21 (step L3 of [the learning loop study](../../studies/2026-11-21-memory-learning-loop.md); stage 9 and decision D20 of [the memory plugin design](2026-11-17-memory-plugin-design.md)). Phase A is planned in [the trial plan](../plans/2026-11-21-memory-capture-trial.md); phase B is built only if the trial passes.

## Goal

Lessons, pitfalls and decisions of a session reach the project's memory even when the main agent did not record them, without adding wrong or duplicate records and without the main session waiting.

## Decisions

| # | Decision | Reason |
|---|---|---|
| C1 | A candidate is kept only when it is tied to one signal: `owner_correction`, `failed_then_passed` (a check or command that failed and later passed), `verified_review_finding`, `plan_changed_by_review`, `delegation_failed`, `rework`, `repeated_tool_error`, `decision_with_reason` | A model that criticises itself with no outside signal does not improve (study, E1) |
| C2 | Each candidate carries a quote of its evidence, and code drops the candidate unless that quote occurs in one line of the extract it was given; for the two owner signals that line must be the owner's own (a subagent's report is a different line kind) | Stored experiences propagate their errors (E9); the check is mechanical, not a second opinion of the same model |
| C3 | The process reads the transcript, never the compaction summary | Notes written from a summary carry more errors (E3) |
| C4 | The model gets no Bash and no web: it reads the extract and writes one JSON file inside a work folder; code validates and writes | As `mem-settle` does; a background model cannot write on its own |
| C5 | An unconfirmed captured record is written in the project scope; kinds `lesson`, `pitfall`, `decision`; at most 5 candidates per run | A wrong record must not reach every project before someone confirmed it; a cap keeps the review queue short |
| C10 | Each candidate has a `reach`: `project` (this codebase) or `general` (how the agent plans, delegates, uses skills and plugins, verifies, reads the owner's intent). A `general` record is marked for promotion, and confirming it moves it to the global scope (`mem promote`) | The owner's goal is meta-learning (2026-11-21): a lesson about method must reach every project, not stay where it happened; the project scope is only where it waits |
| C6 | A captured record has origin `transcript` and is shown as `from transcript, unconfirmed` until it is corroborated (C11; `mem confirm` records a corroboration, and a second sighting counts as one); it is valid for 30 days | "Provisional" stays implicit in words agents already meet (`web, unconfirmed`, `mem confirm`); no new status, so no query that filters by status changes; an unconfirmed record expires by itself |
| C7 | The claims of the project's active memories are given to the model as "already recorded" | The main agent records too; an identical claim is already refused at writing |
| C8 | Haiku first; Sonnet only if the trial keeps too few | Cost; the trial decides |
| C9 | Phase A is offline: `mem-capture` writes candidates to a file and never to the store | Stage 9's adoption check comes before any hook |
| C11 | What the owner says, and a friction with the owner, are evidence and not truth. A record drawn from one comment or one friction is worded as what happened ("the owner rejected X, saying Y"), stays unconfirmed, and counts as established only when it is corroborated: the same lesson is seen again in another session, or independent evidence shows it (the owner said it and it then happened, a check confirms it). For an `owner_correction` the candidate also considers the other reading: the owner may have misunderstood, and the lesson is then to explain better or in a form adapted to the owner | The owner's ruling of 2026-11-22: the owner can be wrong, and a single friction does not say who misread whom |
| C12 | Corroboration is kept per scope. A `general` lesson seen in one project is established for that project at most, and stays unconfirmed as a general one until it is seen in a second project; the more a rule restricts the agent or the owner, the more sightings it needs | The owner's ruling of 2026-11-22: a rule that one project needed may not apply to the others |
| C13 | A claim states how often the thing was seen and under which condition ("refused on three merges in this repository", not "is always refused"), and reads as guidance the agent may set aside with a reason. A sighting that goes the other way is recorded as an exception, not as a refutation, so the rule can move to a middle point or become stricter | The owner's ruling of 2026-11-22: some frictions do not occur every time; a rigid rule cannot evolve |
| C14 | When a candidate is very doubtful or would cost much if wrong, the agent may ask the owner. The answer is one more piece of evidence that tilts the balance, as feedback or a preference, not proof (C11) | The owner's ruling of 2026-11-22 |
| C15 | The wording of a record carries its standing, beyond any tag: how sure it is, whether it may be temporary, which conditions are unknown, and how much it matters to follow it ("seen once; may only hold while X", "has held in three projects"). The sightings a lesson needs grow with what it costs if wrong: a grave or restrictive rule needs many, a mild and general one may need none | The owner's ruling of 2026-11-22: an agent reads prose, so prose is what tells it how firmly to apply a lesson, and a lesson that is not applied blindly can be refined |

## Phases

| Phase | Contents | Gate |
|---|---|---|
| A, trial | `capture.py` (extract, validate), `bin/mem-capture run --transcript ... --out ...`, a run over 10 past transcripts, the owner marks each candidate keep or drop | Adopt if at least 60% of the candidates are kept and no kept candidate duplicates an existing record; inconclusive below 15 candidates or 5 producing transcripts; else change the prompt or the model once, then stop. Figures go to ADR 0023 |
| B, wiring | Origin `transcript` and its tag; the `reach` of C10 stored on the record and promotion on confirmation; a curation category "from transcript, not confirmed"; `mem-capture run` writing through `mem remember`; an offset per session; launch from `PreCompact` and `SessionEnd` behind a plugin option `auto_capture` (off by default); a lock, a status file and a failure line as `mem-settle` has | A plan of its own, with a pre-mortem |

## Not in this design

Notes; a signal during a run (L5); graduation (L4): a periodic retrospective that reads the general lessons gathered across sessions with the usage metrics and proposes a change to a rule (a context file, a skill, an agent definition) for the owner to approve, because a pattern of behavior shows across sessions, not inside one.
