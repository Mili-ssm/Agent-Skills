# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-22

### Added

- New option `auto_capture` (off by default): when a compaction starts and at session end, a background run reads the new part of the session's transcript and writes lessons as unconfirmed project memories (`auto_capture_budget`, USD per window, default 0.25). Turning it on sends transcript text of the session to a small model through your own `claude` and spends model usage; a failed run shows one line at the next session start until `mem-capture ack`. Not yet measured. Nothing to migrate.
- Memories can now come from a session transcript: they are marked `from transcript, unconfirmed` until another session shows the same lesson, and lapse 30 days after the last session that showed them. `mem remember` takes `--reach` and `--weight`; `mem confirm` takes `--source` and `--note` to record one more session; `mem curate` has a new category for these records; `mem-capture run --write` records the kept candidates as project memories. No hook runs it yet. Nothing to migrate.
- A trial command `mem-capture run` proposes memory candidates from a session transcript into a local file; it writes nothing to the store and no hook runs it. Nothing to migrate.
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
