# A digest per topic for the loaded lessons: design

Status: draft for the owner's approval · Date: 2026-11-24 · Builds C85 of [the rewording and grouping design](2026-11-23-memory-reword-and-grouping-design.md) on the grouped block (C81 to C83). The table of [the capture design](2026-11-21-memory-capture-design.md) reserves the numbers C86 to C95.

## Goal

The lessons loaded at session start say more in the same space. Under each topic a model writes one line that names the situation the topic's lessons share, and for each lesson a line that no longer repeats that situation and spends its characters on what may be worth doing and why (the owner, 2026-11-22 and 2026-11-24: more detail and less repetition in the same space; each lesson keeps a line of its own).

## State before this change

| Fact | Where |
|---|---|
| The loaded lessons can be printed under a heading per topic, each as its short form; four of the lines loaded on 2026-11-22 began with the same situation | `rules.grouped`, option `rules_layout` |
| A short form stands alone: it is printed alone by `mem rules --more`, by the flat block and by a search | C83 |
| A lesson's cases are counted per version of its short form, and the pass rewords a short form that got worse | C66, C67, C74 |
| What loads is a text derived from the records, which can be regenerated at any time | C19 |
| The session start hook has four seconds and calls no model; the background pass writes short forms with one writing session and one checking session | `hooks/session-index.sh`, `fill_auto` |
| A plugin option reaches the hooks and the background pass as an environment variable, not a `mem` command typed in a session | `plugin.json`, `hooks/session-env.sh` |

## Decisions

Rows marked *owner* are the owner's rulings of 2026-11-24; the others are the author's proposals.

| # | Decision | Reason |
|---|---|---|
| C86 | A digest is, per topic, one heading that names the situation its lessons share (at most 80 characters) and one line per lesson (at most 120 characters, the limit of a short form) that leans on the heading: it does not repeat the situation and says what may be worth doing and why | *Owner*: a heading with the situation and a line per lesson, the freed space spent on the reason. A lesson keeps a text of its own, so its cases, its versions and its rewording keep their meaning |
| C87 | The digest is written from the claims. The writing session reads, per topic, each lesson's claim, context and present short form; it never reads an earlier digest as its source | C19 and C75: a text rewritten from its own summary loses detail at each pass |
| C88 | The digest is a derived file in the plugin's data folder, not a field of the records: per topic the heading and, per lesson, its line, each with a fingerprint of what it was written from (the lesson's claim and short form; for the heading, the topic's lessons). The records are not touched | It can be thrown away and written again; an older plugin never sees it; a short form stays what stands alone (C83) |
| C89 | A lesson's line is written again only when that lesson's claim or short form changed. When a topic gains or loses a lesson, the heading is written again and the other lessons keep their lines, each checked against the new heading | The tally of a version (C67) then belongs to one loaded text: a new line comes only with a new version or a new claim |
| C90 | The first version covers global lessons. A project lesson that loads is printed under its topic with its short form, after the digest lines | A heading is written once for a topic; the lessons of one project would need a digest per project. Revisit when a project has several lessons under one topic |
| C91 | Checks, as for a short form: by code, each line passes `shortcheck` against its claim (the hedge kept, no absolute word, no link, "the user") and the limits of C86; then a checking session reads, per lesson, the claim, the heading and the line together and says whether together they ask for nothing the claim does not, in no wider a situation, with no more certainty. A refused line is left out and its lesson prints its short form; a heading that the checking session finds unfit for any of its lessons is refused, and the whole topic prints as the grouped block does | C60: what loads must not be stronger than the lesson. The fallback is always the short form, which already passed its own checks |
| C92 | At most two tries for one fingerprint of a line or of a heading; then it stays on its fallback until what it was written from changes. An unusable answer is no try, and after three such runs in a row the step waits, as the fill does | A model that keeps failing must not be paid at every compaction |
| C93 | A third value of the option `rules_layout`: `digest`. At session start it prints the grouped block with, for each topic and each lesson whose digest is present and not stale, the digest's heading and line in place of the bare topic name and the short form. The choice of lessons and its limits are those of `rules.choose`, made on the short forms; headings are outside the limit as in C82. `mem rules --layout digest` prints the same | The choice must not depend on the layout (C82). Stale or missing parts fall back without a model |
| C94 | The background pass writes the digest in a step of its own after the fill and the rewording, only when `rules_layout` is `digest`, `auto_capture` is on and the loaded rules are on. `mem-corroborate digest [--dry-run] [--sheet PATH]` runs it by hand | *Owner*: off by default. One option decides both what is written and what is printed |
| C95 | The gate before the owner turns it on: on a copy of the owner's store the step runs once with `--dry-run --sheet`. It passes when the checking session accepts at least 80% of the lines that pass the code check, every heading with at least two lessons is accepted, and the owner, reading the sheet of claim, short form, heading and line, calls no line stronger or wider than its claim. The block's length with the digest is recorded against the grouped block's | *Owner*: a sheet to read before turning it on. The measure with a real task is not repeated here: it needs what the owner chose not to grant for the grouped block (C84) |

## Not in this change

| Left out | Why |
|---|---|
| A paragraph per topic that merges its lessons | The owner chose a line per lesson; cases and rewording work per lesson |
| A digest of project lessons | C90 |
| Changing which lessons load, or the limits | C93 |
| Telling the owner of each digest written, as `mem rules --unread` does for short forms | The digest is derived and checked, and `mem rules --layout digest` shows it; revisit if the owner wants to read each change |

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| A. A derived file beside the records, printed when present and fresh | Records untouched, cheap to throw away; one more file to keep fresh | Chosen |
| B. A second field on each lesson (`digest_line`) and a record per topic for the heading | Travels with the store and its history, but a derived text would then sit in the source, change files at every regeneration and need its own curation and merge rules | Rejected |
| C. Rewriting the short forms themselves to lean on a heading | Nothing new to store, but a short form would no longer stand alone (C83) | Rejected |

## Known limits

- A line is checked against its own claim, not against the other lessons of its topic: two lines of one topic may still say nearly the same.
- The writer and the checker are the same small model, so their agreement may be correlated, as in C80.
- With the option on, an automatic run can start two more model sessions when a topic changed.
- A lesson whose topic is changed by hand gets a new line and leaves its old topic's heading stale until the next pass; meanwhile both topics print as the grouped block does.

## Checks

| Check | Proves |
|---|---|
| With `rules_layout` unset, `flat` or `grouped`, every output and the automatic run are as in 0.8.0, and no digest file is written | C93, C94 |
| A digest present and fresh prints its heading and lines; a stale line prints its short form; a refused or stale heading prints the bare topic and the short forms | C91, C93 |
| A reworded lesson gets a new line at the next pass, and the other lessons of its topic keep theirs | C89 |
| A line that drops its claim's hedge, passes 120 characters or is refused by the checking session is not kept; after two refusals nothing is asked for it until its lesson changes | C91, C92 |
| The records' files are byte-identical before and after the step | C88 |
