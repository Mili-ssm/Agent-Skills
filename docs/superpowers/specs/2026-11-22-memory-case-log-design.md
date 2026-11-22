# Case log of a lesson: design

Status: approved by the owner on 2026-11-22, rows C64 to C72 as revised the same day after the plan's pre-mortem · [plan](../plans/2026-11-22-memory-case-log.md) · Extends C49 of [the capture design](2026-11-21-memory-capture-design.md), whose table reserves these numbers.

## Goal

The plugin learns from what a loaded lesson does afterwards, in both directions. Each lesson records every later case with its date and whether the lesson worked or failed, and every version of its loaded text. From that it shows the balance of each version, marks a lesson that failed after it loaded, and hands the owner a lesson whose balance got worse, with what is needed to reword it, make it firmer or go back to an earlier wording.

Learning uses positive reinforcement as much as negative (the owner, 2026-11-22): a version that yields fewer good cases than the one before is a reason to go back, so a failure is not the only reason to change a lesson.

## State before this change

| Fact | Where |
|---|---|
| A sighting is an entry of `sources`, `session <id>` or `session <id> project <key>`, with no date and no outcome | `records.sighting`, `records.sighting_entry` |
| Capture keeps a candidate for one of eleven signals, three of them positive (`owner_approval`, `owner_request_paid_off`, `effective_practice`); the signal reaches the record only as a note in its body | the brief in `bin/mem-capture` |
| `released` is written once, when a global lesson is first established, and never changes | `records.standing_changes` |
| Editing a claim removes its short form; nothing counts, dates or keeps a rewording | `cmd_memory` in `mem.py` |
| A lesson whose `triage` is `pending` is left out of the loaded block, and only a global lesson can await triage | `rules.choose`, `cmd_triage` in `mem.py` |
| `records.update` keeps the frontmatter keys it does not know | `records.update` |
| The released parser reads `session <id> project <key> <date>` as no sighting at all | run on 2026-11-22 against `records.sighting` |

## Decisions

Rows marked *owner* are the owner's rulings of 2026-11-22; the others are the author's proposals.

| # | Decision | Reason |
|---|---|---|
| C64 | A lesson has a list `log` that only grows, one entry per case: `<YYYY-MM-DD> <session key> <outcome>`, where the session key is the normalized `session <id>` and the outcome is `worked`, `failed` or `seen`. `sources` keeps its present form and meaning, so the standing of a lesson is computed as before. A session gives at most one `worked` and one `failed` entry, and a `seen` entry only when it has no other | *Owner*: a separate list, after the pre-mortem showed that a date inside `sources` makes an older plugin read the entry as no sighting, which takes a global lesson out of the loaded block on a rollback or a second machine. An older plugin keeps a key it does not know |
| C65 | The outcome comes from the capture signal. `failed`: `owner_correction`, `failed_then_passed`, `verified_review_finding`, `delegation_failed`, `rework`, `repeated_tool_error`. `worked`: `owner_approval`, `owner_request_paid_off`, `effective_practice`. `seen`: `plan_changed_by_review`, `decision_with_reason`, and a sighting recorded with no signal. The date is the day of the session where the caller knows it (the transcript's last change), else the day of recording | *Owner*: a sighting is a reinforcement and "it still happened" speaks of failures only, and both are recorded. The mapping is the author's |
| C66 | A lesson has a list `versions` that only grows, one entry per version of its loaded text, which is its short form (C46): `<YYYY-MM-DD> <the short form>`. An entry is added whenever a short form is written onto a lesson and differs from the one it holds at that moment; holding none counts as different. Two changes on one day are one version, holding the later text. Removing a short form adds nothing. A lesson that has a short form and no `versions` (written before this change) is read as one version with its present text, dated `released` or, for a lesson without it, `created`, and is not rewritten by a read; its first change of short form writes that version before the new one, so the old wording is kept | *Owner*: a log of how many attempts were made, and the text of each kept so that going back is always possible. This replaces the earlier ruling that the 30-day curation log was enough, made before going back was a requirement |
| C67 | A case belongs to the last version dated earlier than the case; a case dated on or before the first version belongs to none. Each version has a tally, `worked` and `failed`, and a balance, `worked` minus `failed`. `seen` cases are in no tally. This replaces "later than its `released` date" in C49 | *Owner*: the count per version. A case on the day of a version is usually the session that led to it |
| C68 | One `failed` case in the present version is a visible mark and changes nothing else. A lesson is listed for the owner when its present version got worse: at least 2 `failed` cases, and either more `failed` than `worked`, or a balance below that of the version before. Listed means a category of `mem curate`, "balance got worse after loading", and a sentence of its own in the session start text. The category is computed at each run: `triage` is not set, so the lesson keeps loading while it waits, and a project lesson is listed as a global one is. Only a lesson that `rules.choose` loads or leaves out by the cap of C48 is listed | *Owner*: mark at one, to the owner when the balance is worse. The rule of "worse" is the author's, a soft means: revisit it with the first month of real tallies. Computed, not stored, because `triage: pending` takes a lesson out of the loaded block and exists only for global lessons |
| C69 | `mem show` prints each version with its date, text and tally. `mem rules` and `mem rules --more` print the present version's tally for a lesson with a `failed` case. The row of the category of C68 gives the tally and text of the present version and of the one before. The block printed at session start does not change | The record is for whoever rewords the lesson; the agent that applies it needs the lesson |
| C70 | A merge keeps the union of both `log` lists and of both `versions` lists, each sorted by date, without repeated entries. The pass that writes short forms (C52, C61) adds a version by the rule of C66, as an edit by hand does, because both go through `records.update` | A merged lesson has the history of its parts |
| C71 | The owner answers a listed lesson in one of four ways. Rewording it or making it firmer, and going back to an earlier text, are both `mem memory edit <h> --short`, which adds a version. Dropping it uses the existing commands. Keeping the wording uses `mem triage accept <h>`, with `--project-scope` for a project lesson, which writes a date `reviewed`; the lesson is listed again only when C68 holds counting the `failed` cases later than that date | Without the last answer a lesson kept on purpose would stay listed for ever |
| C72 | A second plan puts an automatic attempt before the owner: when a version gets worse, the background pass writes a new short form once, told what failed, and only if that version gets worse too does the lesson reach the owner. It may reword, not make firmer than the claim (C60). It ships behind its own gate, measured on the tallies this change collects. Until then a listed lesson goes straight to the owner | *Owner*: first an automatic attempt, then one with human feedback, in two plans. An automatic change to what loads needs its own measure, as C62 was for C52 |

## Not in this change

| Left out | Why |
|---|---|
| The automatic attempt of C72 | Its own plan, after real tallies exist |
| A text of what happened in each case | The session key points to the project record that holds it, and a copied quote could carry a project's name into the global scope |
| The exceptions half of C49 ("may not hold") | An exception (C13) is not a `failed` case; it gets its own plan |
| Knowing whether a lesson was in the loaded block of the very session of a case | The block is rebuilt at each session start and not logged per session. C68 lists only lessons that load or are cut by the cap today; revisit if listed lessons were mostly left out |
| Grouping the block by topic, a digest per topic | The owner's other two ideas of 2026-11-22; planned after this |

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| A. Date the existing `sources` entries | One home per fact, but an older plugin reads a dated entry as no sighting, and the outcome needs a second mark anyway | Chosen first, withdrawn by the owner after the pre-mortem |
| B. A separate `log` list on the lesson | Invisible to an older plugin; date, session and outcome in one entry. The session is written in `sources` and in `log`, and a merge joins two lists | Chosen |
| C. A log file beside each lesson | The lesson stays small, but two files must move, merge and sync together | Rejected |

## Known limits

- An older plugin that records a sighting adds no `log` entry, and one that rewords a lesson adds no version: those cases and versions are missing from the tallies, and nothing else breaks.
- A session swept days later (C37 of the capture design) is dated by its transcript's last change, which is the day it ended, not the day of each case in it.
- The tallies are small numbers; C68's rule compares counts, not rates per day live. `mem show` prints the days each version was live so the owner can weigh them.

## Left to the builder

Where the tallies are computed (one function in `records.py`, used by every place of C69); the wording of the mark; which existing tests need a case with a `log`.

## Checks

| Check | Proves |
|---|---|
| A store written by this change, read by the `records.py` of `main`, gives the same standing, sessions and projects for every memory | C64: an older plugin is not harmed |
| A store written before this change loads and merges as before, with no file rewritten by a read | Backward compatible |
| One session recorded twice as `failed` is one case; recorded as `failed` and later as `worked` it is two | C64 |
| Setting a first short form, changing it the next day, removing it and setting the first text again a day later gives 1, 2, 2, 3 versions, and the third holds the first text | C66 |
| A lesson with `worked` 3 and `failed` 2 in its first version is marked and not listed; with a second version at `worked` 0 and `failed` 2 it is listed and still in `mem rules`; a third version clears the listing | C67, C68 |
| After `mem triage accept` the lesson leaves the category and returns after two more `failed` cases | C71 |
| A malformed `log` or `versions` value leaves the memory readable and the session start text with its rules block | A fault in the new code must not cost the loaded rules |
