# Case log of a lesson Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lesson records the date of each sighting and of each version of its short form, shows "K repetitions after version N", and is listed for the owner at two repetitions while it keeps loading.

**Architecture:** The date rides on the existing `sources` entry and is read by `records.sighting_date`; `records.sighting` keeps its return type, so the functions built on it are unchanged. A frontmatter list `live` is appended in the two functions that write a short form (`records.update`, `records.write_memory`), so every command and the background pass get it without their own code. The repetition count is computed from the record at each read; nothing stores it.

**Tech Stack:** Python 3 standard library and PyYAML, pytest. Engine in `plugins/memory/engine/`, commands in `plugins/memory/bin/`.

**Spec:** [the case log design](../specs/2026-11-22-memory-case-log-design.md), rows C64 to C71. Read it before any task.

## Global Constraints

- Branch `feat/memory-case-log`; one local commit per task; no push, no pull request, no merge (each needs the owner's word).
- A record file written before this change is read with the same result as before and is never rewritten by a read.
- `records.sighting(source)` keeps returning `tuple[str, str | None] | None`: the session key and the project key.
- One session is one sighting, whatever its date and spelling.
- The block printed at session start does not change by one character (C69).
- `triage` is not set by this change (C68).
- The repository is public: no home path, private repository name, client name or note title in code, tests or docs.
- Fast check while working: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_case_log.py -q`. The whole suite takes about two minutes: run it once at the end of each task, `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`, and report its summary line. `test_merge_logs_both_files_and_restore_undoes_each` fails during the hour after local midnight; that is known and not yours.
- Existing tests that assert an exact output this plan changes are updated in the task that changes it, and named in its report.

## Review Focus

| Input or condition | Expected | Pinned in |
|---|---|---|
| A session id that is itself a date, `session 2026-11-22` | Stays a session with that id and no date, as before | Task 1 |
| A last token that looks like a date and is not one, `session abc 2026-13-40` | Stays part of the session id, as before | Task 1 |
| A session recorded before a version and seen again after it (a long session captured at each compaction) | Keeps its earliest date and is never a repetition of the later version | Task 1, Task 2 |
| `live` or `reviewed` holding a wrong value in a file | The memory loads; the bad value reads as absent | Task 2 |
| `mem restore` after an edit that added a version | `live` returns to its earlier value, as the rest of the file does | Task 2 |

## File Structure

| File | Change |
|---|---|
| `plugins/memory/engine/records.py` | The date of a sighting entry, the fields `live` and `reviewed`, `baseline`, `versions`, `repetitions`, `still_happens`, `repeat_words` |
| `plugins/memory/engine/mem.py` | `mem show`, `mem rules`, `mem curate`, the session start text, `mem triage accept`, the merge |
| `plugins/memory/engine/corroborate.py`, `plugins/memory/bin/mem-capture` | The callers pass the date they know |
| `plugins/memory/engine/tests/test_case_log.py` | New: every test of this plan that is not an update of an existing one |
| `plugins/memory/skills/memory-curation/SKILL.md`, `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md`, the two design and plan files of Task 5 | The new category and its three answers |

---

### Task 1: A sighting entry carries its date (C64)

**Files:**
- Modify: `plugins/memory/engine/records.py` (`sighting`, `sighting_entry`, `normalized_sources`, `add_sighting`, and a new `sighting_date`)
- Test: `plugins/memory/engine/tests/test_case_log.py` (create)

**Interfaces:**
- Produces:
  - `sighting(source: str) -> tuple[str, str | None] | None`: unchanged type; a last token that is a valid ISO date, after at least one token of session id, is left out of the key.
  - `sighting_date(source: str) -> datetime.date | None`: that date, or None for an entry without one or a text that is no sighting.
  - `sighting_entry(session: str, key: str | None, date: datetime.date | None = None) -> str`: `"<session>[ project <key>][ <YYYY-MM-DD>]"`.
  - `add_sighting(memory, session, today, note=None)`: signature unchanged. A new session is stored with the date its entry carries, else with `today`.
  - `normalized_sources(sources)`: one entry per session, carrying the earliest date found among its spellings, or none when no spelling has one.

- [ ] **Step 1: Write the failing tests**

Build the memory with the helpers `test_records.py` already uses for a transcript record (read its first 60 lines and reuse them, do not write a second fixture).

```python
import datetime
from engine import records  # same import form as test_records.py

D1, D2 = datetime.date(2026, 11, 20), datetime.date(2026, 11, 25)
KEY = "0123456789ab"


def test_a_dated_entry_is_the_same_session_as_an_undated_one():
    assert records.sighting("session abc 2026-11-20") == ("session abc", None)
    assert records.sighting(f"session abc project {KEY} 2026-11-20") == ("session abc", KEY)
    assert records.sighting_date(f"session abc project {KEY} 2026-11-20") == D1
    assert records.sighting_date("session abc") is None
    assert records.sighting_date("a book, page 3") is None


def test_a_date_alone_or_a_wrong_date_stays_in_the_session_id():
    assert records.sighting("session 2026-11-20") == ("session 2026-11-20", None)
    assert records.sighting_date("session 2026-11-20") is None
    assert records.sighting("session abc 2026-13-40") == ("session abc 2026-13-40", None)


def test_entry_round_trip():
    assert records.sighting_entry("session abc", KEY, D1) == f"session abc project {KEY} 2026-11-20"
    assert records.sighting_entry("session abc", None, D1) == "session abc 2026-11-20"
    assert records.sighting_entry("session abc", KEY) == f"session abc project {KEY}"


def test_normalized_sources_keeps_one_entry_per_session_with_the_earliest_date():
    out = records.normalized_sources(["session abc 2026-11-25", f"session abc project {KEY} 2026-11-20", "session z"])
    assert out == [f"session abc project {KEY} 2026-11-20", "session z"]
    assert records.normalized_sources(["session abc", "session abc 2026-11-25"]) == ["session abc 2026-11-25"]
```

Add three tests on a transcript memory written to `tmp_path`:

- `test_add_sighting_dates_a_new_session_with_today`: `add_sighting(m, "session s2", D2)` stores `"session s2 2026-11-25"`.
- `test_add_sighting_keeps_the_date_the_entry_carries`: `add_sighting(m, "session s2 2026-11-20", D2)` stores `"session s2 2026-11-20"`.
- `test_a_counted_session_is_not_counted_again_under_a_later_date`: after the first, `add_sighting(m, "session s2 2026-11-25", D2)` returns `(memory, False)`, `observed` is unchanged and the stored date is still `2026-11-20`; and a counted session that gains a project keeps its date.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_case_log.py -q`
Expected: FAIL, `sighting_date` does not exist.

- [ ] **Step 3: Implement**

In `sighting`, split the date off the normalized text before any other test, with one helper used by `sighting` and `sighting_date`, so the two cannot disagree. Parse the date with `datetime.date.fromisoformat` on a token that matches `\d{4}-\d{2}-\d{2}` exactly. Where `normalized_sources` and `add_sighting` rebuild an entry with `sighting_entry(*f)`, pass the date as well; grep the engine and `bin/` for every other `sighting_entry(` call and leave those that build a new entry from a caller's values (Task 4 owns them).

- [ ] **Step 4: Run the tests of this file, then the whole suite**

Expected: this file passes; the suite's summary line shows no new failure. An existing test that asserted an undated entry after `add_sighting` now sees a date: update it to the dated entry and name it in the report.

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine/records.py plugins/memory/engine/tests
git commit -m "feat(memory): a sighting entry carries the date it was recorded"
```

---

### Task 2: Versions of the loaded text and the repetition count (C65, C67, C70, C71)

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `update`, `write_memory`, new functions)
- Modify: `plugins/memory/engine/mem.py` (`_merge_pair`)
- Test: `plugins/memory/engine/tests/test_case_log.py`

**Interfaces:**
- Consumes: `sighting`, `sighting_date` of Task 1.
- Produces:
  - `Memory.live: list[datetime.date]` (default empty) and `Memory.reviewed: datetime.date | None`, read from and written to the frontmatter keys `live` (a list of ISO dates) and `reviewed`.
  - `REPEAT_TRIAGE = 2`.
  - `baseline(memory) -> datetime.date | None`: `live[-1]` when `live` is not empty; else `released` when the memory has a valid short form; else None.
  - `versions(memory) -> int`: `len(live)`, or 1 when `live` is empty and `baseline` is not None, or 0.
  - `repetitions(memory, since: datetime.date | None = None) -> int`: the distinct sessions whose date is later than the later of `baseline(memory)` and `since`; 0 without a baseline. A session without a date never counts.
  - `still_happens(memory) -> bool`: `repetitions(memory, memory.reviewed) >= REPEAT_TRIAGE`.
  - `repeat_words(memory) -> str`: `""` at zero repetitions, else `"1 repetition after version 2"` or `"3 repetitions after version 2"`, counted from the baseline only.
  - `update(memory, today, **changes)`: when `changes` holds a `short` that is not None and differs from `memory.short`, `today` is added to `live` (no repeated date). `write_memory(..., short=...)` writes `live: [today]` when it is given a short form.

- [ ] **Step 1: Write the failing tests**

Each on a transcript memory in `tmp_path`, with dates passed as `today`:

| Test | Asserts |
|---|---|
| `test_live_grows_with_each_different_short_form` | first short form, a different one the next day, removal (`short=None`), the first text again a day later: `len(live)` is 1, 2, 2, 3 |
| `test_two_changes_on_one_day_are_one_version` | two different short forms with the same `today`: `len(live) == 1`, `versions == 1` |
| `test_the_same_short_form_written_again_adds_no_version` | `update(m, d, short=m.short)` leaves `live` as it was |
| `test_remember_with_a_short_form_starts_the_list` | `write_memory(..., short="...", today=D1)` gives `live == [D1]` |
| `test_a_wrong_live_or_reviewed_value_reads_as_absent` | files with `live: yes`, `live: [2026-11-20, nonsense]`, `reviewed: soon`: the memory loads with `error is None`; `live` is `[]`, `[D1]`; `reviewed` is None |
| `test_an_old_file_is_not_rewritten_by_a_read` | a file without `live`: `load_memories` leaves its bytes unchanged |
| `test_repetitions_count_sessions_dated_after_the_last_version` | `live == [D1]`; entries dated D1 − 1 day, D1 and undated count 0; one dated D2 counts 1; a second version on D2 sets the count to 0 |
| `test_a_lesson_without_live_counts_from_released` | short form, `released: D1`, no `live`: an entry dated D2 counts 1 and `versions == 1`; without a short form the count is 0 and `versions == 0` |
| `test_still_happens_at_two_and_again_two_after_a_review` | two entries after the baseline: True; `reviewed` set to the later entry's date: False while `repeat_words` still says `"2 repetitions after version 1"`; two more after it: True |
| `test_a_session_seen_before_and_after_a_version_is_no_repetition` | session `s1` dated D1 − 1, version on D1, `add_sighting` of `s1` dated D2: `repetitions == 0` |
| `test_merge_joins_the_live_lists` | through the `mem merge` command as `test_curation.py` drives it: `live` of the kept record is the sorted union without repeated dates |
| `test_restore_brings_live_back` | `mem memory edit --short` that adds a version, then `mem restore`: `live` is as before the edit |

- [ ] **Step 2: Run them and see them fail**

Expected: FAIL, `Memory` has no `live`.

- [ ] **Step 3: Implement**

`_parse` reads `live` as a sorted list without repeats of the entries that are dates or ISO date strings, and drops the others; PyYAML may hand over `datetime.date` objects or strings, accept both. `_render` and `update` write ISO strings. `update` reads the current list from the file's own frontmatter, as it does for every other key. In `_merge_pair`, add `live` to `changes` when the two lists differ from the kept one.

- [ ] **Step 4: Run the tests of this file, then the whole suite**

Expected: both pass; `test_memory_edit.py` and `test_short_by.py` may assert whole frontmatter after a short form is set: update them to include `live` and name them in the report.

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine plugins/memory/engine/tests
git commit -m "feat(memory): versions of a lesson's short form and repetitions after the last one"
```

---

### Task 3: The mark, the category and the answer (C68, C69, C71)

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`_memory_block`, `cmd_rules`, `cmd_curate`, the session start text near the `Triage:` sentence, `cmd_triage` and its parser)
- Test: `plugins/memory/engine/tests/test_case_log.py`

**Interfaces:**
- Consumes: `records.versions`, `records.repetitions`, `records.still_happens`, `records.repeat_words`, `Memory.live`, `Memory.reviewed` of Task 2; `rules.choose` and its `Choice.loaded` and `Choice.left` (existing).
- Produces, as exact output:
  - `mem show`: after the `short:` line, `versions: 2 (2026-11-20, 2026-11-25)` when `live` is not empty, then the line `repeat_words(m)` when it is not empty.
  - `mem rules` (no option): after its present output, one line per lesson of the choice (loaded or left out) with at least one repetition: `m:<handle>\t<repeat_words>`, under the heading line `Loaded and it still happened:`. Nothing is printed when no lesson has one.
  - `mem rules --more`: one more column at the end of each row, `repeat_words(m)` or `-`.
  - `mem curate`: a category for the lessons `listed` (below), heading `loaded and it still happened (decide: reword it with mem memory edit <h> --short, drop it with mem forget <h>, or keep the wording with mem triage accept <h>)`, one row each: `  m:<handle>  <repeat_words>, <loaded | left out by the cap>  <claim, flattened>`.
  - Session start text: after the `Triage:` sentence, `Still happening: N loaded lesson repeats after it loaded (mem curate).` with `lessons repeat` for N above 1; absent at N = 0. It counts project and global lessons together.
  - `mem triage accept <h>`: for a lesson that `still_happens` and is not `pending`, writes `reviewed: <today>` and prints `m:<handle>\tkept as worded`. A new flag `--project` makes `accept` act on the project scope, where this is its only use. A pending lesson is accepted as today.
- `listed`: a lesson that `rules.choose` put in `loaded`, or in `left` with the reason of the cap (`OVER`), and for which `records.still_happens` is true.

- [ ] **Step 1: Write the failing tests**

Drive the commands as `test_rules_session.py` and `test_curation.py` do (read how each builds a store and runs `mem`).

| Test | Asserts |
|---|---|
| `test_show_prints_versions_and_the_mark` | the two lines above, and neither for a lesson with no `live` and no repetition |
| `test_rules_lists_a_lesson_with_one_repetition_and_the_block_is_unchanged` | the lines before `Loaded and it still happened:` equal the output of the same store with the sighting removed |
| `test_session_start_block_is_unchanged` | the rules block inside `mem session-index` is byte-identical with and without repetitions |
| `test_curate_lists_at_two_not_at_one` | absent with one repetition, present with two; the row says `loaded`; `triage` is still unset in the file and the lesson is still in `mem rules` |
| `test_curate_lists_a_project_lesson` | the same for a project lesson that loads, with `mem curate` and no `--global` |
| `test_a_lesson_that_does_not_load_is_not_listed` | `load: no`, index-only, pending and quarantined lessons with two repetitions are absent |
| `test_session_start_counts_still_happening` | the sentence with N = 1 and N = 2, absent at 0 |
| `test_accept_keeps_the_wording` | exit 0, `reviewed` is today, the lesson leaves the category and the count; after two more dated sightings it is back |
| `test_accept_on_a_project_lesson_needs_the_flag` | `mem triage accept <h> --project` works; without the flag the present error is unchanged |
| `test_a_new_short_form_clears_the_listing` | `mem memory edit <h> --short "..."` on a listed lesson: gone from the category, `versions` one higher |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

One helper in `mem.py` returns the `listed` lessons for the loaded project and global memories; `cmd_curate` and the session start text both call it, so the count and the category cannot disagree. `mem curate` runs on one scope: list the lessons of that scope only. If the session start text passes its own limit of 1500 characters in a test, stop and report it instead of cutting another sentence.

- [ ] **Step 4: Run the tests of this file, then the whole suite**

Expected: both pass. Tests that assert the columns of `mem rules --more` or the whole output of `mem curate` are updated and named.

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine plugins/memory/engine/tests
git commit -m "feat(memory): a lesson that still happens after it loaded is marked at one repetition and listed at two"
```

---

### Task 4: The callers pass the date they know

**Files:**
- Modify: `plugins/memory/bin/mem-capture` (the two places that build `--source` for `mem confirm` and `mem remember`)
- Modify: `plugins/memory/engine/corroborate.py` (where a project record's sessions become entries of the global record)
- Test: `plugins/memory/engine/tests/test_mem_capture.py`, `plugins/memory/engine/tests/test_corroborate.py`

**Interfaces:**
- Consumes: `records.sighting_entry(session, key, date)`, `records.sighting_date` of Task 1.
- Produces: no new name. A session captured from a transcript is recorded with the date of the transcript file's last change, in local time; an entry copied from a project record to a global one keeps the date it had, or none.

- [ ] **Step 1: Write the failing tests**

- `test_capture_dates_a_sighting_with_the_transcripts_date` in `test_mem_capture.py`: a transcript file whose modification time is set with `os.utime` to three days ago; after a run with `--write`, the entry on the record ends with that day, not today. One case through `mem confirm` (a lesson the project already has) and one through `mem remember` (a new lesson).
- `test_a_global_entry_keeps_the_date_of_the_project_entry` in `test_corroborate.py`: a project record with `session a project <key> 2026-11-20`; the action that the pass emits for the global record names `session a project <key> 2026-11-20`. And an undated project entry gives an undated global one.

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

`mem remember` and `mem confirm` already pass `--source` through `records.sighting` and `add_sighting`, which keep a date the entry carries (Task 1): check it with the tests before changing either command, and change them only if a date is lost on the way.

- [ ] **Step 4: Run the two test files, then the whole suite**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/bin/mem-capture plugins/memory/engine
git commit -m "feat(memory): capture and corroboration record a sighting with the date of its session"
```

---

### Task 5: One run on a copy of a real store, and the documents

**Files:**
- Modify: `plugins/memory/skills/memory-curation/SKILL.md` (the new category and its three answers, in the table or list where the triage category is described)
- Modify: `plugins/memory/README.md` (one row or sentence where the loaded rules are described)
- Modify: `plugins/memory/CHANGELOG.md` (one line under `## [Unreleased]`, written for users: what they will see, and that records written before the change keep working)
- Modify: `docs/superpowers/specs/2026-11-21-memory-capture-design.md` (the Phases row B4: usefulness, first half, built)
- Modify: `docs/superpowers/plans/2026-11-17-memory-plugin.md` (the Capture row and the "Next" paragraph of "Current state and where to resume")
- Modify: this file (`## Results`)

- [ ] **Step 1: Run the scenario on a disposable copy**

Copy the default store's `memories` folder to a temporary folder (never write to the real one; find the variables that point `mem` at another store and another global memories folder in `plugins/memory/engine/tests/conftest.py`). On the copy: pick one global lesson that loads; add two sightings dated tomorrow and the day after with `mem confirm --source`; record the output of `mem show`, `mem rules`, `mem curate --global` and `mem session-index`; run `mem triage accept`; record `mem curate --global` again; then `mem memory edit --short` with a new wording and record `mem show`.

Expected: the mark and the category appear at the second sighting, the lesson stays in the block, `accept` removes it from the category, the new short form shows one more version and no repetition.

- [ ] **Step 2: Write the outputs into `## Results`**

Numbers and command lines only: replace every handle, claim and path of the owner's store with a placeholder.

- [ ] **Step 3: Write the documents**

One home per fact: the skill says what to do with a listed lesson, the README says the feature exists, the changelog says what changes for a user, and each links to the design for the rules. No line numbers.

- [ ] **Step 4: Run the project's checks**

Run: `python3 scripts/validate.py` and `claude plugin validate .` (the `claude` binary is not on `PATH` on the owner's machine: if the command is missing, report it as not run), then `python3 scripts/port.py --check`.
Expected: `0 errors`; the ports unchanged (the memory plugin has no port).

- [ ] **Step 5: Commit**

```bash
git add plugins/memory docs
git commit -m "docs(memory): the case log in the curation skill, the README and the changelog, with one run on a copy"
```

---

## Results

Filled by Task 5.
