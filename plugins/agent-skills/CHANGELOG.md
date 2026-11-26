# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

### Changed

- `architecture-principles`: the smell catalog names flat sprawl (many modules in one folder, a shared filename prefix in place of packages) and its remedy, grouping by feature.
- `architecture-principles`: a new § File size treats file size as a balance, not a limit; the `architect` reads it when it measures file sizes, and measures the call graph before proposing a split.
- `implementer`: when its task moves, renames, splits or merges modules, it checks that the tests guarding the old names still fail when violated, and reports any it could not prove. Unmeasured (ADR 0013, Review 2026-11-26).

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
