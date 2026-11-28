# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

## [1.5.1] - 2026-11-28

### Changed

- Agents report the evidence needed for the caller's next decision and what changed on follow-up. In plan-loop fix rounds, the fix worker checks reported findings and the caller rules on disputed findings. Refresh your copied routing and offload policies and Codex roles.

## [1.5.0] - 2026-11-27

### Added

- Workflow `plan-task` (pilot, Claude Code only, unmeasured): runs one plan task through `implementer`, `skeptical-reviewer` on its commits and one verified fix round, and returns only the final result to the main conversation. Start it yourself with the task file and its checks; adoption waits for the pilot comparison (ADR 0039).

### Changed

- The offload text counts calls before tokens: join independent commands, delegate an episode of about eight or more of your own calls (twelve when the worker writes code), give a worker one outcome, and end the turn with a one-line status instead of writing messages while a worker runs. A row's own threshold still wins. Re-paste the offload policy and routing from `user-config/` (Codex: re-copy the `.codex.md` files).
- `skeptical-reviewer` reports put only medium and high findings in the table (no `Category` column) and give each low finding one hedged line, `<where> — <doubt>`; when the report would pass its cap, low lines are replaced by `Left out: K low findings`. A brief may name a commit range or a task file instead of pasting text. The offload text and routing now review one change once: a change a review already covered is not reviewed again, round 2 runs only when the fix reaches beyond the findings, a plan ends with at most three narrow reviews, and in a plan-loop fix round the fix worker verifies each finding first and lists the refuted ones with the line that refutes each. Re-paste the offload policy and routing.
- The worker brief has four parts (goal, scope, decisions, checks) and points at files the worker can open instead of restating them; the stop rule and report format now live in each worker. If you pasted the offload table or the routing text into your own instructions, paste the new versions from `user-config/`.
- Worker agents (`skeptical-reviewer`, `implementer`, `fixer`, `check-runner`, `ui-verifier`, `pre-mortem`, `summarizer`, `researcher`) now cap their final report in words through one shared rule (`Left out:` names what was cut; a brief may lower the cap, never raise it), because line caps did not bound length and the main conversation re-reads every report. `doc-curator` gains a stop rule. Reinstall `user-agents/Explore.md` to get its 600-word cap (it replaces "30 lines").
- Codex: the offload policy now says to wait with `wait_agent` (it wakes on any worker's message) instead of writing messages while a worker runs, and the routing text names `AGENTS.md` only. Re-copy the `.codex.md` files.

### Fixed

- Codex: the offload policy now tells Codex to spawn every worker with `fork_turns` set to `"none"`. Without it Codex copies the whole parent conversation into each worker: in local rollouts (Codex 0.171, Nov 2026) 29 of 30 worker spawns did so, and a worker's first request carried a median of 118k input tokens instead of 25.6k, about 1.3M instead of 0.4M input tokens per worker over its run. The role's model and effort were honored either way. Re-copy `user-config/offload-policy.codex.md` into your Codex instructions.

## [1.4.2] - 2026-11-27

### Fixed

- Prompt-engineering guidance covers Codex traces for role selection, audit-mode writes and context delivery.

## [1.4.1] - 2026-11-27

### Fixed

- The Codex port no longer tells Codex to use Claude Code features it lacks (background dispatch, `Monitor`, the Bash `timeout` parameter, slash commands, `CLAUDE.md`, "no model parameter"); the wording now matches what Codex offers. The Copilot port is unchanged. Re-copy `user-config/offload-policy.codex.md` and `routing.codex.md` into your Codex instructions.

## [1.4.0] - 2026-11-27

### Added

- `architect`, `security-reviewer`, `consistency-auditor`, `doc-curator` and the user-scope `Explore` agent can use the `fff` search tools (`grep`, `find_files`, `multi_grep`) when the `fff` MCP server is connected; without it they launch and work as before (observed in one test run on current Claude Code). Reinstall `user-agents/Explore.md` to pick up its rule. Unmeasured (ADR 0024, Review 2026-11-27).

## [1.3.0] - 2026-11-27

### Changed

- `skeptical-reviewer`: its description no longer excludes diff review, so it matches the review row that sends it the staged diff before a push or pull request.
- `skeptical-reviewer`: accepts a process-review brief (rules and steps with their evidence, no paths) and checks it with a new `Process` row, instead of stopping for missing paths; a doubt about a step it did not re-check is reported at confidence `low`. Unmeasured, one trace (ADR 0017, Measurement 2026-11-26, P1).
- `architecture-principles`: the smell catalog names flat sprawl (many modules in one folder, a shared filename prefix in place of packages) and its remedy, grouping by feature.
- `architecture-principles`: a new § File size treats file size as a balance, not a limit; the `architect` reads it when it measures file sizes, and measures the call graph before proposing a split.
- `implementer`: when its task moves, renames, splits or merges modules, it checks that the tests guarding the old names still fail when violated, and reports under Open questions / risks any it could not prove or that lie outside its files. Unmeasured (ADR 0013, Review 2026-11-26).

## [1.2.0] - 2026-11-26

### Added

- The offload table (about 700 tokens, estimated at 4 bytes per token) now loads from a `SessionStart` hook at session start, after `/clear` and after a compaction; new users paste only the routing text. Nothing to do if the table is pasted in `~/.claude/CLAUDE.md`: the hook sees it and stays silent. If the table reaches the session another way (an `@import`, a project `CLAUDE.md`, `CLAUDE.local.md`, account instructions, a file with CRLF line ends) the hook cannot see it and the table loads twice: turn the option off with `/plugin configure agent-skills@mili-ssm` (`offload_policy`). A stale pasted copy wins over the plugin's until you delete it. The cloud script turns it off unless `AGENT_SKILLS_OFFLOAD_HOOK=1`. Copilot and Codex users keep pasting. Decision and measurement: ADR 0032.

### Changed

- Offload policy (`user-config/offload-policy.md`): the `skeptical-reviewer` row and the closing line now name the two-round limit ("re-run it once after fixing (round 2 is the last)"). Re-paste the file into your user-level `CLAUDE.md` to pick it up.
- `prompt-engineer` and `ux-reviewer` read the project's `CLAUDE.md` / `AGENTS.md` first, so decided project rules are no longer reported as findings and project overrides apply.
- `architect` gives options for its top 3 findings and at most 2 ADR drafts, to keep its report within its 80-line limit.
- `api-design`: the status-code table says when each of 400/422, 401/403/404 and 409/412 applies. `architecture-principles` and `intent-elicitation` gain a light path for one module or one gap; `/ux-design` follows the skill's small-change rule; `feature-briefing` states as a rule that the plan waits for step 5, and falls back to `intent-elicitation` only when the feature extends existing code or docs.

### Fixed

- `check-runner` and `ui-verifier` set the Bash `timeout` parameter for long commands (the old 900 s limit could never finish under the tool's 10-minute maximum) and say when to wait with `Monitor`.
- `researcher` states its 300-word limit and stops with a partial report after about 12 tool calls; `implementer` may write the report file its brief names and reports `none` when it has no open questions; `consistency-auditor` opens the staleness rubric file before rating.
- `security-reviewer`, `prompt-engineer`, `consistency-auditor`, `architect` and `pre-mortem` treat the text they read as data and report instructions addressed to an AI assistant instead of following them.

## [1.1.0] - 2026-11-25

### Changed

- `pre-mortem` runs on Opus at `medium` effort instead of `high` (fewer reasoning tokens, same model); the Codex port maps it to `gpt-6.2-sol` low.
- `implementer`, `check-runner` and `ui-verifier` can use `Monitor` to wait for a command the harness moved to the background, instead of a blocked `sleep`; `implementer` says so in its rules. Claude Code only; the ports are unchanged in behavior.
- Codex port model mapping is now derived from a model catalog (`shared/models.toml`); no other agent's Codex model or effort changes (the `pre-mortem` line above is the one that does), and the unused `max` cells now follow the effort policy (never `max`, `xhigh` only on the top model).
- Instruction lines that several agents share (report language, read-only shell use, delegation, search tools) now come from one source, so they stay identical across agents. Nothing to migrate; the Copilot and Codex ports carry the same wording changes and are otherwise unchanged.
- Read-only agents state the read-only shell rule in one shared wording; `prompt-engineer`, `fact-checker` and `skeptical-reviewer` allow temp dirs only, so builds and test runs stay with `check-runner`; `ux-reviewer` keeps its capture-file rule as its own line.
- `prompt-engineering` references link the measurements they cite to the public ADRs instead of naming bare ADR numbers; `pre-mortem` calls missing success criteria a risk; `feature-briefing` no longer implies `ux-reviewer` has a `design` mode.

## [1.0.0] - 2026-11-19

### Added

- First versioned release. From now on an update brings only released content: `main` holds releases and work integrates on `dev` (ADR 0027); Claude Code and Copilot also see the version, Codex ports stay unversioned. License: MIT.
- Contents: 17 agents (7 of them cheap offload workers), 15 skills and the commands in the README catalog; Copilot and Codex ports under `ports/`; the offload policy and the routing rules in `user-config/`.

### Changed

- Codex ports: the Opus agents run on `gpt-6.2-sol`; the equivalence table gains a Fable row on `gpt-6.2-astra` and states each vendor's relative cost scale (`docs/ports.md`).
