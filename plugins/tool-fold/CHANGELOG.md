# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

### Fixed

- Concurrent agent calls for the same shell command share one description request and retry; when it succeeds, each card receives the description.

## [0.1.1] - 2026-11-27

### Changed

- Internal cleanup: an unused export of the agents hook was removed. No visible change.

## [0.1.0] - 2026-11-19

### Added

- First versioned release: tool calls, skills and agents fold into compact lines, and running agents keep a live card in the "Agentes" pane. License: MIT.
