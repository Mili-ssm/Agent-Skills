# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

### Changed

- After a compaction the summary ends with a handoff block (task, state, next step, verified, unverified, plan) and lists the items not yet recorded; the agent is told only when the block is missing or names a plan file that does not exist. Nothing to migrate.

## [0.2.0] - 2026-11-19

### Changed

- A note that a sentence of its synthesis cites goes stale only when such a sentence, or a table row of its part, changes; a note no sentence cites still goes stale on any change to its part, and stamps written before keep that whole-part rule until the note is stamped again.

### Fixed

- A web page whose `<script>` or `<style>` is never closed no longer hides the text from its next tag on, so a quote there is found by the research checks; script source before that tag may still count as page text.
- `mem import --research-data` now scans every text file it copies (`.txt`, `.json`, ...) for secrets and hard terms, not only Markdown.
- A write to the global scope is refused, with a message, when neither `HOME` nor `XDG_CONFIG_HOME` is set (exit code 2, nothing written), because the forbidden-terms list cannot be located; project writes are unaffected.
- `mem memories --project NAME` says so on stderr and exits 2 when the registered project's memory folder was moved or deleted, instead of printing nothing.

## [0.1.0] - 2026-11-19

### Added

- First versioned release of the `mem` command and its skills and agents: search, read and record notes and memories, curation passes, syntheses. License: MIT.
- Still under active development: while the version is `0.y.z`, a minor version may change commands or the store layout; the changelog says how to migrate.
