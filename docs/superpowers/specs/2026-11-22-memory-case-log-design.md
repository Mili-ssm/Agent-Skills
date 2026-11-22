# Case log of a lesson: design

Status: draft for the owner's approval · Date: 2026-11-22 · Extends C49 of [the capture design](2026-11-21-memory-capture-design.md), whose table reserves the numbers C64 to C71 for the rows below.

## Goal

A lesson that loads and still happens gets noticed without anyone reading a log by hand. Each lesson records when each sighting happened and when each wording of its loaded text went live, so the plugin can say "1 repetition after version 2" and, at two, hand the lesson to the owner to reword it or make it stronger.

The number of versions is the measure of how many wordings were already tried, and so of how firm the next one has to be (the owner, 2026-11-22).

## State before this change

| Fact | Where |
|---|---|
| A sighting is an entry of `sources`, `session <id>` or `session <id> project <key>`, with no date | `records.sighting`, `records.sighting_entry` |
| `released` is written once, when a global lesson is first established, and never changes | `records.standing_changes` |
| Editing a claim removes its short form; nothing counts or dates a rewording | `cmd_memory` in `mem.py` |
| The whole previous text of an edited lesson is kept in `.curation-log`; in the store that log is trimmed after 30 days and the store's git history holds older states | `store_git.TRIM_DAYS`, `records.py` (the `edit` action) |
| A lesson whose `triage` is `pending` is left out of the loaded block, and only a global lesson can await triage | `rules.choose`, `cmd_triage` in `mem.py` |
| C49 is not built: "loaded and it still happened" is read by hand from the capture log | [the loaded rules plan](../plans/2026-11-22-memory-loaded-rules.md) |

## Decisions

Rows marked *owner* are the owner's rulings of 2026-11-22; the others are the author's proposals, approved with this design.

| # | Decision | Reason |
|---|---|---|
| C64 | A sighting entry may end with the date it was recorded: `session <id> [project <key>] <YYYY-MM-DD>`. `records.sighting` is extended to read the date and to keep it out of the session key, so every function built on it (`sessions`, `projects`, `counted`, `normalized_sources`, the merge) treats a dated and an undated spelling of one session as one sighting. An entry without a date stays valid, is never rewritten on read, and is older than every version. When two spellings of one session meet, the earliest date is kept | *Owner*: date what exists (approach A below). One home for the session, its project and its date, and a merge carries the dates with the entries |
| C65 | A lesson has a list `live` of dates, one per version of its loaded text, which is its short form (C46). Today's date is appended whenever a short form is written onto a lesson and differs from the one it holds at that moment; holding none counts as different. The list has no repeated date, so two changes on one day are one version, and "version N" is the length of the list. It only grows: removing a short form adds nothing, and no command edits the list | *Owner*: a log of how many attempts were made, which says how firm the next wording has to be |
| C66 | The text of a previous version is not stored in the lesson. It is recovered from `.curation-log`: for a lesson of the store within 30 days, and from the store's git history after that; for a project lesson from the log of the project's memory folder, whose retention the builder reports | *Owner*: the last copy or the 30-day log is enough |
| C67 | A repetition is a sighting dated later than the lesson's baseline. The baseline is the last date of `live`; a lesson with a short form and an empty `live` (written before this change) uses `released`, as C49 says, and has no baseline when it has neither. This replaces "later than its `released` date" in C49. The count starts again with each version; a sighting dated on the baseline's own day does not count | *Owner* for the count per version. Same day: the session that led to a rewording is usually recorded that day |
| C68 | One repetition is a visible mark and changes nothing else. At two, the lesson is listed in a category of `mem curate`, "loaded and it still happened", with "2 times after version N" and whether it is in the loaded block or left out by the cap of C48 today; the `Triage` count of the session start text includes it. The category is computed from the record at each run: `triage` is not set, so the lesson keeps loading while it waits, and a project lesson is listed as a global one is. Only a lesson that `rules.choose` treats as ready (established, a valid short form, `load` unset, not awaiting triage) is listed | *Owner*: mark at one, back to the owner at two. Computed, not stored, because `triage: pending` would take the lesson out of the loaded block and exists only for global lessons: a lesson the agent already fails to follow should not also stop loading |
| C69 | The mark and the number of versions are shown by `mem show`, by `mem rules` and `mem rules --more`, and in the category of C68. The block printed at session start does not change | The mark is for whoever rewords the lesson; the agent that applies it needs the lesson, not its record |
| C70 | A merge keeps the union of both `live` lists, sorted, without repeated dates. The pass that writes short forms (C52, C61) appends to `live` by the rule of C65, as an edit by hand does | A merged lesson was tried as many times as its parts; the automatic path is the usual writer of a short form |
| C71 | The owner answers a listed lesson in one of three ways. Rewording it (a new short form) adds a version, which sets the count to zero. Dropping it uses the existing commands. Keeping the wording uses `mem triage accept <h>`, which writes a date `reviewed`; the lesson is listed again only after two more repetitions later than that date, while the mark of C69 keeps the full count since the version | Without the third answer a lesson kept on purpose would stay listed for ever |

## Not in this change

| Left out | Why |
|---|---|
| A text of what happened in each sighting | The session entry points to the project record that holds it, and a copied quote could carry a project's name into the global scope |
| The exceptions half of C49 ("may not hold") | No record of an exception exists yet to count; it gets its own plan |
| Knowing whether a lesson was in the loaded block of the very session of a sighting | The block is rebuilt at each session start and not logged per session. C68 says where the lesson stands today instead; revisit if triage returns lessons that were mostly left out |
| Grouping the block by topic, a digest per topic | The owner's other two ideas of 2026-11-22; planned after this |

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| A. Date the existing `sources` entries and add the `live` list | One home per fact; touches the parser that deduplication and merging use, so those paths need tests | Chosen by the owner |
| B. A separate `log` list on the lesson | Leaves the parser alone, but the session is written twice and a merge has to join two logs | Rejected |
| C. A log file beside each lesson | The lesson stays small, but two files must move, merge and sync together | Rejected |

## Known limits

- The date of a sighting is the day the pass recorded it, not the day of the session. A session swept days later (C37 of the capture design) can be dated after a version it preceded. The builder passes the transcript's own date where the caller has it, and says in the plan's results where it does not.
- A lesson with a short form that is left out of the block by the cap of C48 still collects repetitions; C68 makes that visible in the reason.

## Left to the builder

The frontmatter spelling of `live` and `reviewed`; where the repetition count is computed (one function in `records.py`, used by every place of C69); the wording of the one-repetition mark; which existing tests of `sighting`, `counted`, `normalized_sources` and the merge need a dated case.

## Checks

| Check | Proves |
|---|---|
| A store written before this change loads, counts sessions and projects, and merges as before, with no file rewritten on read | C64 is backward compatible |
| The same session added with and without a date, and with two dates, is one sighting | C64 |
| Setting a first short form, changing it, removing it and setting it again gives `live` of length 1, 2, 2, 3 | C65 |
| One dated sighting after the last version shows the mark; the second lists the lesson under "loaded and it still happened" and raises the `Triage` count, `triage` stays unset and the lesson is still in `mem rules`; a new version sets the count to zero | C67, C68 |
| A lesson with a short form, `released` and no `live` counts sightings dated after `released`; a project lesson is listed as a global one is | C67, C68 |
| After `mem triage accept` the lesson leaves the category and returns after two more repetitions | C71 |
| `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` passes; `python3 scripts/validate.py` and `claude plugin validate .` pass | Nothing else moved |
