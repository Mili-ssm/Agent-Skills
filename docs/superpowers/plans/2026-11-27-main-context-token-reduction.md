# Main-context token reduction: call economy, reports, briefs, reviewer cadence

**Status** — Planned 2026-11-27 on `dev` at `3b923dd`; executing on `feat/main-context-budget` since 2026-11-27. Stage 5 (Codex) is done first on its own branch `fix/codex-fork-turns` (commit `3574c14`, port-only, no eval), and `feat/main-context-budget` starts from it. Open boxes are pending work; tick a box when its check passes.

**Owner decisions, 2026-11-27** — D1 yes, for plan-loop fix rounds only. D2 yes, a measured pilot. D3: text only, no global switch (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` also removes background Bash); in Codex, wait with `wait_agent`.

**Pre-mortem amendments, 2026-11-27** (Opus `pre-mortem`; each verified at the cited line before being adopted):

| # | Amendment | Applies to |
|---|---|---|
| A1 | Stage 5 is unconditional and ships first (the fork is confirmed below) | stage 5 |
| A2 | `CODEX_REWRITES` in `scripts/port.py` anchors on exact source text, and `port.py` fails when an anchor is gone. Keep "(in the background while you keep working)", "Run it in the background with the checks," and "A worker sees none of this conversation," word for word, or change the rewrite in the same commit; run `python3 scripts/port.py --check` before any eval | stages 2–4 |
| A3 | The stage 4 policy text itself says that a row's own threshold wins over the general rule, so the model does not read a contradiction with the summarizer, check-runner and implementer rows | stage 4 |
| A4 | A low line is `<where> — <doubt>` worded as a doubt ("may", "I think"), and `hedged.md` is extended to judge low lines too, recorded as a grader change | stage 3 |
| A5 | `offload-ui-verifier-with-policy` and `-with-hook` are left out of the stage 1 and stage 3 runs: they fail in the sandbox for an environment reason (backlog 3g) | stages 1, 3 |
| A6 | When a case drops after the stage 2–4 run, revert stage 4 first and rerun only that case; at most two such bisect reruns | stage 3 measure |
| A7 | Briefs to the built-in `Explore` (Codex `explorer`, Copilot `explore`) keep a length, because those agents have no report format of ours on the Codex and Copilot side | stage 2 |
| A8 | The report-budget fragment says a brief may lower the cap but not raise it, except that a report path named in the brief receives the full report | stage 1 |
| A9 | `severities()` in `usage_reviewer.py` ends the Low block at any `Word:` line, so a low line such as `Makefile:3 — …` is lost: require no `.` or digit before the colon, and add the K of `Left out: K low findings` to the low count | stage 0 gaps |
| A10 | Stop and ask the owner when eval spend passes 12 USD before the stage 3 measure | budget |

**Goal** — The main conversation orchestrates and keeps knowledge in sync with as few calls and tokens as the work allows, without losing findings or causing rework. Done means: the edits of stages 1 to 6 are merged to `dev` with their eval records in an ADR, and the after-read (stage 7) is scheduled with its kill criteria.

**Owner rulings, 2026-11-27** — Approved: fewer main calls, a report budget, briefs by reference. Requested, with the design left to the planning session: a rethink of `skeptical-reviewer`, and research on efficient offload (how much delegation is too much or too little). The context ceiling is not to be lowered. This reopens G11 and touches G19 of the 2026-11-23 usage study (both declined on 2026-11-25) on new evidence: a Codex user reported fast quota consumption, and reports and briefs did not shrink in a second week.

## Where to resume

1. Read this file, then `git status` and `git log --oneline dev..feat/main-context-budget` (the branch may not exist yet).
2. Work the first open box. Stages 1 to 4 edit different lines of the same files, so run them in order; stage 0 boxes can run beside them.
3. The repository `CLAUDE.md` holds the commands, generated files, eval protocol and ADR format. This plan repeats none of them.
4. Ask the owner the open decisions below before the boxes they block: D1 and D3 before the eval run of stage 4, D2 before stage 8.

## Why (measured, 7 days to 2026-11-27, 52 main sessions)

Figures in dollars and the sources read are in the owner's local study `.local/studies/2026-11-27-main-context-token-reduction.md` (unpublished); a session without that file works from these tables. Reproduce with `python3 docs/studies/scripts/<script> <session-id-to-exclude> 7` for `usage_main_context.py`, `usage_main_calls.py` and `usage_dispatch_value.py`, and `python3 docs/studies/scripts/usage_reviewer.py 7`. The windows go by file modification time, so counts drift by a few percent between runs.

### The main session pays per call

| Fact | Value | Script |
|---|---|---|
| Main session share of spend | 73%; over half of it is re-reading the context | `usage_main_context.py` |
| Main calls, and context per call | 6,824 calls; median 248k tokens | same |
| Calls that run one shell command | 60.0% | `usage_main_calls.py` |
| Calls inside runs of 3+ consecutive single-shell calls | 44% (537 runs, 3,008 calls; median run 4 and p90 10, ad hoc) | same |
| Tool-using calls with two or more tools | 11.3% | same |
| Result of those single shell commands, median | 334 characters (python) to 1,436 (file reads), by command class | ad hoc breakdown of those runs, recorded in the study; stage 0 adds it to the script |
| Text-only calls made while a dispatch was pending | 1,000 (15% of main calls); in 440 dispatches the report arrived right after one such call | `usage_dispatch_value.py`, section B |

### Delegation pays, with two exceptions

| Fact | Value | Script |
|---|---|---|
| Median dispatch: tool calls inside · tokens kept out (upper bound) · tokens it adds to the main | 13 · 19.5k · 2.6k to 3.0k (ratio 6 to 7; the script counts one of the two completion texts, see stage 0) | `usage_dispatch_value.py` |
| `check-runner` | ratio 1.3, the lowest of the frequent workers | same |
| Reports after which the main opens a reported file itself within 15 calls | 72%, in 2.7 calls on average (`skeptical-reviewer` 86%, 3.5 calls; `implementer` 71%, 2.5 calls) | same; matches file paths on a path boundary |
| Dispatches redone within 12 calls | `implementer` 27.3%, `skeptical-reviewer` 15.4% | same, rough |
| Follow-up messages to finished workers | 5.6% of dispatches | same |
| Share of the context's carry cost: reports · briefs · harness notices (launch and completion text) | 9.4% · 7.0% · 5.8% | `usage_main_context.py` |

### Break-even, in main calls (estimate)

One main call is the unit: it re-reads the whole context and writes its output. About 2k tokens that enter the context cost one call over the rest of the segment (the study gives both rates in dollars). At the median context of 248k tokens:

| Item | Cost in main calls | How |
|---|---|---|
| A dispatch, main side | about 5 | launch call 1 + the turn its notification starts 1 + a text-only call while waiting 0.5 to 1 + 2.6k tokens of brief, report and notices 1.3 + the brief written as output 0.5 |
| Opening the reported files afterwards | 2.7 more (reviewer 3.5) | measured calls |
| The worker's own run | Haiku about 0.4 · Sonnet about 4.5 · Opus `pre-mortem` about 11 | median run cost over the average cost of a main call |
| Median dispatch, had the main done it inline | about 23 | 13 tool calls + 19.5k tokens of results at 2k per call |

So delegation pays from about 8 calls of inline work for a Haiku worker (5 + 2.7 + 0.4), about 6 when the report needs no re-reading, and about 12 for a Sonnet worker (5 + 2.7 + 4.5). Below that, one batched call is cheaper. The saving scales with the context a call re-reads: about 0.4 times at 100k tokens and twice at 500k.

### `skeptical-reviewer`

| Fact | Value |
|---|---|
| Runs | 410, the most frequent dispatch (6.0 per 100 main calls); its brief, report and notices cost the main about 3.5 times its own run (study) |
| Dispatches by trigger (share of the 453 briefs `usage_reviewer.py` finds; guessed from brief words; a brief can match two) | final answer or ad hoc 43% · plan task 25% · round 2 20% · push or pull request 12% · process 4% |
| Reports with zero findings · with a medium or high finding · with a high finding | 1% · 78% · 15% (self-rated, not verified) |
| Finding rows | 1,010 low · 776 medium · 97 high; `routing.md` defers low ones |
| Report text, median | 3,608 characters, 546 words (6.6 characters per word), against a cap of 40 lines; 4,750 characters as it lands in the main, with the hand-back frame |

### Baseline sizes, median characters as they land in the main

Source: the agents table of `usage_main_context.py`. A landed report includes the hand-back frame, about 1,100 characters (measured on the reviewer only: 4,750 landed against 3,608 of text). Targets are the new cap at 6.6 characters per word plus that frame.

| Agent | Brief | Report | Stated cap | Target report | Target brief |
|---|---|---|---|---|---|
| `skeptical-reviewer` | 1,890 | 4,750 | 40 lines | ≤ 2,900 | ≤ 1,000 |
| `implementer` | 3,573 | 2,976 | 25 lines | ≤ 2,400 | ≤ 2,400 |
| `pre-mortem` | 2,679 | 9,458 | 70 lines | ≤ 7,000 | no target |
| `Explore` | 2,215 | 8,592 | 30 lines | ≤ 5,100 | no target |
| `researcher` | 1,370 | 6,689 | 300 words | ≤ 3,100 | no target |

Neither kind of cap holds today: 40 lines came to 546 words, and the 300-word cap is exceeded about threefold (partly because briefs ask for more).

### What the literature adds

| Finding | Source | Evidence |
|---|---|---|
| Coordination gained 80.9% on a parallelizable benchmark and lost 39% to 70% on a sequential one | [arXiv 2512.08296](https://arxiv.org/abs/2512.08296) | measured, 180 configurations |
| Summaries that dropped "subtle facts" lowered success on hard tasks (39.7 to 30.2) | [ACON, arXiv 2510.00615](https://arxiv.org/html/2510.00615v3) | measured |
| Trimming old observations matched LLM summaries at about half the cost | [arXiv 2508.21433](https://arxiv.org/html/2508.21433v2) | measured |
| Compressing tool output cut tokens 38.4% and raised billed cost 6.8%, through extra retrieval turns | [arXiv 2607.12161](https://arxiv.org/abs/2607.12161) | one independent study, abstract only |
| Step repetition 17.1% and missing or wrong verification 13.5% of multi-agent failures | [MAST, arXiv 2503.13657](https://arxiv.org/html/2503.13657v2) | measured, 200 traces |
| Strict output formats lower reasoning | [arXiv 2408.02442](https://arxiv.org/abs/2408.02442) | abstract only |

Reading: delegate what is independent, read-heavy and compressible; keep sequential or state-sharing work inline, in fewer and larger calls; keep specifics verbatim in a report; judge every change by calls and cost, not by tokens removed.

## Decisions already taken

| Decision | Reason |
|---|---|
| Calls are the first target, tokens the second | 60% of main calls are single shell commands; a dispatch already keeps over six times more out than it adds |
| Caps are stated in words, one unit, derived from a target in characters at 6.6 characters per word | A line cap did not bound length |
| Only a worker's final message is constrained, never its working steps | Strict formats lower reasoning |
| A report keeps paths, numbers and quotes verbatim; only narrative is cut | Measured losses came from dropped specifics |
| No new notation (TOON, JSON, telegraphic prose) | Gains inside noise or near 8%; terse output raised tokens on a third of tasks (secondary source) |
| No size floor for reviews | The owner removed the floor on 2026-11-04 (ADR 0017 Review 2026-11-12), and reviews come back empty 1% of the time |
| The reviewer stays, on Haiku, with fewer and cheaper dispatches | Its cost is main-side; a model revising its own answer without outside feedback did not improve in one study (`mem` note `intrinsic-self-correction-does-not-improve-llm-reasoning`) |
| Reviews are not batched to the end of a plan | A late finding costs rework across tasks |
| The eight specialists of the routing row (`architect`, `security-reviewer`, `performance-analyst`, `qa-engineer`, `doc-curator`, `ux-reviewer`, `fact-checker`, `prompt-engineer`) and `consistency-auditor` keep their caps | About 30 runs a week together, and `routing.md` requires relaying every finding |
| No agent `description` changes | Each needs its own commit and eval (N6); B1b tracks the reviewer's |
| Not planned: tool-output filters, delegating long docs writes, Code Mode | A filter raised billed cost in the one independent study; G15 was declined; Code Mode is experimental and off by default |
| Out of scope: a lower context ceiling, a smaller fixed load | Owner, 2026-11-27; the fixed load is P5 and needs an ADR against 0021 |

## Open owner decisions

| ID | Question | Recommendation | Blocks |
|---|---|---|---|
| D1 | May the worker that fixes a review's findings verify them first and report the ones that do not hold, instead of the main opening every cited file? | Yes for plan-loop fix rounds, with the main still ruling on refuted findings; the main opens reported files after 86% of reviews | Stage 3, the box that starts "If the owner answers D1" (no other box waits for it) |
| D3 | When the main has nothing to do until a worker returns, may it wait for the worker instead of dispatching in the background? Today the policy says background, and 1,000 text-only calls happen while a dispatch is pending | Yes, if stage 0 finds a per-dispatch way to wait; a global switch (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`) also stops background shell commands, so try it only as a short trial | Stage 4, last box |
| D2 | Pilot a workflow that chains implement, review and fix for one plan task without the main between steps? Claude Code only; the owner starts it with a command | Yes, as a measured pilot on one small plan | Stage 8 |

## Stage 0: baseline and tools

- [x] `usage_reviewer.py` (reviewer triggers, severity, report size; reads the old and the new report format), `usage_main_calls.py` (call census, lookup runs, inline writes, parallelism) and `usage_dispatch_value.py` (value per dispatch, re-opening, redo, follow-ups, timing). Check: each runs on 7 days; `uvx ruff@0.17.6 check`, `uvx ruff@0.17.6 format --check` and `uvx basedpyright@1.40.2 --warnings` print no finding (done 2026-11-27).
- [x] The working tree on `dev` held uncommitted owner edits to `CLAUDE.md` and `README.md` on 2026-11-27, and `scripts/port.py` rewrites the generated block of `README.md`. Ask the owner to commit or stash them first; do neither yourself. Then branch `feat/main-context-budget` from `dev`. Check: `git status --short` shows neither file before the first run of `port.py` (done 2026-11-27: the edits were committed in `d4b35cc`).
- [x] **Codex spawn mode, first.** Done 2026-11-27 from the owner's local rollouts, see "Codex findings". An open Codex issue ([#20077](https://github.com/openai/codex/issues/20077), not verified on a primary page) reports that a spawn without `fork_turns` forks the parent's whole history and then ignores the role's model and effort. The port names neither `fork_turns` nor `spawn_agent`. In a Codex session with the port installed, dispatch `skeptical-reviewer` once and read the rollout: the role's model and effort, the tokens of its first request, whether `AGENTS.md` loaded. Check: the three answers are written under "Codex findings"; if the history is forked, stage 5 applies. Blocked without a Codex installation: ask the owner for a rollout of that user.
- [ ] Extend `usage_dispatch_value.py` with: the share of `implementer` reports that open with `BLOCKED` or stop for missing input; the share of runs that end within two turns of the agent's turn cap; per agent, the median characters and words of the report text (the hand-back message without its frame); reviewer dispatches per 100 main calls. Extend `usage_main_calls.py` with the length percentiles of the single-shell runs and their calls by command class. Check: the figures are added to the baseline column of stage 7, and the scripts stay clean under Ruff and basedpyright.
- [ ] Known gaps of the scripts, parked after their second review on 2026-11-27 (no third round): fix them before the after-read and rerun the baseline. In `usage_dispatch_value.py`: the hand-back message and the completion notification of one dispatch are two texts that both enter the main context, and the script adds only the first (about 300 tokens missing per dispatch; when the notification comes first, the report text is taken from it); the path match has no end boundary (`foo.md` matches `foo.mdx`); dispatches that never reported are left out of the waiting count. In `usage_main_calls.py`: a notification repeated across two calls counts twice (at most 54 cases); lookup runs still include some writes (other `mem` write verbs, shell redirects to a file, `git -C <dir> commit`; about 8% of the calls in runs of 3+). Check: each gap has a test line in the pull request, and the tables of "Why" are updated if a figure moves by more than a tenth.
- [x] Waiting for a worker. Find in the Claude Code docs and in one trace whether the main can wait for a single dispatch (a parameter of the dispatch tool, a `background` field of the agent definition) rather than receive a later notification, and what the Codex port does (its docs say the main thread waits). Check: the answer and its source are written in "Results"; it decides how D3 is put to the owner (done 2026-11-27, see "Results").

## Stage 1: report budget

- [ ] New fragment `shared/fragments/report-budget.md` with one placeholder, rendered into the Output or Report section of the agents below, replacing each file's own cap sentence and the repeated clause "because it lands in the main conversation's context". Draft:

  ```markdown
  Your final message is all the caller receives, and the main conversation re-reads it on every later turn, so keep it within {{cap}}:
  - Open with the result in one or two lines, then what the caller must act on.
  - Keep every path, number and quote exact; cut the narrative, the restated brief and the account of your steps.
  - When something does not fit, end with `Left out: <what>`, because the caller can ask you for it.
  - A length or format the brief states replaces this one.
  ```

  | Agent | Now | New `cap` |
  |---|---|---|
  | `skeptical-reviewer` | 40 lines | 270 words |
  | `implementer` | 25 lines | 200 words |
  | `fixer` | 25 lines | 200 words |
  | `check-runner` | 10 rows | 200 words; keep the 10-row limit |
  | `ui-verifier` | 30 lines | 300 words |
  | `pre-mortem` | 70 lines | 900 words |
  | `summarizer`, `researcher` | 250 words (60 and 150 lines for outline and extract) · 300 words | unchanged; a verbatim extract is exempt |
  | `memory-curator`, `memory-synthesizer` | none · 20 lines | 300 words · 150 words |
  | `memory-recorder`, `memory-researcher`, `memory-status-checker` | 200 · 250 · 350 words | unchanged |

  Memory agents title the section `## Report`. `implementer` keeps its rule that a report path named in the brief receives the full report. The `researcher` cap is stated in its agent file and in the `web-research` skill: keep both equal.
  For `skeptical-reviewer` the cap covers the whole message; stage 3 says what gives way when it does not fit.
  Check: `python3 -m promptkit.fragments --check` from `scripts/` passes; `grep -rln "lands in the main conversation" plugins/*/agents` no longer lists `skeptical-reviewer.md` or `pre-mortem.md` (the six other files it lists today keep the clause); each agent of the table has one `report-budget` block.
- [ ] `user-agents/Explore.md` takes no markers (`shared/fragments/README.md`) and `verbatim-in` cannot match a filled placeholder: write the fragment text by hand with a cap of 600 words in place of "≤ 30 lines", and list this unmarked copy in `shared/fragments/README.md`. Check: `python3 scripts/validate.py` passes.
- [ ] `Left out:` relies on continuing a finished worker (`SendMessage` in Claude Code). Find the Codex equivalent in the Codex docs or in a rollout; without one, `scripts/port.py` drops that bullet for Codex. Check: the generated Codex agent files show the chosen text, and the evidence is named in the pull request.
- [ ] Measure. Run the workers' `offload-*` cases (Eval protocol). For size, run one fixed brief on both sides (`dev` in a worktree, this branch), 3 runs each: `skeptical-reviewer` on the scaffold of `offload-skeptical-reviewer-quality`; `Explore` with "Which files must change when `user-config/offload-policy.md` changes, and what checks them? Answer with `path:line`." One run each side for `pre-mortem` on this plan. Check: the median characters of the report text on the branch are at or under the cap times 6.6, or at least 25% under the `dev` side (for `pre-mortem`, the single run), and no case drops 2 or more of 6; record the figures in "Results" below.

## Stage 2: brief by reference

- [ ] Replace the six-part list in `user-config/offload-policy.md` and in `shared/fragments/six-part-brief.md` (rename the fragment to `worker-brief`; its only marker is in `plugins/agent-skills/skills/prompt-engineering/references/skills-and-agents.md`; render after renaming) with:

  ```markdown
  A worker sees none of this conversation, so its brief carries what only this conversation knows:

  1. **Goal** and acceptance criteria it can check itself: one outcome per brief.
  2. **Scope**: the paths it owns, and what it must not touch.
  3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
  4. **Checks**: the commands that prove the result.

  Name a file the worker can open (a committed plan task, a spec, a commit range) instead of restating it, and write out only what exists nowhere but here. Every worker already has its stop rule and its report format: state one only to change it.
  ```

  Keep the paragraph that follows ("State the what, the limits and the check…"). A worker in an isolated worktree cannot open an uncommitted file of the main checkout, hence "committed".
  Check: `grep -rn "six-part\|six parts" plugins user-config shared scripts README.md docs/ports.md` shows only ADR history and generated files that `port.py` then rewrites.
- [ ] `plugins/agent-skills/commands/offload.md` tells every brief to carry a stop rule, a format and a max length: align it with the text above, or briefs will keep restating the old caps. Check: the same grep, plus `grep -n "max length" plugins/agent-skills/commands/offload.md` prints nothing.
- [ ] Every agent body has a stop rule and a default report format. `doc-curator`, `memory-recorder` and `memory-status-checker` have no stop rule: add "When the brief does not fit what you find, stop and report the gap, because you cannot ask the owner" as a fragment. Audit the rest. Check: a table of agent · stop rule · report format in the pull request description.
- [ ] `user-config/routing.md`: replace the restated brief parts with a reference to the brief rule, keeping word for word what only this file says about the `implementer` brief: "follow the task's test-then-code steps, commit this task locally, and write the full report (commands run, failing and passing output) to the report path". The review brief line becomes: what changed as paths or a commit range, the intent in one line, rules that are not in `CLAUDE.md` or `AGENTS.md`, what is already verified, the round number, the findings already rejected. Check: `python3 scripts/validate.py` passes.
- [ ] Update `plugins/agent-skills/skills/prompt-engineering/SKILL.md` and `references/skills-and-agents.md` where they name the six-part brief. Check: the grep of the first box.

## Stage 3: `skeptical-reviewer`, fewer and cheaper dispatches

Seven rules dispatch the reviewer (`offload-policy.md` row and closing line; `routing.md` "Execute a plan" row, task reviewer, end of plan, before a push or pull request, process review), and two pairs overlap. The owner's rule stays: whatever changed since the last review is reviewed. What changes is that one change is reviewed once, and that its report costs less to read and to verify.

- [ ] Report format in `plugins/agent-skills/agents/skeptical-reviewer.md`: the table holds medium and high findings without the `Category` column; every low finding is one line (where, then the doubt, hedged, 15 words at most); the `Nits` line goes. When the message would pass its cap, medium and high rows stay whole and low lines give way first, replaced by `Left out: K low findings`, which the main asks for when it keeps a ledger of deferred findings. Update the Rules line on nits and the example. Target shape:

  ```markdown
  ## Findings (N medium or high, K low) — <paths>
  | # | Severity | Confidence | Where | Evidence (fact) | Suspicion (hedged) | Check |
  Low:
  <where> — <doubt>
  Not checked: <what you did not read or run>
  ```

  Read the graders `hedged.md` (it judges the Suspicion cell of every finding) and `clean-file.md` (it counts nits) of `offload-skeptical-reviewer-quality` first; change only what names the old format, never what a grader accepts. Check: that case holds its record, and `usage_reviewer.py`'s `severities()` counts a report in the new format (it already reads both).
- [ ] Inputs section of the same file: a brief may name a commit range or a task file instead of pasting text, and lists only the rules that are not in `CLAUDE.md` or `AGENTS.md`, which the reviewer already reads. Check: one trace with a commit-range brief returns findings instead of stopping.
- [ ] `user-config/offload-policy.md`, reviewer row: keep its trigger and reason; replace its last sentence with "Run it in the background with the checks, triage every finding yourself and verify the medium/high ones in one call that prints every cited range. A change a review already covered is not reviewed again. After fixing, re-run it once only when the fix reaches beyond the findings (round 2 is the last); otherwise confirm the fix by reading it and the checks." Keep the closing line. Check: `python3 scripts/validate.py` passes after the `-with-policy` cases, which embed the policy verbatim, are re-pasted.
- [ ] `user-config/routing.md` and the matching row of `plugins/agent-skills/commands/offload.md`:
  - "Execute a plan" row: replace "`skeptical-reviewer` after the changes land" with a reference to the offload row.
  - Task reviewer: its brief names the task's commit range and the task brief file, not their text.
  - Fixes: round 2 under the same condition as the offload row.
  - End: at most three narrow reviews, for what no task review could see (interfaces between tasks, docs against code, the deferred and parked lines of the ledger).
  - Before a push or pull request: when a review already covered exactly this diff, name it and run `git status --short` and `git diff --stat` yourself; dispatch only for an unreviewed diff.
  - Process review: when a change review is also due, send both in one brief.
  Check: the Reviews section names each trigger once; `python3 scripts/port.py --check` after regenerating.
- [ ] If the owner answers D1 with yes: in the plan-loop "Fixes" line, the fix worker's brief carries the findings as reported and says "verify each finding against the code before fixing it; fix the ones that hold and list the ones that do not, each with the line that refutes it"; the main rules on the refuted ones from that list. Check: one trace of a fix round with one invented finding among real ones: the worker reports it as refuted and leaves it unfixed.
- [ ] Measure stages 2, 3 and 4 in one run after stage 4 (all three edit `offload-policy.md`), one commit per stage so a drop can be reverted alone: canary first, then every `offload-*-with-policy` and `offload-*-with-hook` case, and `offload-skeptical-reviewer-quality`. Check: Eval protocol steps 1 to 3; nothing merges to `dev` before this box.

## Stage 4: call economy and delegation thresholds

- [ ] Add to `user-config/offload-policy.md`, after the "Keep inline" paragraph:

  ```markdown
  Every call re-reads this whole context, so count calls before tokens:

  - Join commands that do not need each other's output in one shell call, and send independent tool calls in one message. A lookup of up to ~3 steps stays here as one call.
  - Delegate an episode you expect to take eight or more calls of your own (twelve when the worker writes code), or to print more than ~8k tokens you will not need word for word, when a short answer can replace it. A dispatch costs this context about as much as five to eight of your calls (brief, report, notices and what you re-read afterwards), so smaller work is cheaper batched here.
  - Give a worker one outcome. Split a brief with several goals or more than about five focus points, because a worker that runs out of turns returns nothing.
  ```

  The existing rows keep their own thresholds; where one is lower than this rule (a single long command to `check-runner`), the row wins until its own measurement says otherwise. Check: measured with stage 3; the `neg-*` cases stay silent.
- [ ] `check-runner` keeps out little more than it adds (ratio 1.3). Read 10 of its briefs from the last 7 days and classify each: one command whose output a `| tail` would have cut, several commands, or failure triage. Check: the counts are recorded in "Results"; propose a change to its row only if the first class is over half, as a separate measured item.
- [ ] If the owner answers D3 with yes and stage 0 found a per-dispatch way to wait: reword the two places of `user-config/offload-policy.md` that say "in the background" to "in the background when you have other work meanwhile; otherwise wait for it, because every wake-up re-reads this context". Check: measured in the same run; text-only calls while a dispatch is pending are in the stage 7 table.

## Stage 5: Codex spawn mode (confirmed; done first, A1)

- [x] Through the Codex transform in `scripts/port.py`, never by editing the generated files (`user-config/*.codex.md`, `ports/codex/**`), add the instruction that makes a role spawn start from a fresh context with its own model and effort (the parameter the rollout of stage 0 shows; `fork_turns` in the issue report). Check: a second rollout shows the role's model and a first request without the parent's history; record both token counts under "Codex findings". Done 2026-11-27 in `3574c14`; the second rollout needs a Codex session after the owner re-copies `offload-policy.codex.md`, so it moves to the stage 7 after-read.
- [x] `CHANGELOG.md` of `agent-skills`: a line for Codex users on the cost of the earlier behavior and the fix.

## Stage 6: ship

- [ ] `python3 scripts/port.py`; `python3 scripts/validate.py`; `claude plugin validate .`; the pre-push hook stage for the touched Python.
- [ ] `CHANGELOG.md` of `agent-skills` and of `memory`, under `## [Unreleased]`, for users: reports are shorter and capped in words; the brief has four parts; one change is reviewed once and low findings are one line each; the offload text counts calls; users who pasted the offload table or the routing text must paste the new version.
- [ ] ADR 0039 "The main conversation budgets calls, reports and briefs" (amends 0013: add "Amended by 0039" to its Status line), with the eval tables under a dated heading (`## Measurement YYYY-MM-DD`) and the kill criteria of stage 7 in "Revisit if"; `## Review` entries in ADR 0017 (reviewer format and triggers) and ADR 0021 if the structure of `routing.md` changed.
- [ ] README catalog rows if a cap is quoted there. Check: `validate.py`.
- [ ] Stage files by name (never the owner's uncommitted `CLAUDE.md` and `README.md` edits), run `agent-skills:skeptical-reviewer` on the staged diff, then ask the owner before pushing; pull request to `dev`.
- [ ] Record the after-read date (five working days after the release) as an item of `docs/backlog.md`, with its `Updated` and `Expires` dates moved.
- [ ] After the release the owner refreshes the pasted tables in `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` (the owner keeps hooks off).

## Stage 7: after-read

Five working days after the owner runs the release, rerun the four scripts and record the table in ADR 0039 as `## Measurement`.

| Change | Baseline | Keep when | Revert or escalate when |
|---|---|---|---|
| Call economy | single-shell calls 60.0% of main calls; 44% inside runs of 3+; two or more tools in 11.3% of tool-using calls | runs of 3+ hold 33% or less, or the 11.3% reaches 20% | no figure moves by a fifth: remove the text and try the escalation below |
| Delegation thresholds | 13% of dispatches under ratio 3; `implementer` redo 27.3% | under ratio 3 falls to 9% or less | `implementer` redo rises above 33%, or dispatches fall while the median context per call rises more than a tenth |
| Report budget | landed sizes in the baseline table | each of the five agents' median landed report is at its target or at least 25% under its baseline | follow-ups exceed 15% of dispatches (baseline 5.6%), or the owner reports a finding that a short report hid |
| Brief by reference | `implementer` brief 3,573 characters; its stop rate from stage 0 | median brief ≤ 2,400 characters | its stop rate exceeds 1.5 times the baseline |
| Reviewer | 6.0 dispatches per 100 main calls (410 runs over 6,824 calls); a high finding in 15% of reports; 3.5 calls spent opening reported files per report | 4.8 dispatches per 100 main calls or fewer, and 2.5 calls or fewer per report | reports with a high finding fall below 12%, or a defect reaches the owner that a skipped review would have covered |
| Waiting (only if D3 changed the text) | 1,000 text-only calls while a dispatch was pending, 15% of main calls | 10% or less | the owner misses progress messages, or parallel dispatches fall |

Escalations, each a separate measured item and Claude Code only:

- [ ] Report cap not held: after confirming the mechanism in the hooks docs (a `SubagentStop` hook can return `decision: "block"` with a reason; agent definitions take a `hooks` field), a hook that counts the words of the final message and, once per run, returns it with "shorten to N words, keep paths, numbers and quotes" when it is over 1.3 times the cap. The worker's model pays for the shortening, not the main.
- [ ] Shell runs not shortened: a `PostToolUse` hook that, after three consecutive single-shell calls of the main, adds one line asking to join the next commands or delegate the episode.
- [ ] After-read recorded and each row ruled keep, revert or escalate.

## Stage 8: workflow pilot for one plan task (needs D2)

A plan task costs the main a dispatch and its re-reading three times over (implement, review, fix). A workflow script chains those agents and returns only the final result to the main; a plugin may ship one in `workflows/`, and the owner starts it.

- [ ] Read the workflows page of the Claude Code docs and write `plugins/agent-skills/workflows/plan-task.js`: `implementer` on the task brief file, then `skeptical-reviewer` on its commit, then one fix round when the review has a medium or high finding; it returns the commit range, the checks' result, the findings fixed and the findings left, within the report budget. Check: `claude plugin validate .` passes and one dry run on a throwaway task completes.
- [ ] Pilot on one small plan: half its tasks through the plan loop, half through the workflow. Compare main calls and tokens added to the main per task, findings fixed, and rework. Check: the table is recorded in "Results", and the owner rules on adopting it; the plan loop text of `routing.md` changes only after that ruling, with an ADR (0019 chose the loop).

## Budget and stops

- Evals: `--max-cost-usd 5` per invocation; stop and ask the owner once the plan's eval spend passes 20 USD (an assumption of this plan, not an owner ruling).
- Stop and ask the owner when an eval case drops 2 or more of 6 after one wording fix, when a change would touch an agent `description`, before any push, and at D1, D2 and D3.

## Results

**Waiting for a worker (2026-11-27, `claude-code-guide` on code.claude.com docs).** No documented per-dispatch parameter makes the main wait for one subagent. The subagent frontmatter `background: true` only forces background ("even when Claude asks to wait for it"; `sub-agents.md`). `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` removes `run_in_background` from Bash, PowerShell and subagent tools alike (`env-vars.md`). A finished subagent resumes through `SendMessage` with its ID or name, keeping its history (`sub-agents.md`, "Resume subagents"). A `SubagentStop` hook returning `decision: "block"` with a `reason` delivers the reason as the subagent's next instruction (`hooks.md`); a subagent's own `hooks` field is "Ignored for plugin subagents" (`sub-agents.md`), so the stage 7 escalation hook must live in the plugin's `hooks/`, not in an agent file. Codex has `wait_agent` (wait for a mailbox update from any live agent) and `followup_task` (send a task to an existing agent, starting a turn if it is idle): the `Left out:` bullet works there too.

## Codex findings

Source: the owner's local rollouts in `~/.codex/sessions`, November 2026 (Codex 0.164 and 0.171, VS Code extension); scripts in the session scratchpad, not committed.

| Question | Answer | Evidence |
|---|---|---|
| Does a spawn without `fork_turns` fork the parent's history? | Yes. The 0.171 `spawn_agent` schema says: "Parent history to inherit. Defaults to `all`; use `none` to start without parent history." 29 of 30 role or `explorer` spawns in 0.171 sessions omitted it and started as `history_mode: legacy` children with `forked_from_id` | 192 parent-side spawns, 189 child rollouts |
| Tokens of the child's first request | Forked: median 118k input tokens (19 role children); fresh: 25.6k (158 children). Over a child's run: 1.32M against 0.39M input tokens | `token_count` events after the child's first own `turn_context` |
| Does the role's model and effort hold? | Yes, 19 of 19 forked role children ran on the TOML's model and effort, so the issue's "ignores the role's model" did not reproduce. The schema: "The selected role applies regardless of how much parent history is inherited" | `turn_context` model and effort against `~/.codex/agents/<role>.toml` |
| Does `AGENTS.md` load in a fresh child? | Yes, in 160 of 160 fresh children | `AGENTS.md` in the child's items before its first request |
| Does a fresh child lack context? | At most 1 of 160 fresh children (0.164 spawns passed `fork_turns: "none"` with an explicit `model`) ended with a missing-context stop | final message matched for `BLOCKED` or missing context |

Fix (stage 5, commit `3574c14`): a `CODEX_REWRITES` entry turns the policy's "A worker sees none of this conversation," into an instruction to spawn every worker with `fork_turns` set to `"none"`. Its check is the next Codex after-read: role children with `history_mode: paginated` and a first request under 40k input tokens.
