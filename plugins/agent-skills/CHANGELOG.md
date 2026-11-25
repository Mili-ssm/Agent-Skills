# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

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
