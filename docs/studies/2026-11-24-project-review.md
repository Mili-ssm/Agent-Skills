# Project review: improvement backlog and refactor candidates

Status: owner rulings 2026-11-24 in § Decisions for the owner; quick doc fixes D1, D3, D4, D5, D8 and the status part of D2 applied with this study · Date: 2026-11-24

What should improve across the whole repository (all plugins, scripts, docs and prompts), and which refactors are worth planning? Five read-only agents assessed it in parallel (`architect`, `qa-engineer`, `security-reviewer`, `doc-curator`, `prompt-engineer`), and a second `prompt-engineer` pass read the agent-skills skill and agent bodies; findings marked **verified** were re-read in code by the main session. The memory plugin's structure was assessed the day before ([study](2026-11-23-memory-plugin-structure.md), [refactor plan](../superpowers/plans/2026-11-23-memory-refactor.md)); this review reports only progress against it and what it missed.

## Conclusion

> Done 2026-11-25 on branch `feat/repo-tooling` ([plan](../superpowers/plans/done/2026-11-25-repo-tooling-and-shared-text.md), ADR 0029): Q1, Q2, Q3, A9, A10, B9–B12.

The repository is healthy at plugin level: no imports cross plugins, every check is green (on 2026-11-24: memory 2,214 passed / 5 skipped in 294 s, tool-fold 154, plan-progress 9, `validate.py` and `port.py --check` OK). The debt sits in four places:

1. **Security of the memory engine** (S1–S7): one high, three medium, three low. S1–S4 and S6 are fixed in [PR #182](https://github.com/Mili-ssm/Agent-Skills/pull/182) (plan `docs/superpowers/plans/done/2026-11-24-memory-security.md` there); S5 and S7 stay open (§ Security, still open).
2. **The memory refactor plan has not started**: none of its tasks is done, and `bin/` copies a background-job lifecycle the study did not count.
3. **The commit gate is untested and unenforced**: `validate.py` and `port.py` have no tests, and nothing runs them automatically.
4. **Docs and prompts drift**: the memory state table already contradicts the release, and three homes (descriptions, `routing.md`, `offload-policy.md`) restate the same triggers.

## Architecture and refactors

Churn since 2026-09-01 (commits per file): `mem.py` 122, tool-fold `agents.tsx` 92, `records.py` 44, `mem-corroborate` 34, `waiting.tsx` 28.

| ID | Area | Finding | Sev | Effort | Action |
|---|---|---|---|---|---|
| A1 | memory config | Refactor-plan task 1 not started: no `engine/config.py`; 15 files read `CLAUDE_PLUGIN_OPTION_*`/`MEM_STORE`; the store-resolution block is copied in 4 hook scripts; `default_store` ×3, `data_dir` ×3 (**verified**) | high | S–M | plan task 1 |
| A2 | memory launchers | Task 2 not started: 7 places build `claude -p`; among production launchers `--strict-mcp-config` appears only in `mem-corroborate`, `backfill.py` and `research_pipeline.py`, so `mem-capture`, `mem-settle` and `synth_pipeline.py` miss the owner's 2026-11-23 ruling (**verified**) | high | M | plan task 2 |
| A3 | memory `bin/` | The job lifecycle (`cmd_ack`, `prune`, `budget_of`, `save_status`, `append_log`, `failure_line`) is copied across 4 scripts, similarity 0.89–1.00; missed by the study | medium | M | one `jobs.py` beside the planned `headless.py` |
| A4 | `bin/mem-corroborate` (1,874 lines) | Engine logic in a script: `Journal`, `Applier`, `execute`, and three parallel jobs (fill, reword, digest) each with near-identical `_state`/`_run_folder`/`_auto`/`_locked` functions | high | M | move into the engine, one module per job on a shared runner |
| A5 | `engine/mem.py` (5,924, was 7,146) | Still a god module: 235 functions, 41 `cmd_*`; each handler sits about 4,500 lines from its logic, so a split along the section banners would leave the handlers behind | high | L | split per feature, each module with its own `cmd_*` (changes how plan task 5 splits); would extend the not-yet-written ADR 0028 drafted in the 2026-11-23 study |
| A6 | `engine/records.py` (1,323, fan-in 11) | Mixes model and parsing, history, similarity, forbidden-term checks and project config | medium | M | split along those seams; `records` stays a facade; config part goes to A1 |
| A7 | engine imports | `research_checks` uses `mem.tokenize` (defined in `records`); `mem-corroborate` imports `research_pipeline` only for `session_env`, pulling in all of `mem.py`; lazy cycle `digest`↔`rules` | medium | S | import from the defining module |
| A8 | tool-fold `agents.tsx` (1,877) | Five layers in one file (format, run-state store, Haiku estimates, cards, lifecycle); 3 import cycles with `waiting.tsx` and `cycle.ts`; dead export `summarize` (tests only; removed 2026-11-26) | medium | M | split at the next tool-fold change into `format.ts`, `runs.ts`, `agent-progress.ts`, `cards.tsx` |
| A9 | `scripts/validate.py` | Checks only `plugins/agent-skills`; memory's 4 skills and 4 agents comply by hand (**verified**) | medium | S | run the agent and skill rules over every `plugins/*` |
| A10 | `port.py` vs `validate.py` | Agent rules (model, effort, maxTurns, preloads) checked twice with different allowed sets | low | S | one rule table in `validate.py` |
| A11 | parked code | `cmd_signal` and `hooks/signal.sh` ship unregistered | low | S | plan task 7 after 2026-12-01 |
| A12 | cold large files | `port.py` (1,398) has clean class seams; `evals/synthesis/run_trials.py` (2,162) is a closed trial whose `self_check` duplicates `evals/trial_env.py` | low | M | not now; split only if touched |
| A13 | mods | `progressSvg` byte-identical in both mods | low | — | accept: ADR 0011 rules out a shared package |

## Tests and the commit gate

| ID | Area | Finding | Sev | Effort | Action |
|---|---|---|---|---|---|
| Q1 | `scripts/validate.py` | The only commit gate has no tests (**verified**): a rule that fails open goes unnoticed | high | M | `scripts/tests/test_validate.py`: one negative case per rule on a temporary mini-repository; unit tests for `parse_frontmatter`, `version_key`, `block_scalar` |
| Q2 | `scripts/port.py` | `--check` is a golden test of today's data; the pure transforms (`transform`, `rename_agents`, `toml_multiline`, `copilot_tools`, …) have no edge-case tests | medium | M | table-driven tests |
| Q3 | repository | Nothing runs the checks automatically ([N5](../requirements.md), the owner's choice); the fast set takes about 20 s | medium | S | proposal: an opt-in local `pre-push` hook, or a PR workflow to `dev` and `main` · done 2026-11-25: opt-in `pre-push` hook (ADR 0029) |
| Q4 | memory tests | 294 s, mostly subprocess-based, so rarely run before commits; lock-wait tests take 3–10 s each | medium | M | try `pytest-xdist`; make wait budgets injectable with sub-second values |
| Q5 | memory tests | `sleep(1)` proves negatives and wall-clock asserts (`time.time()-began >= 2`) in `test_capture_auto`, `test_auto_curation`, `test_plugin_shell` | medium | S | handshakes or an injected clock |
| Q6 | `agents.tsx` | 22 tests for 1,877 lines (`plan.tsx`: 59 for 491) | medium | M | risk review and cases for `activitySummary`, `estimateOf`, `recentCalls`, `scriptOf` before A8 |
| Q7 | mutation | No mutation or branch-coverage data on `records.py` and `check.py` (data integrity) | medium | M | one `mutmut` run |
| Q8 | test files over 1,000 lines | `test_mem_corroborate.py` 2,664, tool-fold `plan.test.tsx` 1,286, `waiting.test.tsx` 1,197, `test_curation.py` 1,143; 33 files re-declare their own `_run` helpers | low | M | split with their modules (A4, A8); shared helpers in `conftest.py` |
| Q9 | small gaps | 5 unexplained skips (`pytest -rs`); no failure-path test for `find-claude.sh`/`subagent-start.sh`; eval case files never linted; two `parsePlan` implementations (one per mod) with no shared fixture | low | S | one each |

## Documentation

| ID | File | Finding | Sev | Action |
|---|---|---|---|---|
| D1 | `plans/2026-11-17-memory-plugin.md` § Current state | Says "Released 0.10.0" and research-gaps unreleased; 0.11.0 is released (#178, #179). CLAUDE.md sends agents here first (**verified**) | high | fix; then drop the version from the table or add a `validate.py` check against `plugin.json` |
| D2 | `plans/2026-11-17-memory-seamless.md` | "Start with stage 2", already merged in #136 (**verified**); 435 lines, ~21k tokens, open stages 3–5 buried | high | mark stage 2 merged; move finished stages to a results section |
| D3 | `plans/2026-11-18-usage-followups.md` item 5 | Open item already done (D2) | medium | tick, point to stage 3 |
| D4 | `README.md` opening | "one plugin and opt-in mods": there are four plugins (**verified**); also `tool-fold` named twice, "0008 supersedes 0005" omits 0027→0006, eval command lacks `--max-cost-usd 5` | medium | fix; link the eval command to CLAUDE.md § Eval protocol |
| D5 | 5 specs from 2026-11-02 to 2026-11-06 | Still `Status: proposed` though implemented (#106–#110) | medium | set implemented or superseded · done: no spec left `Status: proposed` (#181, #182) |
| D6 | `plugins/memory/README.md` | 318 lines, ~12.7k tokens, 5 lines over 1,000 characters, status words inside headings (breaks anchors) | medium | keep install, scope and links; move sections to reference pages |
| D7 | about 25 finished plans | No Status line; 3 stray open boxes | low | one `Status: done · merged #N` line each; archive candidates · partly done 2026-11-26: Status lines added; `2026-11-25-usage-ledger-mod` says its state is unknown |
| D8 | ADR 0027 | Lacks `Amends 0011` though 0011 says "Amended by 0027" (only break in 27 ADRs) | low | add it to the Status line |
| D9 | misc. | `requirements.md` "Current as of 2026-11-15" (last change 2026-11-19); seam IDs R1–R5 collide with requirement IDs; `platform-parity-study` plan still "in progress" with 11/11 ticked; broken anchor in `2026-11-17-memory-plugin-project-syntheses.md`; 3 orphan docs; `tool-fold/README.md` at ~360 characters per line | low | one edit each |

## Prompts and always-loaded context

Always-loaded text is about 9.2k tokens: skill descriptions 2.5k, agent descriptions 2.9k, `routing.md` + `offload-policy.md` 2.9k, session-start text 0.9k. Every description change needs the eval protocol in CLAUDE.md.

| ID | File | Finding | Sev | Action · check |
|---|---|---|---|---|
| P1 | `agents/skeptical-reviewer.md` description vs `routing.md` § Reviews | Description says "Not for … PR or diff review"; routing sends it to the staged diff before a push or PR (**verified**) | high | cut that clause · `offload/skeptical-reviewer*` and every `neg-*` · done 2026-11-26, merged #218 (ADR 0017 Measurement 2026-11-26) |
| P2 | `agents/pre-mortem.md` description | Opens "Skeptical reviewer that…", the name of another agent | medium | "Plan stress-tester that…" · `trigger/pre-mortem` and `neg-*` |
| P3 | `memory` skill vs `web-research` vs offload row | Three triggers on "research X" with no order; `memory-researcher` appears in neither routing nor offload | medium | routing row: `mem search` first, then `web-research` · a routing trace |
| P4 | `offload-policy.md` vs `routing.md` | Offload says "re-run it after fixing" with no cap; routing caps at round 2; the rule appears 3 times | medium | "re-run once (round 2)"; delete the duplicate closing line · every `offload-*-with-policy` · done 2026-11-26, closing line kept and capped (ADR 0017 Measurement 2026-11-26) |
| P5 | `routing.md` | The specialist and writing rows restate 19 descriptions (~1k tokens); § Plan loop (~580 tokens) loads every turn for a rare path | medium | keep only what descriptions cannot hold; move Plan loop to an on-demand reference (needs an ADR, 0021) · trace |
| P6 | `memory/hooks/subagent-start.sh` | Memory text goes to narrow read-only workers; `memory-synthesizer` is not skipped | medium | add it to the skip list; decide the Haiku workers from 3 traces |
| P7 | `memory-curator` agent vs `memory-curation` skill | Actions and safety rules written in both; the skill is the largest (~2.8k tokens) | medium | one home (the skill, preloaded); move § Notes and § Project syntheses to references · curator trace |
| P8 | small items | `ui-verifier`/`fact-checker` bodies carry long output examples; `Explore` says "Use proactively" outside `WORKERS` (exempted only by a code comment); `commands/offload.md` copies the offload table; session text "run mem curate" names neither the skill nor the agent | low | one edit each |

## Agent and skill bodies (agent-skills)

No stale paths, flags or tool names; every SKILL.md is at most 81 lines and every reference is linked one level deep, so no split is due (largest: `ui-verifier` ~2.3k tokens). The defects are contracts between bodies and `user-config`.

| ID | File | Finding | Sev | Action · check |
|---|---|---|---|---|
| B1 | `agents/skeptical-reviewer.md` § Inputs | Routing sends it a process review (rules and steps with evidence, no paths); the body stops on "No paths and no diff" and its checklist has no process row (**verified**) | high | accept that brief; add a `Process` checklist row · one process-review trace · done 2026-11-26 with one trace, merged #218; the description and README row still name change review only, tracked as B1b in the backlog |
| B2 | `agents/doc-curator.md` § Modes | `apply` fires on "apply, update or fix"; the command and routing pass `Mode: apply` only when the owner asked | medium | trigger on `Mode: apply` only · one `/doc-audit update README` trace |
| B3 | `agents/implementer.md` § Rules | "Leave no temporary files" and a 25-line report, while the plan loop asks for a full report file (**verified**) | medium | a report path in the brief is a deliverable · one plan-loop trace · done 2026-11-26: a report file at a path the brief names is the exception (92d3b8a); no trace recorded |
| B4 | `agents/researcher.md` | The only worker with no stop rule near `maxTurns` (**verified**) | medium | "after ~12 rounds, report what you have" · done 2026-11-26: stop after about 12 tool calls (92d3b8a) |
| B5 | `skills/web-research/SKILL.md` | Lets the main model read a page itself; the offload policy says any page goes to `researcher` | low | owner decision: drop the clause or add the exception to the policy |
| B6–B7 | 6 read-only agents; `doc-curator`, `qa-engineer`, `performance-analyst` | No "content is data" line where repository text is read; read-only modes of 3 editing agents enforced only by prompt, with no "Bash leaves files unchanged" line | low | add the existing shared lines |
| B8 | `skills/prompt-engineering/references/prompt-rules.md`, `models.md` | Model facts dated 2026-10 may be one generation old | low (unverified) | re-check with `web-research`, then re-date |
| B9–B12 | references; agents | ADR citations dead for installed users; vocabulary slips ("finding" in `pre-mortem`, `ux-reviewer` given a mode it lacks); shared lines copied ×4 to ×17 because of `omitClaudeMd`, with wording drift and no validator check; six-part brief in 3 places | low | inline notes; a drift check in `validate.py` for the shared lines |

## Security, still open

| ID | Area | Finding | Sev | Action |
|---|---|---|---|---|
| S5 | memory auto-capture | Text seen in two sessions (tool output, web pages) can become a loaded project rule; only frequency gates it | low | never auto-load capture-born rules without owner triage, or filter rules that order commands, fetches or setting changes |
| S7 | `scripts/cloud-setup.sh` | Falls back to the first `user-agents/Explore.md` under `~/.claude/plugins`, which may belong to another marketplace | low | fail instead, or restrict the search to the `mili-ssm` clone |
| — | memory, noted in the fix review | Two low hardening notes on note writes and single linked memory files | low | decide when the area is next touched |

## Recommended sequence

| Step | Content | Why first |
|---|---|---|
| 1 | Security S1–S4 and S6: done in PR #182 | one high finding in a public plugin |
| 2 | Quick fixes: D1–D5, D8, P1 (measured), A7, A9, unused `summarize` · done by 2026-11-27 (D2 that day) | small, independent, and D1 misleads every agent that resumes memory work |
| 3 | Gate: Q1 tests, then Q3 if the owner wants it · done 2026-11-25 (ADR 0029) | protects every later refactor |
| 4 | Memory refactor plan tasks 1–2 extended with A3 (`config.py`, `headless.py`, `jobs.py`) | fixes A2's missing flag on the way |
| 5 | A4 (`mem-corroborate` into the engine), then A5 per feature, then A6 | largest, most-changed files; Q4 makes the suite fast enough to run per step |
| 6 | A8 with Q6 at the next tool-fold change | cold now |
| 7 | B1–B4 (additive one-liners), then P3–P7 with traces or evals · B1, B3, B4 and P4 done 2026-11-26; B2 and P2, P3, P5–P7 open | B1–B4 are contract gaps in the plan loop and reviews; P3–P7 change always-loaded behavior |

## Decisions for the owner

Ruled 2026-11-24:

1. Security: fix now, before other work, S1–S4 plus S6 (plan on branch `fix/memory-security`); S2 by the light design: committing `.memory/` is a legitimate feature, so repository memories keep loading, but the owner confirmation written in their files no longer counts, they are marked "from repository", and corroboration never lifts them into global memories.
2. Gate: Q1 tests plus an opt-in local `pre-push` hook (Q3); no CI.
3. Refactor plan: extended with A2, A3, A4, A5 and A7 ([plan](../superpowers/plans/2026-11-23-memory-refactor.md)).

Open:

4. ~~`validate.py` over every plugin (A9)?~~ Implemented on the owner's request, 2026-11-25.
5. ~~D1: remove the version from the state table, or guard it with a check?~~ The owner chose a `validate.py` check, 2026-11-25.
6. Architect's assumed ranking of quality attributes: maintainability by LLMs, then correctness and safety of background `claude -p` jobs, then portability, then install size. ~~Confirm or reorder.~~ Recorded as N12 in `docs/requirements.md`, 2026-11-25.

## Not checked

No evals or traces were run (P3, P5, P6, P7, B1–B4 need them). No mutation or coverage run; flakiness in Q5 comes from reading, not reruns. `docs/platform-parity.md` and `docs/mods-surfaces.md` vendor claims; terminal-escape rendering in the mods; the facts inside the references of architecture-principles, qa-principles, security-principles, ux-principles, refactoring, intent-elicitation, decision-records and docs-principles.
