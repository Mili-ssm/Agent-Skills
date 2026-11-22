# 0023 A memory plugin makes notes and memories reachable from every repository

Status: accepted · Date: 2026-11-17

## Context

The owner keeps a private repository of Markdown notes (conclusions, lessons, summaries of sources, investigations) with a one-file search tool. On 2026-11-17 the owner said it "practically only works if I work from here" (translated): sessions in other repositories and every subagent do not use it, nothing learned in a work repository is kept in a searchable place, and web research is discarded with the session. The owner asked for a plugin that makes this memory available everywhere, serves as working memory, and syncs through a private git repository.

Evidence, measurements and the options considered are in the [design](../superpowers/specs/2026-11-17-memory-plugin-design.md). Assumptions: the owner is the only user (ADR 0008); `uv` is installed on the owner's machines; the product behaviors the design relies on were read in the product docs on 2026-11-17 (its evidence table says which were checked twice, which once, and which are still to be tried) and may change.

## Decision

Add an opt-in plugin, `memory`, beside `agent-skills` (ADR 0011). The owner decided on 2026-11-17, in two rounds; where the second round changed the first, only the result is stated:

- **Two kinds of record.** A *note* is generic and abstract. A *memory* is specific, comes from experience and carries doubt because it is not an established fact. Memories can be confirmed, refuted, merged and promoted to notes.
- **Two scopes.** The *global scope* holds notes, and memories that do not depend on one project, with no business names. The *project scope* is a hidden folder at each project's root, local by default and committed only when a project opts in.
- **The owner's note repository is not touched until the plugin is finished.** The plugin starts with its own copy of the search tool's code and its own store; which repository syncs the global scope (the note repository or another) is decided at the end.
- **The code is developed in this repository**, on a branch that is pushed, with a documentation branch.
- **Python first.** A move to Rust is decided later, with measured latencies.
- **The agent writes to the memory explicitly**; no hook writes for it, though one may remind it.
- **Hooks signal, they do not inject.** A hook that finds records related to the task prints counts in bands (strong, possible, tangential) and the titles of the best few, so the model decides what to open and writes its own search. No reference to a cached query by default; a per-call reference may be tried.
- **Curation is part of the plugin**: a check when a record is written, a review queue for duplicates and for similar records that are not linked, and commands to merge, supersede, promote and forget.
- **A first version reaches Claude Code on the owner's machines and its subagents**; cloud sessions and the Copilot and Codex ports (ADR 0015) are outside it.

Proposed with this record and not ruled on by the owner (the design lists them): a command plus one skill and no MCP server; reading the note repository as a read-only source during development; the signal bands calibrated on an evaluation set before the hook ships; pull automatic, commit and push explicit; Claude Code's own auto memory left as it is.

## Alternatives

| Option | Rejected because |
|---|---|
| Keep the rule in the owner's user-level file ("consult the note repository") | It is what exists: by the owner's account sessions elsewhere do not use the notes, and a subagent gets only its brief |
| Point Claude Code's auto memory at a synced folder (`autoMemoryDirectory`) | The docs do not say whether one folder serves every project; as read once in the docs, auto memory is kept per repository and is not loaded into subagents |
| An existing memory plugin that captures sessions through hooks into a database | Automatic capture is what the owner declined; the one such plugin read keeps its records in a database, not in Markdown under git |
| An MCP server | A process to keep running and a second interface; its gains (no Bash call, per-tool permissions) do not reach a subagent with a fixed tool list; revisit below |
| Hooks that inject the related records themselves | No source read measures it against task success; two 2026 preprints report the cost of injected memory and lower pass rates from injected skills. The owner chose a signal instead |
| Extending the note repository's own tool in place | The owner wants that repository untouched until the plugin is finished |
| Rust from the start | The record model and the hooks are still changing, which is when a rewrite costs most; this repository has no CI to build binaries. Measured on 2026-11-17: 630 ms per search in Python, enough to try the design |

## Consequences

- First command hooks, first `bin/` executable and first `userConfig` in this marketplace; `scripts/validate.py` and the ports do not cover the new plugin until extended.
- Existing installs do not change: the plugin is opt-in and adds nothing to `agent-skills` (G8).
- The plugin carries a copy of the search tool's code that will diverge from the original; the note repository adopts the plugin's version, or stays as it is, when the plugin is finished.
- The owner's user-level text about the note repository shrinks to what the plugin's skill does not say, so one instruction covers one task.
- Each session pays for a session index, each subagent for three lines, and a signal only when records match (caps in the design).
- The marketplace gains a plugin that is neither `agent-skills` nor a mod: on acceptance, ADR 0011's description of the marketplace and the Repo role row of `docs/requirements.md` are updated.
- Ships unmeasured; the kill criteria are in the [plan](../superpowers/plans/2026-11-17-memory-plugin.md).

## Revisit if

- A kill criterion of the plan fires.
- A subagent without the Bash tool needs to search the memory itself, or the command still prompts for permission in subagents after the allow rule is set: reconsider an MCP server.
- A hook's measured time stays over its budget after the engine keeps a search index on disk: reconsider Rust, for the hooks alone or for the engine.
- The owner wants the memory in cloud sessions, Copilot or Codex.
- Claude Code documents a way for a plugin to supply or sync auto memory.

## Review 2026-11-17

Accepted by the owner the same day, by asking for the branch to be merged and the plugin installed for a trial. Between the proposal and the merge the owner ruled further, and stages 1 to 3, 5, 5b and 6 were built; the decisions table of the [design](../superpowers/specs/2026-11-17-memory-plugin-design.md) (D1 to D23) is the current statement, and where it differs from the Decision above, it wins. The differences:

- The store is the default one, created on first use; the owner's note repository stays a research hub, and its notes are transferred later (D15, D23). Git is for pushing the default store to a remote the owner chooses.
- The standard search returns notes and memories; papers, documents and syntheses are an explicit, deeper search. Writing while working is a note or a memory; everything complex belongs to curation and to subagents (D21, D22).
- Syntheses were added: long documents written by a model over many notes (D17, D19).
- The signal hook was built and measured, showed no gain, and is not registered; what made agents consult the memory was a short start text that states its reason.
- Terms that must not reach the global scope are of two classes: hard ones block, soft ones make the agent ask the owner (D23).

Measured, with one or two runs per case on a Sonnet-class model, which the owner takes as a sufficient reference: routing 9 of 9, recall 8 of 8, delegated recall 9 of 9. No measurement shows that the plugin makes tasks come out better; the field research found none for comparable systems either. The kill criteria of the [plan](../superpowers/plans/2026-11-17-memory-plugin.md) are read after two weeks of use.


## Review 2026-11-21

The owner accepted the order of [the learning loop study](../studies/2026-11-21-memory-learning-loop.md): L1 outcome metrics and a `PostCompact` log line, L2 a handoff block written by the agent and checked by a hook, L3 capture anchored in evidence (stage 9, after a spike), L4 graduation of repeated lessons; L5, hooks during a run, is deferred. The owner's goal behind it: the agent learns locally after each session and compaction, with the least context.

- A deterministic "active plan and next open task" injection after a compaction was declined by the owner: it can name the wrong plan or read progress that was not ticked. L2 replaces it.
- The study's usage read (2026-11-17 to 2026-11-20, four days) is a preview, not the kill read of stage 4, which stays due around 2026-12-01.
- L2 changes the `PreCompact` text and adds a conditional line after a compaction. No eval suite covers hooks, so it ships unmeasured (N6) with these kill criteria, read from the `PostCompact` log at the kill read: fewer than half of the summaries carry the handoff block → reword once, then revert to the previous text; the conditional line fires after more than half of the compactions → the check is wrong, disable it; summaries stop carrying "not yet recorded" items (12 of 13 before the change) → revert.
- Earlier reads, added after the plan's pre-mortem: after the first 5 compactions, no parsed block while the log's `marker` is true → fix the parser, do not reword the text; none of the first 5 summaries carries "not yet recorded" → revert at once; the owner or the agent finds a shown line false → disable that rule; the `post-compact` hook's p90 is over 500 ms → revisit.
- L3 is adopted only by stage 9's own check: most provisional records kept at the next curation pass.

## Review 2026-11-22

The capture trial (learning loop L3, phase A; [its plan and results](../superpowers/plans/2026-11-21-memory-capture-trial.md)) passed its gate: an offline `mem-capture run` proposed 47 candidates from 10 past transcripts of 5 projects for 0.196 USD on Haiku, validation dropped none, and the owner kept 38 (81%; 88% of the 26 about the agent's own method, 71% of the 21 about a project); the 9 not kept were 5 duplicates and 4 that were not lessons. Phase B (writing records, hooks) gets a plan of its own.

The owner's rulings while marking, recorded as C11 to C18 of [the capture design](../superpowers/specs/2026-11-21-memory-capture-design.md): what the owner says is evidence, not truth; a lesson is established by corroboration, kept per scope, and the more it restricts the more sightings it needs; its wording carries its certainty, its possible temporariness and its weight, and reads as a suggestion or a recommendation; a project decision or a technical note is not a lesson; a lesson corroborated across projects goes to a triage; an established rule lives in the memory store and moves to a skill, an agent definition or the instructions only if it is not followed there.

Limits: the marks are not independent of the agent that presented the candidates; no claim but one was checked against code; 8 of 10 sessions were read only at their end.

### Stage B1, the same day

Stage B1 of the capture design is built ([plan and results](../superpowers/plans/2026-11-22-memory-capture-records.md)): a memory may carry the origin `transcript`, a `reach` and a `weight`; whether it is established is derived from the number of distinct sessions in its sources, never from its `observed` count, so that a re-read of one session, a curation pass or a merge cannot establish it; `mem-capture run --write` records candidates in the project scope through `mem remember` and adds a sighting to a lesson the project already holds. Nothing runs by itself yet. The first real write recorded 11 project memories from two sessions of this repository; a second run of one session changed no existing record, though it added one record the first run had not chosen.

The texts given to models changed without an eval suite (N6): the capture brief, one sentence in the `memory` skill, one in the `memory-curation` skill and one in the `memory-curator` agent. Kill criteria are in the plan; the one already read (the model still returned its ceiling of five in 6 of 10 runs) led to the single revision it allows.

Open after this stage: a lesson said again in other words is still recorded twice; a `light` lesson is established by one session, which includes lessons drawn from one comment of the owner (the owner confirmed on 2026-11-22 that this is intended). The owner marked the first three matches the model made as correct.

### Stage B2, the same day

Stage B2 is built ([plan and results](../superpowers/plans/2026-11-22-memory-capture-background.md)): with the plugin option `auto_capture` on, the `PreCompact` and `SessionEnd` hooks start `mem-capture auto` detached; it reads the session's transcript forward from a saved offset in windows and writes through `run --write` (capture design, C22 to C27). The option is off by default and no released version carries it yet, so nothing runs in the owner's sessions. Four triggers on a private copy, the hooks run by hand with the real model: the hooks returned in under a second, each run ended by itself, the second trigger of a session read only its new lines, and a long session was read in full windows at 0.05 to 0.08 USD each (shorter windows about 0.03). Not exercised: a hook fired by the harness itself, and the default 300 s wait.

Unmeasured: whether the records are worth keeping (16 new records from four triggers on two past sessions, none judged by the owner), and how many say again what the session recorded itself. Kill criteria once the option is on, read from `capture/log.jsonl` and the owner's marks after two weeks: more than 1 in 5 background records repeats or rewords one the session wrote itself; more than 5 new records per project per active day; a failure line naming an import or type error; a write in a project without a memory folder, or a capture process alive after 60 minutes (a run may wait 300 s, then up to 900 s for the lock, then read three windows of up to 600 s each). Any of them turns the option off until the cause is fixed.

### Stage B3, the same day

Stage B3 is built ([plan and results](../superpowers/plans/2026-11-22-memory-capture-corroboration.md); capture design, C28 to C39): a background pass, `mem-corroborate`, matches lessons by meaning and gives each general lesson one global record; that record is in quarantine, hidden from readers, until it is seen in two projects or the owner confirms it; a lesson that leaves quarantine waits for triage; a session left open is captured at a later session start. The owner chose the write-then-review order, the small-model matching and the quarantine.

Research the owner asked for changed the method (C39). Our own audit of 2026-11-19 had a Haiku judge agree with itself on 6 of the verdicts it flagged in two passes, so one session does not decide a merge: a first session proposes and a second verifies each group. The systems read ([Mem0](https://arxiv.org/html/2504.19413v1), [A-MEM](https://arxiv.org/html/2502.12110), [LangMem](https://langchain-ai.github.io/langmem/reference/memory/), [Zep](https://arxiv.org/html/2501.13956), [ACE](https://arxiv.org/html/2510.04618v3)) let a model decide after a cheap recall of candidates and publish no precision of that decision. Memory rewritten at each consolidation loses content (ACE's "context collapse"; [arXiv 2605.12978](https://arxiv.org/abs/2605.12978)), so a record is reworded once. Adding every experience hurts and a write gate helps ([arXiv 2505.16067](https://arxiv.org/html/2505.16067v2), authors' figures). No system read holds a new lesson back until it is corroborated ([ExpeL](https://arxiv.org/html/2308.10144) starts a counter at once), so the quarantine has no published baseline. The reports came from a small-model researcher; several figures are the authors' own and some papers were read as abstracts.

Gate, on a private copy of the real records (36 lessons of origin `transcript`: 15 global, 21 of one project; 3 projects registered):

| Measure | Result |
|---|---|
| Dry runs with a usable answer | 6 of 7. One run used the reading tool's line numbers as ids; code refused all 15 groups and planned nothing. The proposal brief gained one sentence; 3 of 3 after it |
| Groups proposed | The same 15 in each of the 6 runs: 13 of one lesson, 2 pairs |
| The two transcript wordings of the turn-limit lesson | Joined in all 6 |
| Groups applied per run | 12, 12, 14, 14, 14, 15; 12 groups were applied in each of the last four runs |
| Refusals by the verifying session | All for an unfaithful rewording, a different group each run; none for "not the same" or "not general" |
| The owner's judgment of the 15 | 15 accepted; a rewording softer than the original is intended, and strength is added at triage after more confirmations |

The dry runs showed two defects no test had: a group that keeps a global record's wording was refused for a rewording that is never used, and one bad rewording kept a lesson from being proposed again. Both are fixed and tested.

Limits: one project holds all the project lessons, so matching across projects was exercised only between that project and the global records; the 15 groups were shown by the agent that built the pass. After the release the reviewed groups were applied on the real store in two passes; the first read 21 of 36 lessons because the background commands did not find the global memories folder from the store alone, a defect present in the capture since 0.3.0 and fixed in 0.4.1 ([results](../superpowers/plans/2026-11-22-memory-capture-corroboration.md#results)). No pass with real model sessions has run on the real store yet. The 15 global lessons recovered from the trial were confirmed with `--by-owner` on the real store, as the owner agreed, so the new rule does not hide them.

The texts given to models changed without an eval suite (N6): the proposal and verification briefs of the pass (new), three sentences of the capture brief (lines starting `g:`), one sentence each in the `memory-curation` skill and the `memory-curator` agent. Kill criteria, read from `corroborate/log.jsonl`, `capture/log.jsonl` and the owner's triage after two weeks of use:

- The owner rejects more than 1 in 5 lessons at triage, or judges one applied group to hold two lessons: stop the pass and reread the briefs.
- More than 1 pass in 5 ends with every group dropped, or the same lessons are written or refused in two passes in a row.
- A global record's body holds text of a transcript, or a project name or path appears in `log.jsonl` or in the session start text.
- The pass and the sweep together cost more than 1 USD a day for a week.
- After the release, a global record of origin `transcript` is in quarantine with no end date.
- The capture sets `same_as` to a `g:` record for a lesson the owner judges only related: revert the capture brief's sentence.


### Stage B4: loaded rules, the same day

Stage B4 is built on the branch `feat/memory-loaded-rules`, not merged and not released ([plan and gate](../superpowers/plans/2026-11-22-memory-loaded-rules.md); capture design, C46 to C48, C52 to C55): established lessons load at session start as short rules, built by code from the records, followed by one line that counts what did not fit by topic. The first release is the small one (C54): a lesson loads only with a short form that the owner read; a lesson has three load states (C55). Reminders were built and parked on a branch (C51). The automatic writing of short forms (C52) and the usefulness of a loaded lesson (C49) have no plan yet.

Measurement (C53, [results](../superpowers/plans/2026-11-22-memory-loaded-rules-and-reminders.md#measurement-loaded-rules-are-followed-2026-11-22)): one small task, three runs a condition, a real model, the rules printed by a throwaway hook and not by the plugin. No rules: 0 of 3; three rules: 3 of 3; the same three among twelve unrelated ones: 3 of 3, at about 7% more cost than with no rules. Not measured then: a rule that conflicts with other instructions, a long session, the owner's own instruction files beside the rules.

Gate, on a private copy of the real global lessons:

| Measure | Result |
|---|---|
| Short forms proposed by the small model | 15 asked, 13 kept, 2 dropped for passing 120 characters (they are proposed again by the next dry run); 0.004 USD. The 13 keep the hedges of their claims (the author's reading; the owner's reading is pending) |
| Rules loaded on the copy | 6; the real hook printed 1692 characters (a median of 644 over 63 session starts in the owner's hook log before). Thirteen of the 15 lessons tied on every order key, so most of the six were the first by handle: the reason for the index-only state (C55) |
| Runs with a real model, five general rules loaded, a task with an ambiguous term | Without rules the model stated its reading in 2 of 3 runs, with rules in 2 of 3, with the owner's instruction file beside them in 0 of 1. No reply announced a rule it did not follow and none went against the instruction file. No effect measurable on this task, whose base rate is high; no harm |

The first batch of runs was void: with no store option the hook switches to the default store, which the test's temporary folders had created empty.

The brief that has the small model write the short form and the topic ships unmeasured beyond that one batch of 15 (N6), as do the rules beside the owner's own instruction files (one run). Kill criteria:

- In a review of the proposals, the owner rewords more than 1 in 5 short forms because they are stronger than their claims: the brief is not good enough; do not build the automatic path of C52 on it.
- In real runs no loaded rule that bears on the task is followed, or one that contradicts the owner's instruction file is followed: stop before release.
- After release, the hook's `ms` at the 99th percentile in `hooks/log.jsonl` is over 1500 (the slowest run seen before was 742): build the block outside the hook.
- After two weeks, the owner turned off or forgot more than two loaded rules, or the same lesson was captured again in a session where it was loaded: revisit the order, the limit of six, or the wording.

State at the end of 2026-11-22: merged into `dev` (pull request 161), not released. The owner read ten of the fifteen proposed short forms and set all fifteen to load; they are applied on the owner's store and take effect once the release is installed. Text loaded for the model says "the user" (C56).

Before the release, a prompt review changed the loaded wording (C57): the block reads as lessons to apply with judgment, a confirmed lesson ends with `(the user vouched for it)`, the index line says when to fetch a group, and the brief for a short form says what to drop first. The header was measured again and held (3 of 3 and 3 of 3; [results](../superpowers/plans/2026-11-22-memory-loaded-rules-and-reminders.md#measurement-loaded-rules-are-followed-2026-11-22)). Unmeasured and shipped with these kill criteria: the new brief (check: three dry runs on a private copy, no short form over 120 characters and no hedge lost); the curation bullet (check: one curator run on a private store that rewords an over-strong rule in one command). The plugin option `loaded_rules` switches the feature off as a whole. Text that the plugin's skills, agents and messages show a model still says "the owner" in about twenty places; changing it waits for a plan with an eval, since some of it sits in transcript labels and schema values.

The new brief for a short form, measured the same day on a private copy of the 15 lessons with their short forms removed, three dry runs with the real small model: 15 of 15 valid in each run (13 of 15 with the first brief), lengths from 97 to 116 characters, no "owner" in any, and by a word match the hedge of the claim missing in 1 of 45 short forms. Cost 0.005 to 0.009 USD a run. Limit: the hedge check is a word match, not a reading.

The capture brief gained the signal `owner_request_paid_off` (C58). Tried the same day on the last part of the session in which the owner asked for a final review of prompts and processes before the release, two runs with the small model, nothing written: both runs kept a lesson with that signal that says to consider such a review without being asked; one of the two overstated what the review found ("six high-severity issues" where it found nine items, one of them high). Cost 0.014 to 0.015 USD a run. Unmeasured: whether the signal fires on requests that showed nothing. Kill criterion: more than one in five lessons with this signal, read at curation, rests on a request that showed nothing: tighten the brief or drop the signal.

Released as memory 0.5.0 on 2026-11-22.
