# Weekly usage study: suspicions and suggestions (read-only)

**Window**: records dated 2026-11-11 to 2026-11-18. **1,150 transcript files, 28 main sessions, 1,114 unique Agent calls** (deduped by `id`), 5 projects (A graphics code, B note-writing hub, C this repository, D and E work projects). Snapshot: the counts drift as sessions continue. Earlier window: [2026-11-17-subagent-usage.md](2026-11-17-subagent-usage.md).

The counts in § 1 are **observed** (counted from transcripts); the "Sampled cause" column of its error table and the labels of the general-purpose calls are read from a few commands or from call descriptions. § 2 is **suspected**: a cause read from counts and a few sampled commands, not tested. § 3 is **suggested**: nothing here is decided until its Status says so.

The counts come from `docs/studies/scripts/usage_counts.py` and `usage_errors.py` (read-only over `~/.claude/projects`, last 7 days; `SELF` in each excludes the session that ran them).

"Weighted tokens" = input + 1.25 × cache write + 0.1 × cache read + 5 × output. It is not price-adjusted across models.

## 1. Observations

### Where the tokens went

| Scope and model | Weighted tokens | Share |
|---|---|---|
| Subagents, Sonnet | 262 M | 39% |
| Main session, Opus | 172 M | 26% |
| Main session, Fable | 116 M | 17% |
| Subagents, Haiku | 83 M | 12% |
| Subagents, Opus | 32 M | 5% |

| Project | Main turns | Context per turn: median / p90 / max | Compactions | Inline checks | `check-runner` calls |
|---|---|---|---|---|---|
| A | 2,519 | 425k / 760k / 966k | 4 | 126 | 33 |
| B | 1,635 | 337k / 658k / 966k | 2 | 157 | 3 |
| C | 725 | 424k / 840k / 964k | 1 | 89 | 1 |
| D | 753 | 280k / 540k / 635k | 0 | 63 | 8 |
| E | 220 | 166k / 263k / 289k | 0 | 16 | 6 |

"Inline checks" = Bash calls in the main session that ran `pytest`, `cargo test|build|clippy|check`, `validate.py`, `npm run` or `ruff`.

### Agent calls

| Type | Calls | Model | Turns: median / p90 | Median output tokens | Share of weighted tokens |
|---|---|---|---|---|---|
| implementer | 271 | Sonnet | 21 / 62 | 16.3k | 15.8% |
| skeptical-reviewer | 255 | Haiku | 9 / 15 | 25.7k | 10.0% |
| general-purpose | 239 | Sonnet 209, Haiku 22, Opus 8 | 20 / 65 | 16.3k | 20.9% |
| fact-checker | 77 | Sonnet | 12 / 33 | 11.7k | 2.7% |
| researcher | 52 | Haiku | 6 / 9 | 11.4k | 1.1% |
| check-runner | 51 | Haiku | 6 / 9 | 2.1k | 0.3% |
| pre-mortem | 45 | Opus | 12 / 36 | 15.0k | 1.6% |
| ui-verifier | 39 | Sonnet | 7 / 17 | 5.4k | 0.5% |
| Explore | 23 | Opus | 16 / 44 | 9.2k | 1.2% |
| prompt-engineer 17, summarizer 11, performance-analyst 6, architect 5, doc-curator 5 | 44 | | | | 1.9% |
| fixer 3, consistency-auditor 3, qa-engineer 2, security-reviewer 1, ux-reviewer 0 | 9 | | | | 0.5% |
| memory-curator, memory-recorder, memory-researcher | 1 each | | | | (plugin installed 2026-11-17) |

- Rework: 63 of 271 implementer calls (23%) were fix rounds; 64 of 255 reviewer calls were a second round or re-review (classified from the call description).
- general-purpose, classified from call descriptions: 89 note-writing and 45 fact-check calls in project B, 24 plan-task reviews (21 Sonnet, 3 Opus) that bypassed `skeptical-reviewer`, 31 trial subjects in project C.

### Skill loads (59 in 28 sessions)

`docs-principles` 12, `prompt-engineering` 11, `systematic-debugging` 6, `writing-plans` 5, `subagent-driven-development` 5, `feature-briefing` 3, `decision-records` 3, `change-impact` 3, `ux-principles` 2, one each for `refactoring`, `api-design`, `intent-elicitation`, `brainstorming`, `update-config`, `dataviz` and the three memory skills.

No load: `security-principles`, `qa-principles`, `observability`, `architecture-principles`, `release-hygiene`, `web-research` (against 52 `researcher` calls).

### Tool errors

| Error | Count | Mostly in | Sampled cause (4 commands each) |
|---|---|---|---|
| zsh `= not found` | 160 | general-purpose 63, skeptical-reviewer 34, implementer 20, fact-checker 13, main 12 | unquoted `echo ===` used as a separator between commands |
| zsh `no matches found` | 53 | general-purpose 14, fact-checker 13, implementer 10 | unquoted glob in an option, e.g. `--include=*.rs` |
| zsh `defining function based on alias` | 15 | general-purpose 10 | a function named `g` or `gg`, which are aliases in the owner's profile |
| zsh `bad substitution` | 2 | general-purpose 2 | not sampled |
| `Blocked: sleep N followed by …` | 48 | implementer 34 | a command started in the background, then `sleep` plus `cat` of its output file |
| `No such tool available: bash` | 27 | implementer 19 | tool name written in lower case |
| `No such tool available: Monitor` | 10 | implementer 10 | waiting on a background command with a tool the agent does not have |
| `This agent is isolated in the worktree` | 21 | implementer 17, performance-analyst 4 | a path of the main checkout or the session scratchpad used from an isolated worktree |
| Auto-mode classifier denial | 28 | main 11, implementer 10, skeptical-reviewer 5 | not sampled |
| `mem … use --shrink if that is meant` | 9 | general-purpose 8 | an edit that drops sentences |
| WebFetch size limit | 7 | researcher 7 | page over the fetch limit |

### Inline checks, measured for suspicion S3

All 453 inline checks of the window (`docs/studies/scripts/usage_inline_checks.py`; 2 more than the table above; the difference between the two scripts was not traced):

| Measure | Value |
|---|---|
| Output already cut in the command (`tail`, `head`, `grep`, `-q`) | 426 of 453 (94%) |
| Result size: median / p90 / max | 394 / 1,704 / 16,915 characters |
| Results over 4,000 characters | 18 |
| All results together | 379,002 characters, about 95k tokens for the week |
| Wall time: median / p90 / max | 5 s / 66 s / 475 s; 49 over 60 s; 179 minutes in total |
| One `check-runner` call | about 35k weighted tokens on Haiku (1.8 M over 51 calls), plus its brief and report in the main context |
| One inline check in weighted tokens (estimate, not measured) | a median result of about 100 tokens costs 125 to write and 10 per later turn that re-reads it: about 1,100 over 100 later turns, on the main model |

## 2. Suspicions

| # | Suspicion | Rests on | Would be tested by |
|---|---|---|---|
| S1 | The main session, not the subagents, is the largest cost once price is applied, because Opus and Fable cost more per token than Sonnet and Haiku and each main turn re-reads a context of 280k to 425k tokens | § 1 token and context tables; price ratios are assumed, not taken from a price list | pricing the same counts with the published rates |
| S2 | Sessions run until the context is near its limit instead of ending at a plan boundary: 7 compactions in 5,852 main turns, maxima of 964k to 966k in three projects | context table | reading where the long sessions could have ended (a merged PR, a finished plan stage) |
| S3 | The offload row for checks is not followed: 451 inline against 51 delegated. Either the row's trigger is too weak or inline is the better choice for short checks and the row is wrong | context table | measured on 2026-11-18 (table above): the inline checks are short and already cut, so by the estimate above a short inline check costs fewer tokens than a dispatch, whose brief and report also stay in the main context; what delegation would save is waiting time on the 49 checks over 60 s. The row, not the behavior, looks wrong for short checks |
| S4 | The zsh errors are an environment mismatch, not a prompt defect: agents write bash, the Bash tool runs the owner's zsh profile | sampled commands | the same counts after G1 |
| S5 | `implementer` has no rule on how to wait for a long command, so it backgrounds it and polls | 34 + 10 errors, and no line on this in `implementer.md` | the same counts after the rule ships |
| S6 | The worktree refusals come from briefs that carry absolute paths of the main checkout | 4 sampled commands, all with such a path | reading the briefs of those runs |
| S7 | `skeptical-reviewer` writes more than it needs: its median output is the highest of the frequent agents on 9 turns, at `effort: high` | agent table | reading 5 traces: how much is thinking, how much is report |
| S8 | `web-research` is redundant with the offload row that already dispatches `researcher` | 0 loads, 52 calls | a second week with 0 loads |

## 3. Suggestions

Order = expected gain against risk. Status values: `proposed`, `accepted`, `done`, `dropped`.

| # | Suggestion | Addresses | Where | Status (2026-11-18) |
|---|---|---|---|---|
| G1 | Make the Bash tool run bash: `CLAUDE_CODE_SHELL=/usr/bin/bash` in the `env` block of the owner's `~/.claude/settings.json` (the owner chose this over a quoting line in the agent bodies, which would not reach general-purpose). The aliases `g` and `gg` come from the zsh profile only | S4 | the owner's settings, outside this repository | accepted; the setting is applied on the owner's machine, its verification in a new session and in a subagent is open (plan task 3b) |
| G2 | `implementer`: run long commands in the foreground with a timeout instead of background plus polling; paths relative to its working directory | S5, S6 | `plugins/agent-skills/agents/implementer.md` | done, unmeasured ([ADR 0025](../adr/0025-implementer-waits-in-the-foreground-and-stays-in-its-worktree.md)) |
| G3 | End the session at a plan boundary (a finished stage, a merged PR) and resume from the plan file and the memory | S1, S2 | owner habit | accepted as a habit; the owner declined a line in `user-config/routing.md`. Read the context medians again in the next study |
| G4 | Decide issues #124 (`note-writer`) and #125 (`fact-checker` batch and apply mode) | general-purpose at 21% | new or widened agents | #125 done (description names batches, read-only kept; ADR 0018 Review 2026-11-18); #124 waits for the next study, by the owner's ruling |
| G5 | Name the route for plan-task reviews so they stop going to general-purpose on Sonnet | 24 calls | `user-config/routing.md` | proposed |
| G6 | Enforce the checks row, or narrow it to checks whose output is long or slow | S3 | `user-config/offload-policy.md` (a measured change, requirement N6 in [requirements.md](../requirements.md)) | accepted (owner, 2026-11-18), after the S3 measurement: delegate a check expected to run over a minute or to print more than a screen, run the rest inline with the output cut. Done: row narrowed and measured, [ADR 0010](../adr/0010-cheap-offload-workers.md) Review 2026-11-18. The owner's `~/.claude/CLAUDE.md` copy is re-pasted after the merge |
| G7 | Wait one more week on the six skills with no load; then merge or remove `web-research` | S8 | skills | proposed |
| G8 | Inject the offload policy and the routing rules from a session-start hook of the plugin instead of pasting them into the user-level `CLAUDE.md` (the owner's question, 2026-11-18). For: no re-paste after each change; subagents that load `CLAUDE.md` stop reading about 80 lines addressed to the main conversation only. Against: text injected by a hook may be followed less than `CLAUDE.md` text (not measured; the memory plugin's three session-start lines were followed), the `*-with-policy` evals measure neither path, the Copilot and Codex ports have no such hook, and ADR 0021 would be amended | S1, re-paste upkeep | a hook in `plugins/agent-skills`, ADR 0021 | proposed |

## Limits

- One user, one week, two projects hold 79% of the weighted tokens.
- Error causes come from four sampled commands per category; counts match a text pattern in the tool result, so a pattern inside ordinary output would be counted too.
- "Inline checks" counts every `npm run <script>`, so a few may be scripts that are not checks.
- Fix rounds and review rounds are classified from call descriptions, not outcomes.
- The memory plugin was installed on the last full day of the window: its agents have no usable sample.
