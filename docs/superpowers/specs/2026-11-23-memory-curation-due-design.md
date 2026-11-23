# The `Curation due` count and the noise of the curation queue: design

Status: approved by the owner on 2026-11-23 (the two choices below) · [plan](../plans/2026-11-23-memory-curation-due.md) · The table of [the capture design](2026-11-21-memory-capture-design.md) reserves the numbers C98 to C107. C101 was narrowed and C106, C107 added after the plan's pre-mortem.

## Goal

The count that every session start prints tells how many decisions a curation pass would find that no pass has seen yet, and the queue that `mem curate` prints lists those decisions without noise. On 2026-11-23 the count said 164 while the queue held 13 items, 11 of which ask for nothing (a memory-curator pass of 2026-11-23 found this and four more kinds of noise).

## State before this change

| Fact | Where |
|---|---|
| The count is the live memories created after the folder's last pass (counted only from 10, or from 1 once the pass is 14 days old) plus the active memories that expired since that pass | `records.curation_due` |
| `mem curate` does not list new memories, so the count's main part has no item in the queue; only `mem curate --done` resets it, and the automatic curation never runs `--done` | `cmd_curate`, `bin/mem-auto` |
| The last passes are dated 2026-11-19 (this project) and 2026-11-20 (global), and about 150 memories were written since | `curated.json` in the data folder |
| Same-or-opposite pairs are found by comparing every pair of live claims of a folder: 0.3 seconds for the 434 memories of 2026-11-23, 3.8 seconds for 1302. The session start hook stops at 4 seconds and then prints nothing, rules included | `records.pairs`, `hooks/session-index.sh` |
| The pairs block prints a memory once per pair it is in, and `differ in` lists every word found in one claim only, stopwords included | `cmd_curate`, `records.differing_words` |
| Two state memories of one project written on following days pair as same or opposite until someone runs `mem supersede <old> <new>` | `records.pairs` |
| Triage and lessons that got worse have their own session start lines (`Triage:`, `Got worse:`) | `session_index` |

## Decisions

Rows marked *owner* are the owner's choices of 2026-11-23; the others are the author's proposals.

| # | Decision | Reason |
|---|---|---|
| C98 | The count is the number of decision items of a folder's queue that its last pass did not list. Decision items: written again after being refuted, same or opposite, newer state (C103), expired, seen 3 times or more, not confirmed in 90 days. Not counted: lines that only inform (in quarantine, short forms nobody read, project syntheses), memories from a transcript not confirmed yet (their answer is to leave them), and triage and got-worse items, which keep their own lines. A new memory no longer counts by itself | *Owner*: count only new decisions. A count that matches what the queue asks for is followed; a pass that decides to leave an item clears it |
| C99 | The line names the parts: `Curation due: 4 items (2 same or opposite, 1 expired, 1 seen often) (run mem curate after the current task).` Parts in the queue's order, empty parts left out | The reader sees what the pass is for before running it |
| C100 | `mem curate --done` also records, per folder, the keys of the decision items the queue held: `refuted:<live>|<refuted>`, `pair:<a>|<b>` (handles sorted), `state:<old>|<new>`, `expired:<h>`, `seen:<h>`, `stale:<h>`. They go to a new file `curated-items.json` beside `curated.json`, which keeps its format so an older plugin reads it as before. Each pass replaces the folder's keys | A key names a decision, not a memory: a pair that comes back with a new partner is a new decision |
| C101 | At session start the pair kinds (refuted again, same or opposite, newer state) are searched only among pairs with at least one memory changed on or after the folder's last pass (created on or after it, or its file modified on or after it), or among all when there is no pass. One budget of 150,000 claim comparisons covers both folders and both searches; the newest changed memories are compared first, and when the budget runs out the rest are not compared. When it ran out and N is above 0 the line reads `Curation due: at least N items (...) (run mem curate after the current task).`; when N is 0 no line is printed. `mem curate` still searches every pair | The session start text must not be lost to the hook's 4 seconds: the work grows with changed memories times live memories, not with live memories squared. A pair of two memories unchanged since the pass was there at the pass; an edit, a restore or a revival writes the file, so its memory counts as changed. A line at 0 would start a curator at every session for nothing (pre-mortem, 2026-11-23) |
| C106 | `mem remember` no longer prints the number of new memories since the last pass. Its list of related memories already names the pair a new memory makes, and the session start line names the rest | The nudge counted new memories, which C98 no longer treats as decisions |
| C107 | `mem curate --done` prints `recorded <K> items` per folder | The session that ran the pass can compare K with the queue it read; a memory written by a background step between the two would make them differ |
| C102 | The same-or-opposite block groups pairs by memory: the memory in the most pairs first, its line, then one indented line per partner with its `differ in`; each pair printed once | *Owner*: the curator read one handle several times |
| C103 | Two live state memories of the same folder that pair are listed in a category of their own, not as same or opposite: `newer state of the same project? (decide: mem supersede <old> <new>, or mem distinct <a> <b>)`, one line per pair, `m:<old>  ->  m:<new>`, older by `created`, then by handle. Nothing is superseded without a command | *Owner*: a proposal, not an automatic change. One project may hold state memories about different work |
| C104 | `differ in` leaves out the stopwords of `records.STOPWORDS` except negations (`_NEGATIONS`), and keeps digits; when nothing is left it reads `differ in: wording only` | *Owner*: the words were mostly stopwords. Negations and numbers are what make two claims opposite |
| C105 | The seen-often category says what promotion makes: `seen 3 times or more: general enough for a note in the store? (mem promote <h>)` | The curator pass of 2026-11-23 read promotion as making a memory global |

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| A. Count the decision items not listed at the last pass, with keys recorded by `--done` | One more derived file; a pass that leaves items clears the count | Chosen (owner) |
| B. Count every decision item of the queue | Always equal to the queue, but an item left on purpose keeps the line on at every session | Rejected (owner) |
| C. Keep the count of new memories and list them in the queue | The numbers match, but the queue grows to about 160 lines with nothing to decide on most | Rejected (owner) |
| Automatic supersession of an older state memory | Less friction, but it changes memories nobody read and one project may hold states of different work | Rejected (owner) |

## Not in this change

| Left out | Why |
|---|---|
| The automatic curation recording `--done` | It applies only the safe subset; what it leaves is for the main session to decide |
| Making the full pair search faster | `mem curate` runs on request and takes 0.6 seconds today; revisit when it passes a few seconds |
| The threshold of the automatic curation (`auto_curation_threshold`) | It counts new records for its own purpose, by `mem curate --new-since` |
| The lessons and pitfalls of 2026-11-17 to 2026-11-23 reach "not confirmed in 90 days" together around 2027-02-15, and the count will name them | They are decisions the queue asks for (C98); revisit if that wave proves to be noise |

## Checks

| Check | Proves |
|---|---|
| A folder with 150 new memories and no decision item prints no `Curation due` line | C98 |
| After `mem curate --done`, the same queue gives no count; one new pair or one new expiry gives 1, named in the line | C98, C99, C100 |
| A store without `curated-items.json` and with an older `curated.json` reads as before, and an older plugin reads the `curated.json` written by `--done` | C100 |
| The session start search never makes more than 150,000 comparisons in all; with 2000 memories and the budget nearly used, session start stays under 1 second; past the budget a found item prints `at least` and none prints no line | C101 |
| A pair made by `mem memory edit`, `mem restore` or `mem confirm --until` between two memories older than the pass is counted | C101 |
| `mem curate --done` on an unchanged store leaves no line, whatever mix of superseded, unconfirmed, quarantined, expired and state memories it holds | C98, C100 |
| A memory in three pairs prints once with three partner lines; two state memories of one project appear only under the newer-state category | C102, C103 |
| `differ in` of two claims that differ by "the" and "not" lists only `not` | C104 |
