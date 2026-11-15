# Superpowers and agent-skills: overlaps and seams

> Reference, not a decision. Nothing here changes an agent, skill, command or policy: each seam waits for the owner. The decided boundary lives in [requirements.md § Superpowers boundary](requirements.md#superpowers-boundary) (requirement R5). A seam the owner decides moves there or to an ADR, and its row leaves this file.

As of 2026-11-15: Superpowers 7.0.2 (`22f0b463e7a5`), agent-skills `651e633`. [Recheck](#recheck-after-a-superpowers-update) after a Superpowers update: 6.4.2 → 7.0.2 already renamed files and changed scripts.

## Summary

- The two plugins rarely disagree on **intent**. They disagree on **action**: Superpowers puts the method in the main conversation and enforces it with gates and strong wording; agent-skills moves the work to named subagents with a fixed model and keeps the main conversation for decisions.
- **Execution and general review have drifted from the declared boundary.** The boundary gives `executing-plans` and `requesting-code-review` to Superpowers; `user-config/routing.md` and `offload-policy.md` give both to `implementer` and `skeptical-reviewer` (seams E1, R1).
- **Planning is where agent-skills leans on Superpowers most, and where use falls short.** agent-skills has no plan writer and delegates to `writing-plans`, but the plan's hand-off leads into Superpowers execution, and 13 of the 22 sessions with three or more `implementer` dispatches had no plan activity (P3, [observed usage](#observed-usage)).
- **Eleven of the 25 seams carry a conflict** ([index](#seam-index)). The ones that touch everyday work: parallel implementers (E1), who runs the proof of completion (R3), and mechanical fixes against the root-cause gate (D2).
- **Complementary as written**: `brainstorming` with `intent-elicitation` (P2), `test-driven-development` with `qa-principles` (D3), `writing-skills` with `prompt-engineering` on process (A2).
- **Only Superpowers has**: worktrees, the branch-finish menu, a resumable task ledger, spec-compliance review, a root-cause method. **Only agent-skills has**: cheap-model offload, specialist reviewers, `fact-checker`, `ui-verifier`, `pre-mortem`, ADRs and requirements, evals.

## Labels

| Label | Meaning |
|---|---|
| `text` | Read in the plugin files; the quoted phrase can be grepped in the named file |
| `observed` | Counted in the owner's session transcripts ([window and limits](#observed-usage)) |
| `inferred` | Our reasoning from the two texts; not seen in a trace |
| Boundary: agrees / drifted / silent | The seam matches a row of the declared boundary, contradicts it, or has no row |
| SDD | The Superpowers skill `subagent-driven-development` |

Paths: Superpowers files are relative to its `skills/`; agent-skills files to `plugins/agent-skills/` unless they start with `user-config/` or `docs/`.

## How each plugin works

| Dimension | Superpowers (`text`) | agent-skills (`text`) |
|---|---|---|
| Contents | 15 skills, all process or authoring; no agents, no commands | 15 skills, 17 agents, 14 user-only commands (`disable-model-invocation: true`), 2 UI mods |
| Activation | `hooks/hooks.json`: a SessionStart hook injects `using-superpowers` on startup, clear and compact: "even a 1% chance a skill might apply ... you ABSOLUTELY MUST invoke the skill" | No hook. Skill and agent descriptions ("auto-triggering is a bonus", ADR 0007) plus two tables the owner pastes into the user-level CLAUDE.md |
| Precedence | "User instructions (CLAUDE.md, ...) take precedence over skills, which in turn override default behavior" | No precedence statement |
| Who does the work | The main conversation follows the skill. Subagents are `general-purpose` with a prompt template; the model is chosen at each dispatch | Named agents with fixed `model`, `effort`, `tools`, `maxTurns`; the main conversation writes a six-part brief (ADR 0013) |
| Keeping context small | Files and scripts: `task-brief`, `review-package`, a report file per task | Cheap subagents: `summarizer`, `check-runner`, `researcher`, each with a bounded report |
| Enforcement | Wording strength, `<HARD-GATE>`, "Iron Law" lines, rationalization tables, scripts that gate the ledger | Calm wording (`prompt-rules.md`), `disallowedTools`, `validate.py`, `claude plugin eval`, ADRs |
| Human gates | Design approval, plan approval, execution-method choice, branch-finish menu | Question rounds in `intent-elicitation` and `feature-briefing`; subagents cannot ask |
| Progress tracking | Plan checkboxes, a `progress.md` ledger per plan, one todo per task | None in the plugin; `plan-progress` displays plan checkboxes |
| Review stance | Authoritative verdict: "Ready to merge?", task quality Approved or Needs fixes | Hedged doubts the caller verifies: "untrusted by design", no "approved" or "LGTM" |
| Artifacts | `docs/superpowers/specs/`, `docs/superpowers/plans/`, a git-ignored `.superpowers/sdd/` workspace | `docs/adr/`, `docs/requirements.md`, reports returned in the conversation |
| Git | The implementer commits each task; worktrees; merge, PR, keep or discard menu | "Commit only when the brief asks; never push or switch branches" |
| Subagents and these rules | `using-superpowers`: "If you were dispatched as a subagent ... ignore this skill" | 12 of 17 agents set `omitClaudeMd: true`; the other 5 load CLAUDE.md |

## Seam index

Kind: **conflict** (contradictory instructions), **double** (the same work done twice), **fit** (complementary as written), **coupling** (one depends on the other's format), **gap** (only one side covers it).

| ID | Superpowers | agent-skills | Kind | Boundary |
|---|---|---|---|---|
| P1 | `brainstorming` | `feature-briefing` | fit, with one conflict at the hand-off | agrees |
| P2 | `brainstorming` | `intent-elicitation`, `consistency-auditor` | fit | agrees |
| P3 | `writing-plans` | no plan writer; ADR 0013 brief contract | conflict (plan detail, hand-off) | agrees on who writes the plan; silent on format and hand-off |
| P4 | `writing-plans` self-review, SDD pre-flight | `pre-mortem` | double | agrees |
| P5 | plan file format | `plan-progress` mod | coupling | silent |
| P6 | design doc "Approaches" | `decision-records`, `change-impact` | double (decision in two places), gap | agrees |
| E1 | SDD | `implementer`, routing "Execute a plan" | conflict | drifted |
| E2 | `executing-plans` (inline) | offload row "more than ~20 changed lines" | conflict | drifted |
| E3 | ledger, todos, `task-done` | none | gap | silent |
| E4 | `dispatching-parallel-agents` | parallel briefs, `fixer` | double | silent |
| E5 | `using-git-worktrees`, `finishing-a-development-branch` | `release-hygiene`; no worktree or finish step | gap, fit | silent |
| R1 | `requesting-code-review`, SDD task reviewer | `skeptical-reviewer` | double, conflict (verdict form, rounds) | drifted |
| R2 | `receiving-code-review` | triage line of the offload policy | fit | silent |
| R3 | `verification-before-completion` | `check-runner`, "Before you reply" line | conflict | agrees, tension unstated |
| R4 | one reviewer covering security, architecture, tests | `architect`, `security-reviewer`, `qa-engineer`, `ux-reviewer`, `doc-curator` | fit | agrees |
| R5 | none | `fact-checker`, `ui-verifier` | gap | agrees |
| D1 | `systematic-debugging` | `performance-analyst` | fit, with a shared trigger | agrees |
| D2 | `systematic-debugging`, `test-driven-development` gates | `fixer` | conflict | silent |
| D3 | `test-driven-development` | `qa-principles`, `qa-engineer` | fit | agrees |
| D4 | `test-driven-development` "Always" | `refactoring`, `implementer` step 2 | conflict (strictness) | silent |
| D5 | `condition-based-waiting.md`, `writing-good-tests.md` | `qa-engineer` flaky mode, `test-quality.md` | double (two rulebooks) | silent |
| A1 | SessionStart hook, skill-first rule | offload and routing tables | conflict (order unstated) | silent |
| A2 | `writing-skills` | `prompt-engineering`, `prompt-engineer`, ADR 0007 | fit on process, conflict on wording advice | agrees |
| A3 | `diagnosing-superpowers` | none | gap | silent |
| A4 | skills of 200 to 400 lines loaded into the main conversation | offload-first, N1 (`SKILL.md` ≤ 150 lines) | conflict (cost) | silent |

## Planning seams

| ID | Same intent | How the action differs (`text`) | If both run on one task |
|---|---|---|---|
| P1 | partly | `brainstorming` is a dialogue: one open question at a time, an approaches message, a design doc in `docs/superpowers/specs/`, then "Nothing gets built until your human partner approves the design doc". `feature-briefing` is evidence first: seven steps, parallel `consistency-auditor`, `researcher`, `architect` and specialists, an options matrix, an ADR | `feature-briefing` calls `brainstorming` for step 1 and says "then return to step 2, because writing-plans waits for step 5"; `brainstorming` ends with "invoke superpowers:writing-plans and no other skill". The two exits contradict. Two owner interviews are possible (`inferred`) |
| P2 | partly | `brainstorming` designs something new. `intent-elicitation` reconstructs intent from existing code, drafts a hypothesis first and asks "≤ 4 questions per round", each with options; it writes EARS requirements and ADRs | The split is explicit on the agent-skills side ("a new design with no existing code or docs belongs to Superpowers brainstorming"). On existing code both claim the task: `brainstorming` lists "modifying behavior". Question styles differ: open and single, or optioned and batched |
| P3 | partly | `writing-plans` writes `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md` with files, interfaces and TDD steps down to "Commit", then asks "Which execution approach would you prefer?" and requires `subagent-driven-development` or `executing-plans`. agent-skills writes no plan format; `feature-briefing` step 5 uses "Superpowers writing-plans if installed" | ADR 0013 rejects "Plans with complete code for the worker" and the brief says "State the what, the limits and the check, not each step". The plan's hand-off leads to Superpowers execution while `routing.md` sends execution to `implementer`. Two openings in the skill itself: "User preferences for plan location override this default", and an execution method "already explicitly supplied" skips the menu |
| P4 | partly | `writing-plans` self-reviews in the same context ("not a subagent dispatch"); SDD runs a pre-flight conflict scan. `pre-mortem` is a fresh Opus context that returns failure stories, assumptions, rated risks and kill criteria | Two or three audits of one plan. Amendments land in the plan once; in this repo they appear as an appended "Amendments (pre-mortem ...)" block |
| P5 | n/a | `plan-progress` reads `docs/superpowers/plans/`, `docs/plans/` and `plans/`, and two shapes: "several headings each owning checkboxes (Superpowers ...)" or a task list with nested subtasks | Compatible today. A change in the Superpowers plan template can break the card without any change here |
| P6 | partly | The design doc has an "Approaches" section; `decision-records` writes `docs/adr/NNNN-kebab-title.md` with Alternatives. Superpowers has no blast-radius, rollout or rollback step (`change-impact`) | One decision can be recorded in a spec and in an ADR |

## Execution seams

| ID | Same intent | How the action differs (`text`) | If both run on one task |
|---|---|---|---|
| E1 | partly | SDD makes the main conversation a controller: one fresh `general-purpose` implementer per task with the model named at dispatch, a brief file from `task-brief`, a task reviewer after each, a fix loop, a ledger, a final whole-branch review; "Do not pause to check in". agent-skills dispatches the fixed Sonnet `implementer` with a six-part brief in the prompt, then `check-runner`, then one `skeptical-reviewer` | SDD: "Never dispatch multiple implementation subagents in parallel". Offload policy: "Independent briefs run in parallel in one message, with disjoint paths". Two implementer contracts apply to the same task ([table](#the-two-implementer-contracts)). `observed`: of the 6 sessions that loaded SDD, 5 also dispatched `implementer`, alongside `general-purpose` subagents |
| E2 | no | `executing-plans` is the inline path: the main conversation writes the code in test-first order and its `task-done` script runs the tests and appends the ledger line only on pass | The offload policy delegates any plan task over ~20 changed lines. `observed`: `executing-plans` was never loaded |
| E3 | n/a | Superpowers tracks a plan three ways: checkboxes, a `progress.md` ledger in the plan's workspace that survives compaction, and one todo per task | agent-skills tracks nothing itself. Ticking the plan depends on user-level rules; `observed`: 4 of 22 multi-task sessions edited a plan file |
| E4 | partly | `dispatching-parallel-agents`: one `general-purpose` subagent per failing domain, in one message, then the main conversation checks for conflicts and runs the full suite. agent-skills: parallel briefs with disjoint paths; `fixer` for mechanical errors | Two rules for the same fan-out; Superpowers states no model and no path ownership |
| E5 | partly | `using-git-worktrees` isolates the work under `.worktrees/` and runs baseline tests; `finishing-a-development-branch` offers merge, PR, keep or discard. `release-hygiene` covers commit messages, version bumps, changelog and tags | They run in sequence. agent-skills has no isolation step and none for integrating a branch; `implementer` never switches branches |

### The two implementer contracts

| Aspect | Superpowers `implementer-prompt.md` | agent-skills `implementer` + ADR 0013 |
|---|---|---|
| Agent and model | `general-purpose`; model required at dispatch | `model: sonnet`, `effort: medium`, `maxTurns: 60` |
| Brief | A path to `task-N-brief.md` cut from the plan | Six parts written by the main conversation: goal, scope, decisions with reasons, checks, stop rule, report |
| Tests | TDD when the task says so, with red and green evidence | "Write or update a test ... see it fail when feasible" |
| Commit | "Commit your work" | "Commit only when the brief asks" |
| Questions | Asks; the controller answers and provides context | Cannot ask: stops and returns what is missing |
| Self-review | Checklist before reporting | None; runs the given checks until green |
| Stop | `BLOCKED` or `NEEDS_CONTEXT` | `BLOCKED — checkpoint` near round 24, `BLOCKED — turn budget` near round 48 |
| Report | Full report in a file, a short reply | At most 25 lines in the reply |

## Review and verification seams

| ID | Same intent | How the action differs (`text`) | If both run on one task |
|---|---|---|---|
| R1 | partly | Superpowers reviews a git range or one task against the plan: spec compliance (missing, extra, misunderstood) and code quality; output is Critical / Important / Minor plus a verdict; "Fix Important issues before proceeding"; the fix loop allows "Five rounds maximum per task". `skeptical-reviewer` (Haiku, effort high) reviews whatever changed since the last review, including docs, layout and deletions; output is hedged findings with severity and confidence; the caller verifies; "there is never a round 3" | Two reviews of one change, with different verdict forms and stop rules. `observed`: `requesting-code-review` never loaded; `skeptical-reviewer` dispatched 496 times |
| R2 | partly | `receiving-code-review` is a protocol for the receiver: understand, verify against the code, push back, implement one item at a time; "STOP - do not implement anything yet" when an item is unclear. agent-skills has one policy line: triage every finding, verify the medium and high ones | Compatible: the protocol is a superset of the line. `observed`: never loaded |
| R3 | partly | `verification-before-completion`: "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE"; the main conversation runs the command and reads the full output; an agent's success report is not evidence ("Verify independently"). `check-runner` (Haiku, effort low) runs the checks and returns only failures | The Superpowers text asks the main conversation to run and read what the offload policy tells it to delegate. Reading the worker's PASS or FAIL may or may not satisfy the gate; no file says (`inferred`). `observed`: never loaded |
| R4 | partly | The Superpowers code reviewer covers security, architecture and testing in one pass. agent-skills splits them across specialists, each with its own scale | Overlapping coverage, separate scales |
| R5 | no | No Superpowers skill checks claims against cited sources or drives a browser flow | agent-skills only |

Only Superpowers has, in review: a spec-compliance check, a re-review that confirms each finding is fixed, adjudication recorded as rulings, a whole-branch review before merge.

## Debugging and testing seams

| ID | Same intent | How the action differs (`text`) | If both run on one task |
|---|---|---|---|
| D1 | partly | `systematic-debugging` is an inline, four-phase cause hunt: "NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST". `performance-analyst` is a subagent that measures a baseline, profiles and tests one change per hypothesis | Both descriptions fire on slow code: the skill lists "Performance problems". No file orders them |
| D2 | partly | The debugging skill covers "Test failures" and "Build failures" and has no carve-out for mechanical errors; `test-driven-development` requires a failing test before production code. `fixer` loops "run check → fix → rerun", groups errors by cause and prefers safe autofixes | Read literally, the root-cause gate forbids the `fixer` loop for lint, type and import errors. `fixer` shares one stop rule ("The same error after 2 attempts → stop") |
| D3 | partly | `test-driven-development` decides when to write a test and enforces red, green, refactor. `qa-principles` decides which cases and how good: risk map, ISTQB techniques, mutation testing | Compatible and stated on the agent-skills side: "not for the red-green-refactor loop itself (Superpowers test-driven-development)" |
| D4 | partly | `test-driven-development` applies "Always", refactoring included: "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST". `refactoring` asks for characterization tests first and allows skipping them for a tool-driven rename in a clean tree; `implementer` sees a test fail "when feasible" | A subagent does not load Superpowers skills (`using-superpowers` tells it to ignore them), so under the offload policy the strict loop reaches code only through the softer `implementer` step (`inferred`). `observed`: `test-driven-development` loaded once |
| D5 | partly | `condition-based-waiting.md` gives one cause and fix for flaky tests; `writing-good-tests.md` gives gate-style rules. `qa-engineer` flaky mode classifies causes; `test-quality.md` catalogs smells and test doubles | Two rulebooks that do not contradict |

Explicit hand-offs to Superpowers in this area: `observability` and `api-design` ("belongs to Superpowers systematic-debugging") and `qa-principles` (the red-green-refactor loop, quoted in D3). Other areas: `intent-elicitation` and `feature-briefing` (P1, P2), `prompt-engineering` (A2). Superpowers names agent-skills nowhere.

## Activation and authoring seams

| ID | Same intent | How the action differs (`text`) | If both apply |
|---|---|---|---|
| A1 | no | Superpowers requires a skill check "BEFORE any response or action" and orders process skills first (`"Fix this bug" → superpowers:systematic-debugging first`). agent-skills routes by tables in CLAUDE.md, which Superpowers itself ranks above skills | The tables win where they speak (`inferred` from the precedence line). No file says whether a skill is invoked first and the table followed after, or how the skill-first rule relates to delegation rows |
| A2 | yes on process | `writing-skills`: "NO SKILL WITHOUT A FAILING TEST FIRST", pressure scenarios with subagents, persuasion wording ("YOU MUST"), a description that "never summarizes the skill's workflow". `prompt-engineering` hands the process to it ("belongs to Superpowers `writing-skills`") and adds wording rules: "Calm wording; MUST/NEVER only for true invariants", descriptions that say what the skill does, then when, then why to load it, measured with `claude plugin eval` | Opposite advice on emphasis and on what a description contains. A skill written to one standard fails the other |
| A3 | no | `diagnosing-superpowers` reads session transcripts and builds a cited report when a Superpowers session went wrong | agent-skills has no diagnosis tool; this one could examine a seam in a real session |
| A4 | no | Superpowers skills load whole into the main conversation: `writing-plans` 204 lines, `brainstorming` 316, `executing-plans` 323, `subagent-driven-development` 339 | The offload policy sends any file over ~200 lines to `summarizer`, and N1 caps a `SKILL.md` at 150 lines. Loading a Superpowers skill costs the context the policy protects (`inferred`) |

## Where the declared boundary has drifted

| Boundary row | What the files do now |
|---|---|
| "`writing-plans` / `executing-plans`" owned by Superpowers; agent-skills adds `change-impact` and `pre-mortem` | `user-config/routing.md`: "Execute a plan" goes to `implementer` per task, `check-runner`, `skeptical-reviewer`. The offload row delegates plan tasks over ~20 changed lines |
| "`requesting-code-review` (general)" owned by Superpowers; agent-skills adds specialist lenses | ADR 0017 added `skeptical-reviewer`, a general reviewer that the offload policy makes "part of done" |
| "`verification-before-completion`" with `check-runner` and `ui-verifier` as "cheap workers that produce that evidence" | Agrees in intent; the Superpowers text does not accept a subagent's report as the evidence (R3) |
| README: "Superpowers owns process" and the workflow diagram, with "executing (TDD + qa-engineer)" | Same drift as the first two rows |

## Observed usage

62 main-conversation sessions, 2026-10-27 to 2026-11-15, all of the owner's projects, counted once per tool call. 53 sessions predate 2026-11-13, when Superpowers moved from 6.4.2 to 7.0.2. Counts show what ran, not what was worth running.

| Superpowers skill | Loads |
|---|---|
| `writing-plans` | 10 |
| `brainstorming` | 7 |
| `subagent-driven-development` | 7, in 6 sessions |
| `finishing-a-development-branch` | 4 |
| `systematic-debugging` | 4 |
| `test-driven-development` | 1 |
| `executing-plans`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review`, `dispatching-parallel-agents`, `using-git-worktrees`, `writing-skills`, `diagnosing-superpowers` | 0 |

| agent-skills agent | Dispatches |
|---|---|
| `implementer` | 530 |
| `skeptical-reviewer` | 496 |
| `check-runner` | 76 |
| `researcher` | 69 |
| `pre-mortem` | 67 |
| `fact-checker` | 43 |
| `fixer` | 9 |

`general-purpose` subagents were dispatched 449 times; the transcripts do not say which were Superpowers implementers or reviewers.

Planning in the 22 sessions with three or more `implementer` dispatches:

| Measure | Sessions |
|---|---|
| Loaded `writing-plans` | 5 |
| Loaded `subagent-driven-development` | 5 |
| Wrote a plan file | 7 |
| Edited a plan file afterwards | 4 |
| No plan skill, plan write or plan edit | 13 |

Limits: the counts are a snapshot taken while the session that wrote this document was still running, so a recount gives slightly higher agent numbers; a plan ticked through the shell is not counted; a session resumed in a new transcript counts twice; the window mixes two Superpowers versions and several versions of the user-level CLAUDE.md.

## Open questions for the owner

| # | Question | Seams |
|---|---|---|
| 1 | Who executes a plan: SDD, `implementer` rows, or SDD's controller loop with `implementer` as its subagent? | E1, E2, P3 |
| 2 | Should the boundary table follow the current routing for execution and general review, or the routing return to the boundary? | E1, R1 |
| 3 | Which plan format: the Superpowers template, a lighter task list, or the template with the execution method and folder supplied in advance? | P3, P5, E3 |
| 4 | Is a subagent's PASS enough evidence for "done", and should a line say so? | R3 |
| 5 | Should mechanical fixes be exempt from the root-cause gate in writing? | D2 |
| 6 | How strict is test-first for code written by `implementer`? | D4 |
| 7 | Is anything from the Superpowers task review worth adding to the `skeptical-reviewer` brief (spec compliance, confirming a fix)? | R1 |
| 8 | Should a line state the order between the skill-first rule and the tables? | A1 |
| 9 | Are worktrees and the branch-finish menu wanted in the agent-skills flow? | E5 |
| 10 | Which Superpowers skills are worth their length in the main conversation? | A4 |

## Recheck after a Superpowers update

```sh
ls ~/.claude/plugins/cache/anthropic-plugin-directory/superpowers/          # installed versions
diff -rq <old>/skills <new>/skills                                          # files added, removed, changed
grep -rn -i "superpowers" --include='*.md' plugins/agent-skills user-config docs/requirements.md
```

Then grep each quoted phrase of the changed skills in its file; a phrase that no longer matches marks a row to reread.
