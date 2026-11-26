# 0017 Skeptical after-action reviewer, Codex pair for Haiku medium

Status: accepted · Date: 2026-11-03 · Amends 0007, 0010, 0012, 0014 · Amended by 0018, 0019

## Context

`pre-mortem` stress-tests plans before the work; nothing reviews what an action just produced before it is delivered. Tests cover correctness, so the weak spots that owners or users find later are quality ones: needless complexity, a wrong data structure, a design or UX/UI pattern violated, poor organization, unclear names or text. Research 2026-11-03: self-correction without external feedback degrades (arXiv 2310.01798); tool-checked critique helps (CRITIC, arXiv 2305.11738); critics hallucinate bugs (CriticGPT, arXiv 2407.00215); judges are biased (arXiv 2306.05685, 2410.21819). Design: `docs/superpowers/specs/2026-11-03-skeptical-reviewer-design.md`.

## Decision

- Renamed 2026-11-03 from `untrusted-reviewer` to `skeptical-reviewer`: "untrusted" read as the opposite of the intent, a reviewer that distrusts the work.
- New seventh worker `skeptical-reviewer` (Haiku, effort medium, read-only, `maxTurns` 20, `omitClaudeMd: true`, `Skill` to load at most one existing skill). Its report is untrusted: hedged wording, evidence per finding, never an approval; the caller triages, verifies medium and high findings, and skims low ones.
- Focus (owner refinement): quality of what is about to be delivered, ranked by how much fixing it would improve the delivery, then by confidence; obvious bugs are listed with the rest; nits ≤ 5.
- Trigger: at least ~20 changed lines or 2 files, or any deletion; also a doc section or an image description. Dispatched in the background with `check-runner`. The brief carries the round number and the findings already rejected; the reviewer stops at round 2; a report about files changed after dispatch is stale.
- Coupled edits: `WORKERS` in `validate.py`, "seven workers" in CLAUDE.md, offload row and policy row, the `*-with-policy` cases (verbatim policy), the `neg-*` graders that name every agent, README catalog and Workers cell. ADR 0007 and 0010's "Use proactively" exception now covers seven workers; 0012's single-copy policy gains a row.
- Codex pair: `("haiku", "medium")` becomes `("gpt-6-luna", "low")` in `scripts/port.py` (owner, 2026-11-03). The change is global, so it also moves `researcher`'s Codex port to luna low. ADR 0014's early-stop risk (low effort stopping early) is watched. It is its own commit (`port.py`, `docs/ports.md`, regenerated `ports/`).
- Evals (owner exception to N6, 2026-11-03): only the new agent's cases run, `offload/skeptical-reviewer-with-policy` (dispatch after a ~60-line module across two files) and `offload/skeptical-reviewer-quality` (a working module with a list scanned inside a loop where a set fits, plus a clean file). The existing `neg-*` and other `*-with-policy` suites are not re-run by owner decision, although the new description and policy row could move them (the eval protocol lists every `neg-*` for an agent description): **unmeasured** for those suites, with the kill criterion below. Budget per glob `--max-cost-usd 5`. The quality case grades the main model's relay of the report and the trace, not the subagent's report itself.

## Alternatives

| Option | Rejected because |
|---|---|
| Hook after every Edit/Write | Reviews half-done edits, costs more, adds a moving part |
| Worker plus a new checklist skill | More context per cheap call; existing skills already cover each domain |
| Bug-hunt focus | Tests cover correctness; critics hallucinate bugs; the owner wants early quality alerts |
| Keep luna medium for Haiku medium | The owner accepted luna low for cost |

## Consequences

- One more row in the offload table: every session loads a few more tokens, and the main model may dispatch too often (watch the trace).
- Reviewer findings can be wrong or anchoring; the triage rule and hedged wording limit that cost, they do not remove it.
- `researcher` on Codex runs at luna low; it may stop before searching.

## Revisit if

Measured numbers for the two cases exist (record them in `## Measurement YYYY-MM-DD`), a model change alters Haiku's routing, or the reviewer's false-positive rate in real use makes the owner stop reading its reports.

### Kill criteria

| Signal | Action |
|---|---|
| Any routing oddity in traces (an unrelated agent fires, or a skill stops firing) | Run the `neg-*` suite and compare with the ADR 0007 records |
| `skeptical-reviewer-with-policy` dispatch ≤ 1/3 with a Sonnet main | Re-plan: hook or Stop reminder |
| Quality case misses the seeded point in ≥ 2/6 runs, or > 2 findings on the clean file | Raise effort or re-plan |
| More than 2 dispatches per change in a trace | Tighten the trigger floor |
| `researcher` on Codex returns without searching | Pin it to its own Codex pair |

## Measurement 2026-11-03

`--model sonnet --runs 3`, after the rename and eval fixes:

| Case | Result |
|---|---|
| `offload-skeptical-reviewer-quality` (dispatch asked) | 0.94; delegated 3/3, point-found 3/3, hedged 3/3, no-verdict 3/3, clean-file 2/3 |
| `offload-skeptical-reviewer-with-policy` (dispatch left to the policy) | 0.00; delegated 0/3 |

The reviewer works when dispatched; a Sonnet main conversation does not dispatch it on its own from the policy row, as with `implementer` (ADR 0012 Measurement). Kill criterion "with-policy dispatch ≤ 1/3" met: proactive use is re-planned (a hook or Stop-time reminder), not reverted, because the agent itself measures well. Earlier run before the fixes (2 runs): with-policy 0/2; quality 0.50, its `clean-file` fixture had a real bug and `hedged` judged the main answer, both fixed.

## Measurement 2026-11-04

Owner's simpler rule (before the final answer, whenever the project changed since the last review; closing "Before you reply" line), then every agent reports in English. Sonnet main.

| Case | Baseline (2 runs, before) | Turn-end rule (3 runs) | + English (runs) |
|---|---|---|---|
| `offload-skeptical-reviewer-with-policy` | 0/2 | 1/3 | 1/3 + 1/3 = **2/6** |
| `offload-skeptical-reviewer-quality` | 2/2 | 3/3 | 3/3 |
| `neg-*` (5 cases) | 10/10 silent | 15/15 silent | not re-run (no description change) |
| `offload-check-runner-with-policy` | 2/2 | 3/3 | 2/3, rerun 6/6 |
| `offload-ui-verifier-with-policy` | 2/2 | 3/3 | 2/3 (judge), rerun 6/6 |
| `offload-summarizer-with-policy` · `-extract-` | 2/2 · 2/2 | 3/3 · 3/3 | 3/3 · 3/3 |
| `offload-implementer-with-policy` | 0.17 | 0.17 | 0.17 (owner: fires constantly in real use) |

Full baseline the same day (2 runs): 17 trigger cases match their records (`architecture-principles` 0/2, `performance-analyst` 0/2, `docs-principles`, `pre-mortem`, `security-principles` 1/2; the rest 2/2); no regression from adding the worker. Proactive dispatch moved 0 → 2/6 with wording only; hooks were declined by the owner and remain the next lever if it stays low in real use.

## Review 2026-11-12

The Decision's trigger floor ("at least ~20 changed lines or 2 files") was replaced on 2026-11-04 by the owner's simpler rule (whatever changed since the last review; Measurement 2026-11-04), which the policy states. The `/agent-skills:offload` row still carried the floor and now states the same rule (ADR 0018). Vendor data read 2026-11-12 (ADR 0018) supports keeping Haiku for a report the caller verifies, and shows why it is not the only gate for defects.

The same day the owner raised `skeptical-reviewer` from effort `medium` to `high` (ADR 0018 Review 2026-11-12); its Codex port moves from `gpt-6-luna` `low` to `medium`.

## Review 2026-11-15

ADR 0019 makes `skeptical-reviewer` the task reviewer of the Superpowers plan loop and the reviewer after its last task; ADR 0021 moves the owner's review rows into `user-config/routing.md`.

The kill criterion "More than 2 dispatches per change in a trace" no longer holds as written: one review per plan task and several narrow reviews per change are intended (owner, 2026-11-15). No replacement criterion has been set by the owner; ADR 0021 proposes one for the review rows. In the 62 sessions measured, the reviewer was dispatched 496 times against 530 `implementer` dispatches.

## Measurement 2026-11-26

The offload policy's `skeptical-reviewer` row and closing line now name the two-round limit ("re-run it once after fixing (round 2 is the last)"; "and round 2 has not run"), which until now only `user-config/routing.md` stated (project review 2026-11-24, P4). Sonnet main, 2 runs, `--scaffold`; the same run carries body changes to `check-runner`, `implementer` and `ui-verifier` (changelog, Unreleased).

| Case | Last record | 2026-11-26 (2 runs) |
|---|---|---|
| `offload-skeptical-reviewer-with-policy` | 2/6 | 2/2 |
| `offload-check-runner-with-policy` | rerun 6/6 | 2/2 |
| `offload-summarizer-with-policy` · `-extract-` | 3/3 · 3/3 | 2/2 · 2/2 |
| `offload-implementer-with-policy` | 0.17 | 0/2: implemented 2/2, no dispatch |
| `offload-ui-verifier-with-policy` | rerun 6/6 | 0/2: `delegated`, `inline`, `js-defect` 2/2; `faq-works` 1/2; `mobile-defect` 0/2 |

- The four cases that ran clean hold their records, so the change is kept. The reviewer case moved from 2/6 to 2/2 on 2 runs, too few to claim a gain.
- The two cases below their record were rerun at 6 runs on both sides the same day (Eval protocol step 2), `dev` in a worktree:

  | Case | `dev` (old policy text) | This change |
  |---|---|---|
  | `offload-implementer-with-policy` | 0/6, score 0.17: `implemented` 6/6, `delegated` 0/6 | 0/6, score 0.17: `implemented` 6/6, `delegated` 0/6 |
  | `offload-ui-verifier-with-policy` | 2/6, score 0.83: `delegated`, `inline`, `js-defect` 6/6; `faq-works` 4/6; `mobile-defect` 2/6 | 1/6, score 0.75: `delegated`, `inline`, `js-defect` 6/6; `faq-works` 2/6; `mobile-defect` 1/6 |

- `offload-implementer-with-policy` is identical on both sides: the main model writes the code itself in every run, as its record of 0.17 says. The policy change does not move it.
- `offload-ui-verifier-with-policy` drops 1 run of 6, under the revert threshold of 2, so the change is kept. Both sides sit far below the record of 6/6 because no browser launches in the eval sandbox (Playwright finds no Chromium; system Chrome exits on the read-only `$HOME`): the two graders that need the browser fail on `dev` too, while dispatch is 6/6 on both. That record cannot be reproduced on this machine until backlog item 3g is done (set aside by the owner, 2026-11-26).
