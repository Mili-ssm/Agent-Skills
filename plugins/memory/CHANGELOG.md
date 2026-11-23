# Changelog

All notable changes to this plugin. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions: [SemVer](https://semver.org/).

## [Unreleased]

## [0.8.0] - 2026-11-23

### Added

- The option `auto_reword` (off by default; it needs `auto_capture`) lets the background pass reword the short form of a loaded lesson that got worse, once for each wording you wrote or read, with the same checks as a first short form; a reworded lesson shows in `mem rules --unread`. The pass never rewords its own rewording nor a wording you kept with `mem triage accept`: those come to you. `mem-corroborate reword` runs the step by hand (`--dry-run`, `--sheet FILE`). Its gate passed on one store (15 lessons); read `mem rules --unread` after it runs.
- The option `rules_layout` (`flat` by default, or `grouped`) and `mem rules --layout` print the lessons loaded at session start under a heading per topic; the same lessons load, only the text changes. Nothing has to be done: the default is the old layout. The grouped layout is not measured yet.

## [0.7.0] - 2026-11-23

### Added

- Each lesson now keeps a log of dated cases (`worked`, `failed` or `seen`, taken from what the capture saw) and the versions of its short form, each with its tally; `mem show` prints them. A lesson that got worse after it loaded is marked in `mem rules` and `mem rules --more`, listed by `mem curate` under "balance got worse after loading", and counted in the session start text ("Got worse: N loaded lesson needs a decision"). It keeps loading until you decide: reword it or go back to an earlier text (`mem memory edit <h> --short`), drop it (`mem forget <h>`), or keep the wording with the new `mem triage accept <h>` (`--project-scope` for a project lesson), which stores a `reviewed` date. `mem confirm` and `mem remember` take `--outcome` and `--seen-on`; the corroboration pass carries cases to the general lesson.
- Records written before, and older plugin versions reading a store written by this one, keep working: there is nothing to migrate.

### Changed

- `mem confirm --source` on a session the lesson already counts, given with `--outcome`, now adds that case, prints `m:<handle>\tcase <outcome> added` and exits 0; without `--outcome` it still changes nothing and exits 3. `--outcome` or `--seen-on` without `--source`, and a `--seen-on` later than today, are usage errors.
- The log line of the corroboration pass has one more key, `cases`: the case entries it carried to general lessons.
- Up to 16 lessons (was 6) and 2400 characters of rule lines (was 900) now load at session start, so more established lessons reach the agent without asking by topic; nothing has to be done.

## [0.6.0] - 2026-11-22

### Added

- With `auto_capture` on (and `loaded_rules` not `false`), the background pass now writes the short form and topic of established lessons that lack one, and they load at the next session start **before anyone has read them**. Code refuses a short form that drops its claim's hedge, adds an absolute word, holds a link or says "owner"; a second model session checks the rest against their claims. A short form is tried twice at most per wording of a claim; after the second refusal a general lesson waits at triage with the reason (`mem triage hold <h> --because TEXT` does it by hand). A `strong` project lesson is filled only after you confirm it. Measured once before release, by a gate on a private copy of one store (the plugin README gives the figures and what they do not show); a short form that keeps its hedge but loses the situation of its lesson is not caught, so read `mem rules --unread` now and then. To see what loaded unread: `mem rules --unread` (also counted by `mem curate`); to mark them read: `mem rules --read <h>...` or `--read all`; to switch one off: `mem memory edit <h> --no-load`; to switch all off: option `loaded_rules` to `false`. `mem-corroborate status` prints a `last fill:` line.

### Changed

- A general lesson waits at triage on its first establishment only when its weight is `strong`; a `medium` or `light` one is released and may load once it has a short form. Pending ones stay pending.
- `mem memory edit --short` and `mem remember --short` now check the text against the claim: a text that drops the claim's hedge, adds an absolute word, holds a link or says "owner" is refused (exit 2, with the reason), and an accepted one is marked as unread by a person. Pass `--user-read` for a text you read yourself (no check, no mark). Stored short forms are not touched.

## [0.5.0] - 2026-11-22

### Added

- Established lessons can load at session start as short rules (at most 6, 900 characters), followed by one line that counts the other recommendations by topic; `mem rules` prints them and `mem rules --more [<topic>]` lists what did not load. A lesson loads only when it has a short form, so **nothing loads after the update until you give lessons one**: `mem-corroborate fill --dry-run --out FILE` has a small model propose a short form and a topic for up to 30 lessons, in a file that also carries each lesson's load state (`yes`, `index` or `no`) for you to set (it starts one model session and sends lesson text to it), you read and edit the file, then `mem-corroborate fill --items FILE` applies it (no model session; `mem-corroborate undo <stamp>` reverts it). Or write one by hand with `mem memory edit <h> --short TEXT --topic TEXT`, or `mem remember --short --topic`. `mem memory edit <h> --no-load` turns one rule off and `--index-only` keeps it to the index line; `--load` removes either. Editing a claim removes its short form. The plugin option `loaded_rules` (on by default) set to `false` loads no rules and prints no index line at session start; `mem rules` still shows what would load. Rolling back to the previous version keeps the new record fields (`short`, `topic`, load state). Nothing to migrate.

### Changed

- The capture now also keeps, as an unconfirmed lesson, a step you asked for on your own that visibly paid off (for example one more review before publishing), so that a later session may take that step without being asked. Nothing to migrate.

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
