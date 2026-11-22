# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

### Added

- Reminders: ask a later session for a piece of work. `mem remind <topic> --body TEXT` writes one (due now, or after `--in-sessions N`, `--in-days N`, `--after DATE`; `--every 30d` or `--every 10s` repeats it; `--effort` and `--risk` say how big and how risky the work is); `mem reminders` lists what is due with the rule for acting on it (`--all`, `--stats`); `mem reminder done|close|snooze|restore <handle>` ends or undoes one. A session start now counts sessions per project in the data folder (`startup`, `clear` and `compact`, not a resume). When a reminder is due, the session start text gains one line, at most 300 characters. A store or project without reminders behaves as before, and nothing changes in the text. Nothing to migrate.

## [0.4.1] - 2026-11-22

### Fixed

- The background capture and the corroboration pass now find the global memories folder from the store (`MEM_STORE`, or the default store) as `mem` does. Before, with no `MEM_MEMORIES` set, they saw no global memory: since 0.3.0 the capture could propose again a lesson that a global memory already held, and in 0.4.0 the pass could not add a sighting to a global record. Nothing to migrate; the next capture and pass read them.

## [0.4.0] - 2026-11-22

### Added

- A general lesson captured from a transcript now gets one global record that stays in quarantine: searches, the session start text and `mem memories` do not show it until it is seen in a second project (three sessions across two projects for a `strong` one) or the owner confirms it with `mem confirm <h> --global --by-owner`. `mem memories --global --quarantine` lists what waits. **Migration:** before you install this version, confirm with `--by-owner` every global memory of origin `transcript` that you want to keep readable: one seen in fewer than two projects (every one written before this version, since sightings did not name a project) would otherwise be hidden.
- With `auto_capture` on, a background pass (`mem-corroborate`) starts after a capture that wrote something. A small model proposes which lessons state the same lesson, a second session verifies each proposal, and only verified ones are applied: duplicates inside a project are merged, a general lesson gets its global record, and later sightings are added to it. It sends lesson text to the model, costs up to two sessions per pass within `auto_capture_budget` each, and can be undone per run with `mem-corroborate undo <stamp>`. `mem-corroborate status` and `ack` report and clear a failed pass.
- A lesson that leaves quarantine waits for triage: `mem curate --global` lists it and the session start text counts it. `mem triage accept <h>` keeps it, `mem triage reject <h>` retires it and marks its project records so they are not promoted again, and `mem memory edit <h> --global` rewords it.
- With `auto_capture` on, a session start also captures sessions in the transcript folder of the starting session that were left open and never ended (idle for 6 hours, at most 7 days old; at most 2 per start and 4 per day use the model, at the cost of an ordinary capture).
- A capture that recognizes a lesson already kept as a global record adds a sighting to it, naming the project by an opaque key and never copying text of the transcript.


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
