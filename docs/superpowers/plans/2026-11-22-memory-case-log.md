# Case log of a lesson Implementation Plan

Status: done · merged in #168, 2026-11-23

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lesson records each later case with its date and outcome (`worked`, `failed`, `seen`) and each version of its short form with its text, shows the tally of each version, and is listed for the owner when its present version got worse, while it keeps loading.

**Architecture:** Two frontmatter lists that only grow, `log` and `versions`, beside the untouched `sources`: an older plugin keeps keys it does not know, so it reads a store written by this change exactly as before. `records.add_sighting` records the case and `records.update` records the version, so every command and background pass gets both without code of its own. Tallies and the listing are computed from the record at each read; nothing stores them.

**Tech Stack:** Python 3 standard library and PyYAML, pytest. Engine in `plugins/memory/engine/`, commands in `plugins/memory/bin/`.

**Spec:** [the case log design](../specs/2026-11-22-memory-case-log-design.md), rows C64 to C72. Read it before any task. C72 (the automatic attempt) is a later plan: build nothing of it.

## Global Constraints

- Branch `feat/memory-case-log`; one local commit per task; no push, no pull request, no merge (each needs the owner's word).
- `sources` entries keep their present form: `session <id>` or `session <id> project <key>`. `records.sighting`, `sighting_entry`, `sessions`, `projects`, `counted`, `normalized_sources`, `standing` and `standing_changes` are not changed.
- A record file written before this change is read with the same result as before and is never rewritten by a read.
- A wrong value in `log`, `versions` or `reviewed` reads as absent and never hides the memory.
- The block printed at session start does not change by one character (C69). `triage` is not set by this change (C68).
- Comparisons of dates are exactly those of C67 and C71 ("later than"). A test that does not pass is fixed by changing its dates, never the comparison.
- The repository is public: no home path, private repository name, client name or note title in code, tests or docs.
- Fast check while working: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_case_log.py -q`. The whole suite takes about two minutes: run it once at the end of each task, `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`, and report its summary line. `test_merge_logs_both_files_and_restore_undoes_each` fails during the hour after local midnight; that is known and not yours.
- An existing test that asserts an exact output this plan changes is updated in the task that changes it and named in its report.

## Stop and report (kill criteria, from the pre-mortem of 2026-11-22)

| Observation | Action |
|---|---|
| An existing test of standing, sessions, projects or `sources` changes its result | Stop: `sources` must not move |
| `mem session-index` prints no rules block in a test where it printed one before | Stop |
| A read-only command changes the bytes of a memory file | Stop |
| Anything under the owner's real store or data folder changes during Task 8 | Stop |
| On the copy of Task 8, most listed lessons have only `worked` cases | Stop: the mapping of C65 or the rule of C68 is wrong; re-plan with the owner |

## Review Focus

| Input or condition | Expected | Pinned in |
|---|---|---|
| One session captured at each compaction, first as `failed`, later as `failed` again and as `worked` | Two cases: one `failed`, one `worked`; `observed` and `sources` as today | Task 1 |
| `log`, `versions` or `reviewed` holding a wrong value in a file | The memory loads; the bad entry is dropped, the good ones kept | Task 1, Task 2 |
| A short form holding a date-like first word, or a colon and quotes | Round-trips through `versions` unchanged | Task 2 |
| `mem restore` after an edit that added a version | `versions` returns to its earlier value, as the rest of the file does | Task 2 |
| A fault in the new code at session start (a malformed entry that slips through) | The sentence of C68 is absent; the rules block and the rest of the text are as before | Task 6 |

## File Structure

| File | Change |
|---|---|
| `plugins/memory/engine/records.py` | `log`, `versions`, `reviewed`; cases, versions, tallies, `got_worse`, `mark_words` |
| `plugins/memory/engine/capture.py` | The mapping from a capture signal to an outcome |
| `plugins/memory/engine/mem.py` | `mem confirm` and `mem remember` options, the merge, `mem show`, `mem rules`, `mem curate`, the session start text, `mem triage accept` |
| `plugins/memory/engine/corroborate.py`, `plugins/memory/bin/mem-corroborate`, `plugins/memory/bin/mem-capture` | The callers pass the outcome and the date they know |
| `plugins/memory/engine/tests/test_case_log.py` | New: every test of this plan that is not an update of an existing one |
| `plugins/memory/skills/memory-curation/SKILL.md`, `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md`, the design and plan files named in Task 8 | The new category and its four answers |

---

### Task 1: The log of cases (C64)

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `add_sighting`, `write_memory`, new functions)
- Test: `plugins/memory/engine/tests/test_case_log.py` (create)

**Interfaces:**
- Produces:
  - `OUTCOMES = ("worked", "failed", "seen")`.
  - `class Case(NamedTuple)`: `on: datetime.date`, `session: str` (the normalized `session <id>`), `outcome: str`.
  - `case(entry: str) -> Case | None`: parses `"<YYYY-MM-DD> session <id> <outcome>"`; None for anything else.
  - `case_entry(on: datetime.date, session: str, outcome: str) -> str`.
  - `Memory.log: list[str]`, default empty: the valid entries of the frontmatter list `log`, in file order.
  - `cases(memory) -> list[Case]`, sorted by date, file order kept among equal dates.
  - `add_case(memory, session: str, on: datetime.date, outcome: str, today: datetime.date) -> tuple[Memory, bool]`: `session` is any spelling of a session source. Adds the entry unless the session already has one with that outcome, or the outcome is `seen` and the session has any entry; False and no write then. `ValueError` for a text that is no session or an outcome outside `OUTCOMES`.
  - `add_sighting(memory, session, today, note=None, *, outcome: str = "seen", on: datetime.date | None = None)`: does what it does today and also `add_case` with `on or today`, in the same file write where it writes one. A session already counted still gets its case; the returned flag keeps its present meaning (a new session was counted).
  - `write_memory(..., outcome: str | None = None, on: datetime.date | None = None)`: when `outcome` is given, the record gets one entry per session among its `sources`, with that outcome and `on or today`; without it the record gets no `log` (a caller with several sessions of different outcomes adds each case afterwards, Task 4).

- [x] **Step 1: Write the failing tests**

Build memories with the helpers `test_records.py` already uses for a transcript record (read its first 60 lines; do not write a second fixture).

```python
import datetime
from engine import records  # same import form as test_records.py

D1, D2 = datetime.date(2026, 11, 20), datetime.date(2026, 11, 25)


def test_case_round_trip():
    entry = records.case_entry(D1, "session abc", "failed")
    assert entry == "2026-11-20 session abc failed"
    assert records.case(entry) == records.Case(D1, "session abc", "failed")


def test_what_is_not_a_case():
    for text in ("2026-13-40 session abc failed", "2026-11-20 session abc", "2026-11-20 session abc broken",
                 "session abc failed", "2026-11-20 a book failed", ""):
        assert records.case(text) is None
```

Then, each on a transcript memory in `tmp_path`:

| Test | Asserts |
|---|---|
| `test_add_sighting_records_the_case_of_a_new_session` | `add_sighting(m, "session s2 project <key>", D2, outcome="failed")`: `sources` gains `session s2 project <key>` exactly as today, `log` gains `2026-11-25 session s2 failed`, one file write |
| `test_the_day_of_the_session_wins_over_today` | with `on=D1`: the entry is dated D1 while `last_observed` is D2 |
| `test_a_counted_session_still_gets_its_case` | the same session again with `outcome="worked"`: returns False, `observed` and `sources` unchanged, `log` has both entries |
| `test_one_session_gives_one_case_per_outcome` | `failed` twice: one entry. `seen` after `failed`: no entry. `failed` after `seen`: both kept |
| `test_a_new_transcript_record_starts_its_log` | `write_memory(origin="transcript", sources=["session s1 project <key>"], outcome="failed", today=D1)`: `log == ["2026-11-20 session s1 failed"]`; without `outcome` the file has no `log` key |
| `test_a_wrong_log_value_reads_as_absent` | files with `log: yes`, and `log: ["2026-11-20 session a failed", "nonsense", 7]`: `error is None`; `log` is `[]` and the one valid entry |
| `test_an_old_file_is_not_rewritten_by_a_read` | a file without `log`: `load_memories` leaves its bytes unchanged and `cases(m) == []` |
| `test_sources_and_standing_ignore_the_log` | two memories that differ only in `log`: equal `sessions`, `projects`, `standing` |

- [x] **Step 2: Run them and see them fail**

Run: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_case_log.py -q`
Expected: FAIL, `records.case_entry` does not exist.

- [x] **Step 3: Implement**

`_render` writes `log` only when it is not empty. `add_sighting` computes the new `log` value and puts it in the `changes` it already builds; in its early return for a counted session it writes only when a case was added.

- [x] **Step 4: Run the tests of this file, then the whole suite**

Expected: both pass. A test that compares the whole frontmatter of a transcript record after `add_sighting` or `write_memory` now sees `log`: update it and name it in the report.

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine
git commit -m "feat(memory): a lesson logs each case with its date and outcome"
```

---

### Task 2: Versions, tallies and "got worse" (C66, C67, C68, C70, C71)

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `update`, `write_memory`, new functions)
- Modify: `plugins/memory/engine/mem.py` (`_merge_pair`)
- Test: `plugins/memory/engine/tests/test_case_log.py`

**Interfaces:**
- Consumes: `Case`, `cases`, `Memory.log` of Task 1.
- Produces:
  - `Memory.versions: list[str]`, default empty: the valid entries of the frontmatter list `versions`, each `"<YYYY-MM-DD> <short form>"`, sorted by date. `Memory.reviewed: datetime.date | None`.
  - `version_list(memory) -> list[tuple[datetime.date, str]]`: the parsed `versions`; when that is empty and the memory has a valid short form, `[(released or created, short)]` (a lesson written before this change); else `[]`.
  - `class Tally(NamedTuple)`: `number: int` (from 1), `since: datetime.date`, `text: str`, `worked: int`, `failed: int`; property `balance` = `worked - failed`.
  - `tallies(memory) -> list[Tally]`: one per version of `version_list`; a case counts for the last version whose date is earlier than the case's date.
  - `FAILED_TO_LIST = 2`.
  - `got_worse(memory) -> bool`: False without a version. With `cur` the last tally and `prev` the one before it: the `failed` cases of `cur` later than `reviewed` (all of them when `reviewed` is None) number at least `FAILED_TO_LIST`, and `cur.failed > cur.worked` or (`prev` exists and `cur.balance < prev.balance`).
  - `mark_words(memory) -> str`: `""` when the last tally has no `failed` case, else `"version 2: worked 1, failed 3"`.
  - `update(memory, today, **changes)`: when `changes` holds a `short` that is not None and differs from `memory.short`, the entry `"<today> <short>"` is added to `versions`, replacing an entry of the same day. When the file has no `versions` and holds a short form, the entry of `version_list` for that text is written first, so the wording of before this change is kept. `write_memory(..., short=...)` writes `versions` with one entry when given a short form.

- [x] **Step 1: Write the failing tests**

Each on a transcript memory in `tmp_path`, dates passed as `today`; build cases with `add_case`.

| Test | Asserts |
|---|---|
| `test_versions_grow_with_each_different_short_form` | first short form, a different one the next day, `short=None`, the first text again a day later: 1, 2, 2, 3 entries, and the third holds the first text |
| `test_two_changes_on_one_day_are_one_version_with_the_later_text` | one entry, holding the second text |
| `test_the_same_short_form_written_again_adds_no_version` | `update(m, d, short=m.short)` leaves `versions` as it was |
| `test_a_short_form_with_odd_characters_round_trips` | `"2026-01-01: check \"real\" data first"` as a short form: `version_list` returns it unchanged |
| `test_remember_with_a_short_form_starts_the_list` | `write_memory(..., short="...", today=D1)`: one version dated D1 |
| `test_a_wrong_versions_or_reviewed_value_reads_as_absent` | `versions: yes`, `versions: ["2026-11-20 text", "nonsense"]`, `reviewed: soon`: `error is None`; one valid version; `reviewed` None |
| `test_a_lesson_written_before_reads_as_one_version` | short form, `released: D1`, no `versions`: `version_list == [(D1, short)]`, file bytes unchanged; a project lesson without `released` uses `created`; without a short form `[]` |
| `test_the_first_change_of_an_old_lesson_keeps_its_old_wording` | the same file, then `update(m, D2, short="new text")`: `versions` holds two entries, the old text dated D1 and the new one dated D2 |
| `test_the_fill_pass_adds_a_version` | the apply step of the short form fill, driven as `test_fill_auto.py` drives it: the lesson it fills has one `versions` entry with the applied text (C70) |
| `test_a_case_counts_for_the_version_before_it` | version on D1: cases dated D1 − 1 and D1 are in no tally; `failed` on D1 + 1 and `worked` on D1 + 2 give `worked 1, failed 1`; `seen` counts nowhere; after a second version on D2 a case on D2 + 1 counts for version 2 only |
| `test_marked_at_one_failure_not_listed` | one `failed`: `mark_words == "version 1: worked 0, failed 1"`, `got_worse` False |
| `test_listed_when_failures_outnumber_the_good_cases` | version 1 with `worked 3, failed 2`: False; with `worked 1, failed 2`: True |
| `test_listed_when_the_balance_is_below_the_version_before` | version 1 at `worked 4, failed 1`, version 2 at `worked 3, failed 2`: True (balance 1 below 3); version 2 at `worked 5, failed 2`: False |
| `test_a_new_version_clears_the_listing` | a listed lesson gets a new short form the day after its last case: `got_worse` False, `mark_words == ""` |
| `test_reviewed_asks_for_two_more_failures` | listed; `reviewed` set to the date of its last case: False while `mark_words` still counts every case; two more `failed` later than `reviewed`: True |
| `test_merge_joins_log_and_versions` | through the `mem merge` command as `test_curation.py` drives it: both lists of the kept record are the sorted union without repeated entries |
| `test_restore_brings_versions_back` | `mem memory edit --short` that adds a version, then `mem restore`: `versions` as before the edit |

- [x] **Step 2: Run them and see them fail**

Expected: FAIL, `Memory` has no `versions`.

- [x] **Step 3: Implement**

A version entry is split at its first space. PyYAML may hand `reviewed` over as a `datetime.date` or a string: accept both, as `_date` does. `update` reads the current `versions` from the file's own frontmatter, as it does for every key. In `_merge_pair`, add `log` and `versions` to `changes` when the union differs from the kept record's list.

- [x] **Step 4: Run the tests of this file, then the whole suite**

Expected: both pass; `test_memory_edit.py`, `test_short_by.py` and `test_fill_auto.py` may compare whole frontmatter after a short form is set: update them to include `versions` and name them.

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine
git commit -m "feat(memory): versions of a lesson's short form with the tally of each"
```

---

### Task 3: Commands and capture say what happened and when (C65)

**Files:**
- Modify: `plugins/memory/engine/capture.py` (the mapping)
- Modify: `plugins/memory/engine/mem.py` (`cmd_confirm`, `cmd_remember`, `_add_sightings`, their parsers)
- Modify: `plugins/memory/bin/mem-capture` (every place that calls `mem confirm` or `mem remember` for a candidate)
- Test: `plugins/memory/engine/tests/test_case_log.py`, `test_mem_capture.py`

**Interfaces:**
- Consumes: `records.add_sighting(..., outcome=, on=)`, `records.write_memory(..., outcome=, on=)`, `records.add_case` of Task 1.
- Produces:
  - `capture.outcome(signal: str) -> str`: the mapping of C65 over `capture.SIGNALS`; an unknown signal gives `"seen"`.
  - `mem confirm` accepts `--outcome {worked,failed,seen}` (default `seen`) and `--seen-on YYYY-MM-DD` (default today; a wrong date is a usage error, exit 2); they reach `add_sighting`. When `--source` names a session that is already a source, the case is still added and the present message is unchanged.
  - `mem remember` accepts the same two options, with no default outcome; they reach `write_memory` and `_add_sightings` (which records `seen` when none is given).
  - `mem-capture`: each call for a candidate passes `--outcome` from the candidate's signal and `--seen-on` with the day of the transcript file's last change, in local time.

- [x] **Step 1: Write the failing tests**

| Test | File | Asserts |
|---|---|---|
| `test_every_signal_has_an_outcome` | `test_case_log.py` | each name of `capture.SIGNALS` maps as C65 says, and none is missing from the mapping; `"other"` gives `seen` |
| `test_confirm_records_outcome_and_day` | `test_case_log.py` | `mem confirm m:<h> --source "session s2" --outcome failed --seen-on 2026-11-20` on a transcript record: the entry `2026-11-20 session s2 failed`; a second call with `--outcome worked` adds the second case and leaves `observed` |
| `test_confirm_refuses_a_wrong_day` | `test_case_log.py` | `--seen-on 2026-13-40`: exit 2, nothing written |
| `test_remember_of_a_known_claim_passes_the_case` | `test_case_log.py` | the path through `_add_sightings`: the existing record gains the session and the `failed` case with its day |
| `test_capture_passes_signal_and_transcript_day` | `test_mem_capture.py` | a transcript file whose modification time is set with `os.utime` to three days ago, one candidate of signal `rework` for a lesson the project has and one of `effective_practice` for a new lesson: the records hold a `failed` and a `worked` case, both dated that day |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

- [x] **Step 4: Run the two test files, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory
git commit -m "feat(memory): confirm, remember and capture record whether a lesson worked or failed, and on which day"
```

---

### Task 4: Corroboration carries the cases to the general lesson (C65)

**Files:**
- Modify: `plugins/memory/engine/corroborate.py` (`Action` and where the `sighting` and `write_global` actions are built)
- Modify: `plugins/memory/bin/mem-corroborate` (where those two actions are applied)
- Test: `plugins/memory/engine/tests/test_corroborate.py`, `test_mem_corroborate.py`

**Interfaces:**
- Consumes: `records.cases` of Task 1; `mem confirm --source --outcome --seen-on` of Task 3, which adds a case to a session that is already a source.
- Produces: `Action` gains `cases: list[str]`, default empty: on a `sighting` action the `log` entries of the member records for that session; on a `write_global` action those of all its sessions. `mem-corroborate` applies a `sighting` as today and then one `mem confirm` per case; it applies a `write_global` with its present `mem remember` (no outcome, so no `log`) and then one `mem confirm` per case. The journal undoes the whole action as it does today.

- [x] **Step 1: Write the failing tests**

| Test | File | Asserts |
|---|---|---|
| `test_a_global_sighting_carries_its_cases` | `test_corroborate.py` | a member record with `log` entries `failed` and `worked` for one session: the emitted `sighting` action lists both; a member without `log` gives an empty list |
| `test_a_new_general_lesson_carries_the_cases_of_each_session` | `test_corroborate.py` | two members, one session each, one `failed` and one `worked`: the `write_global` action lists both entries |
| `test_the_pass_applies_cases_to_the_global_record` | `test_mem_corroborate.py` | after the pass, the global record has each session once in `sources` and each case in `log` with the member's date and outcome, for a `sighting` and for a `write_global`; undoing the action leaves the record as it was, or absent |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

Read how `mem-corroborate` applies and journals these two actions before changing them.

- [x] **Step 4: Run the two test files, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory
git commit -m "feat(memory): the corroboration pass carries each session's cases to the general lesson"
```

---

### Task 5: The record is shown (C69)

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`_memory_block`, `cmd_rules`)
- Test: `plugins/memory/engine/tests/test_case_log.py`

**Interfaces:**
- Consumes: `records.tallies`, `records.mark_words`, `records.Tally` of Task 2.
- Produces, as exact output:
  - `mem show`, after the `short:` line, one line per tally, and nothing for a lesson without a version:
    `version 2 since 2026-11-25 (12 days): worked 1, failed 3: <text of that version>`. The days run to the next version's date, or to today for the last.
  - `mem rules` (no option), after its present output: the heading line `Failed after it loaded:` and one line `m:<handle>\t<mark_words>` per lesson of the choice, loaded or left out, whose `mark_words` is not empty. Nothing when there is none.
  - `mem rules --more`: one more column at the end of each row, `mark_words(m)` or `-`.

- [x] **Step 1: Write the failing tests**

Drive the commands as `test_rules_session.py` does (read how it builds a store and runs `mem`). `mem.py` reads the date with `datetime.date.today()`: compute the dates of the fixtures and the expected day counts from it.

| Test | Asserts |
|---|---|
| `test_show_prints_each_version_with_its_tally` | two lines for two versions, with the day counts; none for a lesson with no short form |
| `test_show_of_a_lesson_written_before_this_change` | one line, `version 1 since <released>` |
| `test_rules_names_a_lesson_that_failed_and_the_block_is_unchanged` | the lines before `Failed after it loaded:` equal the whole output for the same store with an empty `log` |
| `test_rules_more_has_the_column` | `-` for a lesson without a failure, the words for one with |
| `test_session_start_block_is_unchanged` | the rules block inside `mem session-index` is byte-identical with and without cases |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

- [x] **Step 4: Run the tests of this file, then the whole suite**

Expected: both pass. Tests that assert the columns of `mem rules --more` or the whole output of `mem show` are updated and named.

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine
git commit -m "feat(memory): mem show and mem rules print the tally of each version of a lesson"
```

---

### Task 6: The owner's queue (C68)

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_curate`, `session_index` near the `Triage:` sentence)
- Test: `plugins/memory/engine/tests/test_case_log.py`

**Interfaces:**
- Consumes: `records.got_worse`, `records.tallies` of Task 2; the `mem show` line of Task 5; `rules.choose`, `Choice.loaded`, `Choice.left` and the reason `OVER` (existing).
- Produces:
  - One helper in `mem.py`, `_got_worse(project: Sequence[Memory], global_: Sequence[Memory], today) -> list[tuple[Memory, bool]]`: the lessons that `rules.choose`, called with both scopes and `today`, put in `loaded` or left out with `OVER`, and for which `records.got_worse` is true; the flag says "loaded".
  - `mem curate`: a category with the heading `balance got worse after loading (decide: reword it or go back with mem memory edit <h> --short, drop it with mem forget <h>, or keep the wording with mem triage accept <h>)`. Per lesson, the row `  m:<handle>  <loaded | left out by the cap>  <claim, flattened>`, then one indented line per tally of the present version and the one before, in the form of Task 5's `mem show` line. The command lists the lessons of the scopes it was asked for; the helper is still called with both.
  - Session start text: after the `Triage:` sentence, `Got worse: N loaded lesson needs a decision (mem curate).`, with `lessons need` above 1; absent at 0. It is computed in a `try` of its own: on any exception the sentence is absent and everything else is as before.

- [x] **Step 1: Write the failing tests**

Drive the commands as `test_curation.py` and `test_session_index.py` do. Date the versions and cases in the past, relative to `datetime.date.today()` (a version 10 days ago, cases after it).

| Test | Asserts |
|---|---|
| `test_curate_lists_a_lesson_that_got_worse` | absent with one failure, present with two and no good case; the row says `loaded`, with the tally line; `triage` is unset in the file and the lesson is still in `mem rules` |
| `test_curate_shows_the_version_before` | two versions: two tally lines, the earlier text in the second |
| `test_curate_lists_a_project_lesson` | the same for a project lesson that loads, in `mem curate` without `--global` |
| `test_a_lesson_that_does_not_load_is_not_listed` | `load: no`, index-only, pending and quarantined lessons that `got_worse` are absent |
| `test_session_start_counts_what_got_worse` | the sentence at 1 and at 2, absent at 0 |
| `test_a_fault_in_the_count_leaves_the_rules_block` | with `records.got_worse` patched to raise, `mem session-index` prints the same text as for a store without cases |
| `test_a_new_short_form_clears_the_listing` | `mem memory edit <h> --short "..."` on a listed lesson: gone from the category, `mem show` has one more version line |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

If the session start text passes its limit of 1500 characters in a test, stop and report it instead of cutting another sentence.

- [x] **Step 4: Run the tests of this file, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine
git commit -m "feat(memory): a lesson whose balance got worse is listed for the owner and keeps loading"
```

---

### Task 7: Keeping the wording (C71)

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_triage` and its parser)
- Test: `plugins/memory/engine/tests/test_case_log.py`

**Interfaces:**
- Consumes: `records.got_worse`, `Memory.reviewed` of Task 2; the category and the sentence of Task 6.
- Produces: `mem triage accept <h>`, for a lesson for which `got_worse` is true and `triage` is not `pending`, writes `reviewed` with the date of today, journaled as the other triage actions are, and prints `m:<handle>\tkept as worded`. A new flag `--project-scope` (argparse dest `project_scope`, not `project`, which `_find_memory` reads as a project name) makes `accept` act on the project scope, where this is its only use. A pending lesson is accepted as today; every present error message stays.

- [x] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_accept_keeps_the_wording` | exit 0, `reviewed` is today, the lesson leaves the category and the sentence; two more `failed` cases dated after today (written into the file) bring it back |
| `test_accept_of_a_pending_lesson_is_as_before` | the present output and file change, no `reviewed` |
| `test_accept_of_a_lesson_that_is_neither_keeps_its_error` | the present message and exit code |
| `test_accept_on_a_project_lesson_needs_the_flag` | `mem triage accept <h> --project-scope` works on a listed project lesson; without the flag the present error is unchanged |
| `test_restore_undoes_the_accept` | `mem restore` after it: `reviewed` is gone |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

`cmd_triage` sets `args.is_global = True` in its first line and raises "was already accepted or never awaited triage" for a lesson that is not pending: the flag has to decide the scope before that line, and the new branch has to come before that raise.

- [x] **Step 4: Run the tests of this file, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine
git commit -m "feat(memory): mem triage accept keeps the wording of a lesson that got worse"
```

---

### Task 8: An older plugin, one run on a copy, and the documents

**Files:**
- Modify: `plugins/memory/skills/memory-curation/SKILL.md` (the new category and its four answers, where the triage category is described)
- Modify: `plugins/memory/README.md` (where the loaded rules are described)
- Modify: `plugins/memory/CHANGELOG.md` (one line under `## [Unreleased]`, for users: what they will see, and that records and plugins of before keep working)
- Modify: `docs/superpowers/specs/2026-11-21-memory-capture-design.md` (the Phases row B4: the first half of C49 is built by this plan)
- Modify: `docs/superpowers/plans/2026-11-17-memory-plugin.md` (the Capture row and the "Next" paragraph of "Current state and where to resume")
- Modify: this file (`## Results`)

- [x] **Step 1: Make a disposable copy and isolate the environment**

Copy the owner's global memories folder and this project's memory folder to a temporary folder. Run every command of this task with the variables that point `mem` at the copies (`MEM_STORE`, `MEM_MEMORIES`, `MEM_PROJECT`, `MEM_DATA`: read `plugins/memory/engine/tests/conftest.py` for their meaning) and with `MEM_SETTLE_AUTO` unset, so that no background pass starts. Record a checksum of every file under the real folders before and after the task: they must be equal.

- [x] **Step 2: An older plugin reads what this one writes**

On the copy, write cases and versions with this branch's `mem` (`mem confirm --outcome`, `mem memory edit --short`). Then load every memory of the copy twice, once with this branch's `records.py` and once with `git show main:plugins/memory/engine/records.py` saved to a temporary folder, and compare `standing`, `sessions` and `projects` of each.
Expected: no difference for any memory.

- [x] **Step 3: Run the scenario**

On the copy: pick one global lesson that loads. Edit its file so that its version is dated 10 days ago, and add with `mem confirm --source --outcome failed --seen-on` two cases on two days after it. Record the output of `mem show`, `mem rules`, `mem curate --global` and `mem session-index`; compare the bytes of the files before and after these four read-only commands. Run `mem triage accept`; record `mem curate --global`. Then `mem memory edit --short` with a new wording; record `mem show`.
Expected: marked at the first case, listed at the second and still in the block; `accept` removes it from the category; the new short form shows one more version with an empty tally.

- [x] **Step 4: Write the outputs into `## Results`**

Numbers and command lines only: replace every handle, claim and path of the owner's store with a placeholder. Add how many lessons of the copy have a case of each outcome.

- [x] **Step 5: Write the documents**

One home per fact: the skill says what to do with a listed lesson, the README says the feature exists, the changelog says what changes for a user, and each links to the design for the rules. No line numbers.

- [x] **Step 6: Run the project's checks**

Run: `python3 scripts/validate.py`, `claude plugin validate .` (if the `claude` command is missing, report it as not run) and `python3 scripts/port.py --check`.
Expected: `0 errors`; the ports unchanged (the memory plugin has no port).

- [x] **Step 7: Commit**

```bash
git add plugins/memory docs
git commit -m "docs(memory): the case log in the curation skill, the README and the changelog, with one run on a copy"
```

---

### Task 9: More lessons load (the owner, 2026-11-22)

The owner raised the starting limits of C48: 16 of the lessons that met every condition existed and 6 loaded. This task is independent of Tasks 1 to 8.

**Files:**
- Modify: `plugins/memory/engine/rules.py` (`RULES_MAX`, `RULES_LIMIT`)
- Modify: the tests that assert the old limits (find them with a search for `RULES_MAX`, `RULES_LIMIT`, `900` and the number of loaded rules in `plugins/memory/engine/tests/`)
- Modify: `docs/superpowers/specs/2026-11-21-memory-capture-design.md` (a new row C73 after the row that reserves C64 to C72), `docs/adr/0023-*.md` (a kill criterion, appended as the ADR's own rules say: read the "ADRs" section of the repository's `CLAUDE.md` first), `plugins/memory/CHANGELOG.md` (one line under `## [Unreleased]`), `plugins/memory/README.md` if it states the limits

**Interfaces:**
- Produces: `RULES_MAX = 16`, `RULES_LIMIT = 2400`. `MORE_LIMIT`, `PROJECT_FIRST` and the 1500 characters of the rest of the session start text are unchanged.

- [x] **Step 1: Change the tests that state the limits to 16 rules and 2400 characters, and add `test_sixteen_rules_load_and_the_seventeenth_is_left_out` in `test_rules.py`**

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Change the two constants**

- [x] **Step 4: Write the row and the criterion**

Row C73: "The limits of C48 are raised to 16 loaded rules and 2400 characters of rule lines (the owner, 2026-11-22); the other limits of C48 stay." Reason: "16 lessons met every condition and 6 loaded; the lessons left out are reached only when an agent asks by topic. Unmeasured: the tallies of C67 are the measure." Kill criterion for the ADR: "Lower the limits again if, a month after the release that carries C73, the lessons that load only because of it show more `failed` than `worked` cases in their tallies, or the owner reports that loaded lessons are ignored more often."

- [x] **Step 5: Run the whole suite and `python3 scripts/validate.py`**

- [x] **Step 6: Commit**

```bash
git add plugins/memory docs
git commit -m "feat(memory): up to 16 lessons and 2400 characters load at session start"
```

---

## Results

Run on 2026-11-23 on a disposable copy (`<copy>`) of the global memories folder and of this project's memory folder, with the engine of commit `8f1d8c5` (the engine files are unchanged up to the later documentation commits; `git rev-parse --short HEAD` printed `aa5d9b2` at the end). Every command ran as `env -u MEM_SETTLE_AUTO -u MEM_CLAUDE -u MEM_SETTLE_CLAUDE -u MEM_SETTLE_MINUTES MEM_STORE=<copy>/store MEM_MEMORIES=<copy>/store/memories MEM_PROJECT=<copy>/proj MEM_DATA=<copy>/data XDG_CONFIG_HOME=<copy>/cfg XDG_DATA_HOME=<copy>/share HOME=<copy>/home plugins/memory/bin/mem ...`; `mem stats` reported the store under `<copy>`; no background pass started.

### (A) An older plugin reads what this branch writes

Written with this branch's `mem`: `mem confirm <handle> --global --source "session <id> project <key>" --outcome <failed|worked|seen> --seen-on <date>` (3 cases, 3 lessons of origin transcript) and `mem memory edit <handle> --global --short "<short form>" --user-read` (3 edits). Then every memory of the copy was loaded with the `records.py` of this branch and with the one of the commit where the branch left `dev` (`61177f6`, `git show 61177f6:plugins/memory/engine/records.py`). The `records.py` of `main` has no `standing`, `sessions` or `projects` yet, so it cannot be the older side of this comparison.

| Scope | Memories compared | With `log` / `versions` | Load errors (old / new) | Differences in `standing`, `sessions`, `projects`, `sources` |
|---|---|---|---|---|
| global | 219 | 2 / 2 | 0 / 0 | 0 |
| project | 191 | 0 / 0 | 0 / 0 | 0 |
| total | 410 | | 0 / 0 | 0 |

### (B) The scenario on one global lesson that loads

Setup: its file got `versions: ["<today minus 10 days> <short form>"]`; two cases `failed` on `<today minus 5 days>` and `<today minus 3 days>` from two new sessions in two projects.

| Step | Command | Result |
|---|---|---|
| 1 | `mem show <handle>`, `mem rules` | no mark yet: `version 1 since <date> (10 days): worked 0, failed 0: <short form>`; the rule is in the block |
| 2 | `mem confirm <handle> --global --source "session <id> project <key>" --outcome failed --seen-on <date 1>` | `observed 2` |
| 3 | `mem show <handle>`; `mem rules` | `version 1 since <date> (10 days): worked 0, failed 1: <short form>`; `mem rules` still prints the rule and adds under `Failed after it loaded:` the line `<handle>  version 1: worked 0, failed 1` |
| 4 | `mem confirm ... --outcome failed --seen-on <date 2>` | `observed 3` |
| 5 | `mem show <handle>`; `mem rules` | tally `worked 0, failed 2`; the rule is still in the block, mark `version 1: worked 0, failed 2` |
| 6 | `mem curate --global` | new category `balance got worse after loading (decide: reword it or go back with mem memory edit <h> --short, drop it with mem forget <h>, or keep the wording with mem triage accept <h>)` lists `<handle>  loaded  <claim>` and under it `version 1 since <date> (10 days): worked 0, failed 2: <short form>` |
| 7 | `mem session-index` | the first line ends with `Got worse: 1 loaded lesson needs a decision (mem curate).`; the rules block is unchanged in form |
| 8 | sha256 of every file of the copy before and after steps 5 to 7 | identical |
| 9 | `mem triage accept <handle>` | `<handle>  kept as worded`; the file gets `reviewed: '<today>'` |
| 10 | `mem curate --global` | the category is gone; the lesson is still in `mem rules` (rule line and mark) |
| 11 | `mem memory edit <handle> --global --short "<new short form>" --user-read` then `mem show <handle>` | `short:` is the new text; two version lines: `version 1 since <date> (10 days): worked 0, failed 2: <old short form>` and `version 2 since <today> (0 days): worked 0, failed 0: <new short form>` |

All the expectations held. One detail: the mark of `mem rules` appears at the first `failed` case (step 3), the line in `mem curate` and the sentence of `mem session-index` only at the second (step 6 and 7), as the rule of C68 asks.

### (C) The copy after the scenario

| Count over the 132 lessons of the copy (410 memories) | Lessons |
|---|---|
| with at least one `worked` case | 1 |
| with at least one `failed` case | 2 |
| with at least one `seen` case | 1 |
| with at least one version in `versions` | 3 |
| listed as "balance got worse after loading" (`mem curate`, any scope) | 0 (1 before `triage accept`) |

The copy held no case or version before this run, so these counts are the ones the run wrote, not a sample of the real store.

### The real folders

sha256 of every file under the real global memories folder (222 files) and under this project's memory folder (192 files), taken before the first command and after the last one: identical, no difference.
