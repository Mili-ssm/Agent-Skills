# Memory learning loop: usage read, evidence and proposals (read-only)

**Conclusion.** In four days of use, 13 of 16 sessions searched the `memory` plugin, so recall is not where the counts show a gap. The gaps against the owner's goal are (1) no outcome metric says whether the agent repeats fewer mistakes, (2) lessons are written only when the main model remembers to, (3) nothing turns a lesson seen several times into a rule. § 4 proposes five steps, the metric first. The owner accepted the order on 2026-11-21 (ADR 0023, Review 2026-11-21).

**The goal** (owner, 2026-11-21): after each session, each compaction and during a run, the agent learns locally: it detects its failures, criticises itself with evidence, and its task performance and knowledge improve a little every day. Two constraints on the means: the most useful awareness in the least context, and the agent uses the plugin more and better. This extends requirements U4, U5 and U11 of [the design](../superpowers/specs/2026-11-17-memory-plugin-design.md) and stage 9 of [the plan](../superpowers/plans/2026-11-17-memory-plugin.md).

Labels: **observed** = counted from transcripts or logs; **measured** / **self-reported** / **prescribed** = how the cited source supports its claim; **proposed** = this study.

## 1. Usage read, 2026-11-17 to 2026-11-20

Observed on 2026-11-21 with `python3 docs/studies/scripts/memory_usage.py 2026-11-17 2026-11-20` ([the script](scripts/memory_usage.py); tool calls counted once per `tool_use` id); hook durations from the plugin's hook log. 16 interactive sessions, 5 projects.

| Measure | Value |
|---|---|
| Sessions with `mem search` | 13 of 16 |
| Sessions with `mem remember` | 11 of 16 |
| Sessions that edited files: searched before the first edit / only after / never | 10 / 2 / 0 of 12 |
| Days with a session that also had a `mem search` (not the kill criterion's day ratio, which is read from the plugin's logs at stage 4) | 4 of 4 |
| `mem search` : `mem show` calls | 149 : 120 |
| Memory agents dispatched | `memory-recorder` 12, `memory-curator` 8, `memory-synthesizer` 1, `memory-researcher` 1 |
| Writes to Claude Code's auto memory beside `mem` | 38 in 8 sessions |
| Compactions | 13; 12 summaries carry "not yet recorded" items, and all 12 were followed by `mem remember` or a `memory-recorder` dispatch before the next summary |
| Hook duration, p95 | `session-index` 91 ms at startup (one run of 742 ms, over the 0.5 s budget), 180 ms after a compaction; `session-end` 63 ms |

The stage 3 results said the `PreCompact` text "was only printed, never seen in a summary": it is now observed in 12 of 13 summaries.

## 2. What the hooks allow

From the [hooks reference](https://code.claude.com/docs/en/hooks), read 2026-11-21.

| Event | Fact |
|---|---|
| `PreCompact` | Receives `transcript_path` and `trigger`; its stdout becomes instructions for the summary (10,000 characters); only `command`, `http` and `mcp_tool` hooks, so no model runs inside it |
| `PostCompact` | Receives `compact_summary`; cannot change it. Runs after `SessionStart`, and what it prints reaches the model; the plugin uses it (L1, L2) |
| `SessionStart`, source `compact` | Adds context after a compaction. It never sees the owner's prompt; `UserPromptSubmit` does |
| `async: true`, `asyncRewake` | A command hook runs in the background; its output arrives on the next turn, or at once when `asyncRewake` exits 2 |
| `SessionEnd` | 1.5 s by default: long work needs a detached process (already done for `mem-auto` and `mem-settle`) |

The transcript file survives a compaction, so "before the compaction" is not a deadline for reading the whole conversation.

## 3. Evidence that constrains the design

| # | Finding | Support | Consequence |
|---|---|---|---|
| E1 | A model that reviews its own answer with no outside signal does not improve, and often gets worse | Measured, independent (ICLR 2024, 2023-era models) | Self-critique is recorded only when a signal backs it: an owner correction, a check that failed and then passed, a reviewer finding that was verified, a repeated tool error |
| E2 | Reflection after a failed attempt with feedback, and playbooks that evolve per task, report gains (Reflexion 91% pass@1 on HumanEval; ACE +10.6% on agent tasks) | Self-reported by each paper | The mechanism is worth a local trial; the figures do not transfer |
| E3 | Notes written from a summary carry more errors than notes written from the source | Measured in the owner's note pipeline | A capture process reads the transcript, never the compaction summary |
| E4 | Context files raised agent cost by over 20% with no significant change in task success | Measured, independent (arXiv 2602.11988) | No new always-on text; each injection is conditional and logged |
| E5 | A progress file plus git history lets a fresh context resume; agents marked work done that was not tested. The same harness lets agents change only a `passes` field of a JSON list, because models are "less likely to improperly alter JSON than Markdown" | Prescribed by Anthropic (no figures), with that failure reported | The agent writes the handoff in a fixed block; a hook checks it against the files |
| E6 | Revising a contradicted fact was the weakest memory skill in one benchmark; a chat user could plant memories that redirected later queries | Measured by the benchmark's and the attack's authors | Captured records start provisional, project scope only, with a source pointer |
| E7 | Products write memory in the turn (Claude Code auto memory, LangMem hot path) or in a separate pass (LangMem background, Letta Code "dreaming" after a number of steps or a compaction, Claude Managed Agents Dreams). No official page compares the two or gives a figure; only Dreams states its conflict rule (the latest value replaces a contradicted one) | Official docs, read 2026-11-21 | L3 follows an existing pattern, and its trial is the only measurement there will be |
| E8 | A signal matched on words fired on 9% (strictest setting) to 82% (loosest) of real briefs and showed no gain in delegated trials | Measured here (stage 6) | No per-prompt recall hook until a match on meaning exists |
| E9 | Stored experiences propagate their errors: an agent follows a retrieved experience closely, and "seemingly correct executions can provide limited or even misleading value"; later task results can label stored memories | Independent study (arXiv 2505.16067), abstract only, no figures | A quality gate at writing (provisional, with evidence), and M1 and M7 as the labels |
| E10 | Skill and workflow libraries report large gains (Agent Workflow Memory: 24.6% and 51.1% relative success on Mind2Web and WebArena; Voyager; Dynamic Cheatsheet) | Self-reported, abstracts only, benchmarks not comparable | Procedures are a candidate record kind after lessons; not proposed here |

## 4. Proposals

Order = what each later step needs. Status values: `proposed`, `deferred`, `accepted`, `done`, `dropped`.

| # | Proposal | Serves | Cost | Status (2026-11-21, after the owner's ruling) |
|---|---|---|---|---|
| L1 | **Outcome metrics first.** Extend `memory_usage.py` and log one line per compaction from a `PostCompact` hook (table below) | Tells whether any later step helps | No model | done ([plan](../superpowers/plans/2026-11-21-memory-handoff-and-compact-log.md)) |
| L2 | **Agent-written handoff, checked by a hook.** `PreCompact` asks the summary for a fixed block: task, state, next step, what is verified against what is only claimed, plan path. `PostCompact` reads it from `compact_summary` and checks that the plan file it names exists (comparing open tasks was dropped after the plan's pre-mortem; `git` is never run). `PostCompact` itself prints the mismatch lines (it runs after `SessionStart`, so `SessionStart` prints nothing new); it speaks only when the block is missing or names a plan file that does not exist | U4; replaces a deterministic plan detector, which the owner declined | No model; a prompt change, unmeasured, with a kill criterion | done ([plan](../superpowers/plans/2026-11-21-memory-handoff-and-compact-log.md)); kill criteria in ADR 0023, Review 2026-11-21 |
| L3 | **Evidence-anchored capture** (stage 9, narrowed by E1 and E3). A detached process started at `PreCompact` and `SessionEnd` reads the transcript since its last offset, keeps only candidates tied to a signal of E1, and writes provisional project memories of kind `lesson`, `pitfall` or `decision`, each with the session and position of its evidence. It receives the records the session already wrote, so it adds only what is missing | U5 without relying on the main model's attention | One small-model run per compaction or session, under a per-run budget, as `mem-auto` has | phase A done: the spike passed and the offline trial passed its gate on 2026-11-22 ([plan and results](../superpowers/plans/2026-11-21-memory-capture-trial.md), [design](../superpowers/specs/2026-11-21-memory-capture-design.md)); phase B: stage B1 (records) and stage B2 (background runs behind the option `auto_capture`, off by default) built on 2026-11-22 ([B1](../superpowers/plans/2026-11-22-memory-capture-records.md), [B2](../superpowers/plans/2026-11-22-memory-capture-background.md)); B3 and B4 not started |
| L4 | **Graduation and retrospective.** A periodic pass reads the general lessons gathered across sessions (capture design, C10) with the usage metrics and proposes a rule change for the owner to approve. A lesson observed again raises its count (`mem observe` exists); at a threshold the session index names it, and `mem promote` drafts a rule for the place that prevents it: a validator, a skill line, a context-file line. A graduated or unused lesson leaves the index | The step from knowing to behaving; keeps the index short (E4) | No model until the draft | accepted |
| L5 | **During a run**: nothing new now. Candidates once L1 has a baseline: a repeated-failure detector on `PostToolUse` that wakes the agent with the matching lesson | U11 | Unknown | deferred |

Intent and miscommunication (the owner's open question): L3 can capture "the agent misread the intent" as a lesson when the owner's correction is the signal, and a `decision` memory can carry "functional goal, hard" against "chosen means, soft". Whether that prevents the next misreading is unknown; M1 below is how to find out.

### Metrics for L1

| # | Metric | Shows | Source | Keep |
|---|---|---|---|---|
| M1 | Repeated corrections: owner corrections whose lesson was already recorded | Whether the agent learns; the outcome | L3's candidates matched against the store | yes, once L3 exists |
| M2 | Rediscovery: a web search or researcher dispatch on a topic the store covered, with no `mem search` before it | Missed recall that cost work | transcripts | yes |
| M3 | Searches followed by `mem show` of a returned record, and searches with nothing opened | Whether results are useful or noise | usage log | yes |
| M4 | Sessions that searched before the first edit | Recall at the right moment | transcripts | yes |
| M5 | "Not yet recorded" items in a summary against records written before the next compaction | Capture follow-through | `PostCompact` log, usage log | yes |
| M6 | Records superseded, refuted or forgotten within 14 days of writing | Wrong or worthless writes | curation log | yes |
| M7 | Provisional records kept at the next curation pass | Whether L3 earns its cost | curation log | with L3 |
| M8 | Characters injected by the session index per call (the script reads no other injection yet) | The context the plugin costs | hook and usage logs | yes |
| — | Raw counts of searches and writes; the day ratio after the kill read | Volume, not quality | — | no |

`PostCompact` log line: session, `trigger`, summary length, whether a marker line is present, which handoff fields are present, whether a plan is named, count of "not yet recorded" items, count of mismatch lines, duration.

## 5. Self-critique of this study's session

| What happened | Lesson |
|---|---|
| The first proposal was a deterministic plan detector; the owner's objection (wrong plan, unticked progress) is the failure E5 reports | Name the failure mode of a proposed means before proposing it |
| The owner asked for a session-start hook that reads the prompt; that event cannot see it | Check which event carries the data before discussing the hook |
| Three `memory-researcher` runs answered well from the store but their outside step found no source for 8 named systems; two `researcher` runs on those names then returned E7, E9 and E10 | For broad literature, pair it with `researcher` on the named gaps |
| The first read told the owner "all 13 summaries" from an ad-hoc run; a fresh-context review found the saved script counts 12, and that its window had grown to include the running session | Re-derive a figure from the saved script, on a closed window, before it enters a document or a memory |

## Limits

- Four days of data; 7 of the 16 sessions were in this repository building the plugin, so use is inflated. The kill read needs two weeks. The first read of this session reported "all 13 summaries"; the script counts 12.
- The command counts match `mem <command>` in Bash text: a command quoted inside a script or a message is counted too.
- One mention of "not yet recorded" is not one item: M5 is not measured yet.
- The figures of E2, E9 and E10 were read from abstracts or vendor pages, not checked against the full papers; Letta's server-side sleep-time page could not be read.
- No eval suite covers hooks: L2 and L3 ship only with kill criteria in ADR 0023.
