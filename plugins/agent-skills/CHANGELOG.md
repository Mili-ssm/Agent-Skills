# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

### Changed

- Lines repeated across agents (English report, read-only Bash, delegation, `fff` tools) are now rendered from one source and wrapped in `<!-- shared:... -->` markers; the ports carry no markers. No behavior change.

## [1.0.0] - 2026-11-19

### Added

- First versioned release. From now on an update brings only released content: `main` holds releases and work integrates on `dev` (ADR 0027); Claude Code and Copilot also see the version, Codex ports stay unversioned. License: MIT.
- Contents: 17 agents (7 of them cheap offload workers), 15 skills and the commands in the README catalog; Copilot and Codex ports under `ports/`; the offload policy and the routing rules in `user-config/`.

### Changed

- Codex ports: the Opus agents run on `gpt-6.2-sol`; the equivalence table gains a Fable row on `gpt-6.2-astra` and states each vendor's relative cost scale (`docs/ports.md`).
