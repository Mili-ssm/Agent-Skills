# Memory capture, stage B3: corroboration, quarantine and triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lesson of reach `general` gets one global record that stays in quarantine (unread) until it is seen in enough sessions and projects, then is read and waits for triage; reworded duplicates inside a project are merged; a session left open is captured at the next session start.

**Architecture:** A sighting on a global record names its session and an opaque project key, and `records.standing` counts both for the global scope. A new detached process, `bin/mem-corroborate`, in the shape of `bin/mem-settle`, gives one tool-less Haiku session the lessons as lines and receives proposed groups, then a second, independent session verifies each group; code validates both answers and applies the verified groups through `bin/mem` (C39). `mem-capture` starts it after a run that wrote something, can add a sighting to a global record, and gains a `sweep` command started by the session start hook.

**Tech Stack:** Python standard library (as `mem-settle` and `mem-capture`), bash hooks, pytest.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md), stage B3, decisions C10, C12, C17, C20 and C28 to C39. Earlier stages: [B1](2026-11-22-memory-capture-records.md), [B2](2026-11-22-memory-capture-background.md).

## Where things stand (2026-11-22)

| Fact | State |
|---|---|
| Design | C28 to C38 approved by the owner on 2026-11-22 |
| Branch | `feat/memory-capture-corroboration`, from `dev`; the spec's rows and this plan, uncommitted |
| First real capture run | Started by hand on the previous session: 2 windows, 8 records written, 0.11 USD, no failure |
| Trial lessons | The 38 candidates the owner kept were recorded on 2026-11-22: 15 global records of origin `transcript`, weight `light`, one counted session each, and 2 project records |
| Project registry | 21 temporary entries removed; 3 projects remain, only this one holds transcript records |
| Proof case | The lesson "a subagent reaches its turn limit and returns no report" stands in three wordings: two global records and one project record |

## Global Constraints

- Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`; before every commit also `python3 scripts/validate.py` and `claude plugin validate .`. Run each check as its own command and read its result before `git commit`: a check piped into `tail` does not stop a chain.
- No version change. One line per user-visible change under `## [Unreleased]` of `plugins/memory/CHANGELOG.md`, written for users.
- No `description` field of a skill or agent changes (a description change needs a measurement, N6); bodies may.
- This repository is public: no home path, transcript text, memory text or project name in code, tests, docs or commit messages. Test records are invented.
- Everything a run writes outside the memories goes under the data folder (`MEM_DATA`, else the state folder), in folders of mode 0700 and files of mode 0600.
- The model session has no Bash, no web and no hooks, and writes one JSON file in its work folder; only code writes memories, and only through `bin/mem`, so every check of that command applies (C4, C28).
- A hook never fails and never waits: it exits 0 within its timeout whatever the started process does.
- With `CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE` not exactly `true`, no process is started by a hook and no file is created. `mem-corroborate run` by hand needs no option.
- A record written before this stage still parses and keeps its standing in the project scope.
- Stage files by name (`git add <path>`), never `git add -u` or `-A`. A report under `.superpowers/` is never committed.

## Names fixed by this plan

| Name | Meaning |
|---|---|
| Sighting entry | A source of the form `session <id>` or `session <id> project <key>`; `<key>` is 12 lower-case hex characters |
| `owner_confirmed` | Frontmatter date: the owner confirmed the record (`mem confirm <h> --by-owner`) |
| `triage` | Frontmatter, only value `pending`: a global record that left quarantine and waits for triage |
| `released` | Frontmatter date: the day the record's quarantine ended |
| `general` | Frontmatter of a project record: the handle of its global record |
| Quarantine | A global record of origin `transcript` whose standing is `unconfirmed` |
| `g:<handle>` | How the capture's "already recorded" list and the pass name a global record; `m:<handle>` stays a project record there |

## Known limits, accepted for this stage

From the pre-mortem of 2026-11-22; its amendments are in the tasks.

- A project is known by the hash of its path: a folder that moved, or a second clone, counts as another project.
- A global record written by a session, with no origin, is not read by the pass (C29). Of the three wordings of the turn-limit lesson only two come from a transcript (one global, one project); the third, an older global record, is left to `mem curate`. The gate in Task 8 is stated on the two.
- Only the list of forbidden terms guards a claim reworded by the model against a name that is not on the list.
- Until a release carries this stage the installed plugin does not know the new fields. The working-tree `bin/mem` is not run on the real store before Task 8.

Kill criteria, also for ADR 0023: a global transcript record in quarantine with no end date after Task 8's migration; a sighting entry without a project on a global record for a project counted elsewhere; the same lessons written or refused in two passes in a row, or two global records sharing a sighting entry; pass and sweep above 1 USD a day for a week; an accepted group that the owner judges to hold two lessons; text of a transcript in a global record's body.

## Review Focus

1. A record with only `session <id>` sources (every record written before this stage): parses, counts its sessions, and in the project scope has the standing it had. Test in Task 1.
2. The model's file is missing, not JSON, names an unknown id, or puts one id in two groups: nothing is written for the bad group, the run ends `ok` with the drop counted. Test in Task 5.
3. A global write is refused for a forbidden or soft term: no project record is linked, the log line counts it, and the run does not fail. Test in Task 5.
4. A record in quarantine still refuses an identical claim at `mem remember --global` and is still found by its handle (`mem show`, `mem confirm`, `mem forget`), although no search shows it. Test in Task 2.
5. A pass stopped after it wrote a global record and before it linked the project records: the record is shown to the next pass as a `g:` lesson, and a verified group that holds it adds the missing sightings and links and writes no second record; two global records of one lesson are merged by a verified group. Test in Task 5.
6. The sweep never reads the transcript of the session that starts, nor a file outside that transcript's folder. Test in Task 7.

---

### Task 1: Sightings with a project, standing of a global record, the new fields

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `session_key`, `normalized_sources`, `sessions`, `standing`, `add_sighting`, `write_memory`)
- Modify: `plugins/memory/engine/mem.py` (`_merge_pair`, `_add_sightings`, `cmd_remember`, `cmd_confirm` and its parser)
- Test: `plugins/memory/engine/tests/test_sightings.py` (new), `plugins/memory/engine/tests/test_confirm_owner.py` (new)

**Interfaces:**
- Produces, in `records`:
  - `PROJECT_KEY_LEN = 12`; `project_key(project: Path) -> str`: the first 12 hex characters of the SHA-1 of the resolved path as text.
  - `sighting(source: str) -> tuple[str, str | None] | None`: `("session <id>", key or None)` for a sighting entry, else None. An entry whose text after `project` is not 12 hex characters is not a sighting entry, and `session_key` returns None for it. `MAX_SESSION_ID` limits the id alone.
  - `sighting_entry(session: str, key: str | None) -> str`: the normalized entry.
  - `session_key(source)`: unchanged contract, now returns only the `session <id>` part of an entry that carries a project.
  - `normalized_sources(sources)`: keeps one entry per session, the one with a project when both forms occur; other sources unchanged, order kept.
  - `projects(memory: Memory) -> list[str]`: the distinct project keys of its sighting entries, in order.
  - `Memory` gains `owner_confirmed: datetime.date | None`, `triage: str | None`, `released: datetime.date | None`, `general: str | None`, parsed and written as frontmatter (an unknown `triage` value parses as None).
  - `standing(memory)`: None unless origin is `transcript`. `established` when `owner_confirmed` is set. Project scope: as today. Global scope (C31): `light` and `medium`, at least 2 projects; `strong`, at least 3 sessions and at least 2 projects; else `unconfirmed`.
  - `quarantined(memory: Memory) -> bool`: scope `global` and standing `unconfirmed`.
  - `standing_changes(before: Memory, after: Memory, today: datetime.date) -> dict`: the frontmatter changes that follow from the standing of `after`: `valid_until` (None when established, else today plus `UNCONFIRMED_DAYS`), and, when `after` is global, established and `before.released` is None, `released=today`, plus `triage="pending"` unless `after.owner_confirmed` is set (the owner's confirmation is the triage). `before` may be None for a record being written.
  - `add_sighting(memory, session, today, note=None)`: accepts a sighting entry with a project; a session already counted without a project gains the project (returns True); uses `standing_changes`.
- Produces, in `mem`: `mem confirm <h> --by-owner` sets `owner_confirmed` to today and applies `standing_changes` (works with `--global`; exit 3 when already set). `_merge_pair` uses `normalized_sources` and `standing_changes` for the kept record. `cmd_remember` applies `standing_changes` to a record it writes, so a global record written with two projects is released and awaits triage at once. `_add_sightings` and the `seen` check of `cmd_confirm` pass whole sighting entries to `add_sighting` and compare by session and project: `--source "session s project <key>"` on a record that holds `session s` adds the project and exits 0; the same entry again exits 3 (pre-mortem 1: both dropped the project).

- [x] **Step 1: Write the failing tests** in `test_sightings.py`, with invented records built through `records.write_memory` in `tmp_path`:

```python
def test_old_entry_still_counts(tmp_path):            # Review Focus 1
    m = project_record(tmp_path, weight="medium", sources=["session a", "Session  A", "session b"])
    assert records.sessions(m) == ["session a", "session b"] and records.projects(m) == []
    assert records.standing(m) == "established"

def test_entry_with_project():
    assert records.sighting("Session  X1 project 0123456789AB") == ("session x1", "0123456789ab")
    assert records.sighting("session x1 project short") is None
    assert records.session_key("session x1 project 0123456789ab") == "session x1"
    assert records.sighting_entry("session x1", "0123456789ab") == "session x1 project 0123456789ab"

def test_normalized_sources_keep_the_project():
    assert records.normalized_sources(["session a", "session a project 0123456789ab", "https://x"]) == \
        ["session a project 0123456789ab", "https://x"]

@pytest.mark.parametrize("weight,entries,expected", [
    ("light",  ["session a project " + K1], "unconfirmed"),
    ("light",  ["session a project " + K1, "session b project " + K2], "established"),
    ("medium", ["session a project " + K1, "session b project " + K1], "unconfirmed"),
    ("strong", ["session a project " + K1, "session b project " + K2], "unconfirmed"),
    ("strong", ["session a project " + K1, "session b project " + K2, "session c project " + K2], "established"),
    ("light",  ["session a"], "unconfirmed"),
])
def test_global_standing(tmp_path, weight, entries, expected): ...

def test_owner_confirmation_establishes(tmp_path): ...     # global, strong, one sighting, owner_confirmed set -> established
def test_release_marks_triage_once(tmp_path): ...          # second project via add_sighting -> released == today, triage == "pending", valid_until None;
                                                           # a third sighting leaves `released` unchanged
def test_project_record_never_gets_triage(tmp_path): ...   # project scope crossing its threshold: triage None, released None
def test_add_sighting_adds_the_project_to_a_counted_session(tmp_path): ...
```

  and in `test_confirm_owner.py`, through the `mem` command as `test_remember.py` runs it: `--by-owner` on a quarantined global record sets `owner_confirmed`, `released`, `triage: pending` and removes `valid_until`; a second call exits 3; the record gets no `triage`. Also through the command: `mem confirm --global --source "session s project <key>"` on a record holding `session s` adds the key (exit 0) and a repeat exits 3; `mem remember --global --origin transcript` with an identical claim and a keyed source adds the keyed entry to the existing record; `mem remember --global --origin transcript --weight light` with two keyed sources of two projects writes a record with `released` and `triage: pending`.

- [x] **Step 2: Run them and see them fail.** Run: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_sightings.py plugins/memory/engine/tests/test_confirm_owner.py -q`. Expected: failures on the missing names.
- [x] **Step 3: Implement** the interfaces above. `write_memory` computes `valid_until` for a transcript record from the new `standing`.
- [x] **Step 4: Run the whole suite.** Expected: all pass; a test of an earlier stage that asserted a global transcript record is established by sessions alone is changed to the rule of C31, and the report names each such test.
- [x] **Step 5: Commit** `feat(memory): sightings name their project and a global lesson needs two projects`.

### Task 2: Quarantine on the reading side

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`session_index`, `cmd_search`, `cmd_memories`, the related-memory hints of `cmd_remember`, the status counts near `_memory_folders`, the start of `mem-settle` in `cmd_remember`), `plugins/memory/engine/settle.py` (`pending`)
- Test: `plugins/memory/engine/tests/test_quarantine.py` (new)

**Interfaces:**
- Consumes: `records.quarantined` (Task 1).
- Produces: `_readable(memories: Sequence[records.Memory], today) -> list[records.Memory]` in `mem.py`: live and not quarantined; every place that shows memories to a reader uses it. `mem memories --global --quarantine` lists only the records in quarantine, each line tagged `quarantine`. Settling leaves quarantine alone: `cmd_remember` does not start `mem-settle` for a record it wrote into quarantine, and `settle.pending` offers no pair that holds a quarantined record (pre-mortem 9).

- [x] **Step 1: Write the failing tests**, each on a global folder holding one established record and one quarantined record with distinct invented claims:

```python
def test_search_does_not_show_a_quarantined_record(...)       # its claim's words as the query: absent; the established one: present
def test_session_index_counts_only_readable(...)              # "Global memories: 1"
def test_memories_listing_hides_it_and_the_flag_shows_it(...)
def test_remember_hint_does_not_show_it(...)                  # related-memory hint on a similar claim
def test_identical_claim_is_still_refused(...)                # Review Focus 4: mem remember --global, same claim -> exit 3
def test_handle_still_resolves(...)                           # Review Focus 4: mem show, mem confirm --global, mem forget --global work
def test_project_scope_is_unchanged(...)                      # an unconfirmed project record is still shown as before
def test_settle_leaves_quarantine_alone(...)                  # no pair with a quarantined record; a quarantined write starts no settle run
```

- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement** `_readable` and use it at the reading call sites; leave the identical-claim check, handle resolution, `mem curate` and `mem-capture`'s list on the unfiltered load.
- [x] **Step 4: Run the whole suite.** Expected: all pass.
- [x] **Step 5: Commit** `feat(memory): a general lesson in quarantine is not shown to a reader`.

### Task 3: A capture can add a sighting to a global record

**Files:**
- Modify: `plugins/memory/bin/mem-capture` (`recorded_lines`, `apply_one`), `plugins/memory/engine/capture.py` (`validate`, only if it rejects the `g:` prefix), `plugins/memory/engine/records.py` (`under_temp`)
- Test: `plugins/memory/engine/tests/test_mem_capture.py`, `plugins/memory/engine/tests/test_capture.py`

**Interfaces:**
- Consumes: `records.project_key`, `records.sighting_entry` (Task 1).
- Produces: `recorded_lines` returns global records of origin `transcript` (live, or unconfirmed and lapsed for at most `LAPSED_DAYS`, quarantined ones included) as `g:<handle>\t<claim>` with their handles in the returned mapping; other global records stay `(general)\t<claim>`. `apply_one` with `same_as` starting `g:` runs `mem confirm m:<handle> --global --source="session <id> project <key>" --note="Seen again (<signal>)."`, `<key>` from `env["MEM_PROJECT"]`; the note never holds the evidence quote, because text of a transcript must not reach the global scope (pre-mortem 3). In a project under a temporary root (`records.under_temp(path) -> bool`: the resolved `tempfile.gettempdir()`, `/tmp`, `/var/tmp`; false when `MEM_COUNT_TEMP_PROJECTS` is `1`) the candidate is `skipped` with "a temporary project" (pre-mortem 6); outcome `sighting`, or `skipped` with "this session already counted" on exit 3 and "not a global memory any more" when the handle is gone.

- [x] **Step 1: Write the failing tests**: the list holds a `g:` line for a quarantined global transcript record and a `(general)` line for a global record of no origin; a candidate with `same_as: "g:<handle>"` and enough shared terms is kept by `validate`; `apply_one` adds the entry with the project key and a second call with the same session is skipped; the evidence text is not in the global record's file; in a project under a temporary root nothing is added; a `same_as: "m:<handle>"` still only reaches a memory of the project.
- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the whole suite.** Expected: all pass.
- [x] **Step 5: Commit** `feat(memory): a capture adds a sighting to a general lesson it recognizes`.

### Task 4: `corroborate.py`, what the pass reads and decides

**Files:**
- Create: `plugins/memory/engine/corroborate.py` (pure: no model, no subprocess)
- Test: `plugins/memory/engine/tests/test_corroborate.py` (new)

**Interfaces:**
- Consumes: Task 1 (`project_key`, `sighting`, `sighting_entry`, `sessions`), Task 3 (`records.under_temp`, the `g:` naming).
- Produces:
  - `MAX_LESSONS = 150`, `MAX_GROUPS = 30`.
  - `counted_projects(registry: Mapping[str, Mapping[str, str]]) -> list[Path]`: registered paths that exist, hold a memory folder and are not `records.under_temp`; sorted.
  - `Lesson(id: str, scope: str, project: Path | None, memory: records.Memory)`; ids are `g:<handle>` and `p<n>:<handle>`, `<n>` the project's position (from 1) in the sorted list, so no project name reaches the model.
  - `collect(projects: Sequence[Path], global_folder: Path | None, today) -> list[Lesson]`: active records of origin `transcript`, live or unconfirmed and lapsed for at most 60 days; project records with `promote == "no"` or `general` set are left out; newest first, cut at `MAX_LESSONS`.
  - `fingerprint(lessons: Sequence[Lesson]) -> str`: a hash of every id with its reach, claim, context and sorted sources, joined so that no two different sets give the same text; `lesson_fingerprint(lesson) -> str` the same for one.
  - `lesson_lines(lessons) -> list[str]`: `<id>\t<reach, or "general" for a global record>\t<claim>\t<context>`, each on one line.
  - `validate_groups(raw: object, lessons: Sequence[Lesson]) -> tuple[list[Group], list[str]]`; `Group(ids: list[str], claim: str, context: str)`. A group is dropped, with a reason, when it is not an object of that shape, names an unknown id, repeats an id, shares an id with an earlier group, has an empty claim, or has one member and that member is global or of reach `project`. At most `MAX_GROUPS` are kept.
  - `validate_groups` takes the model's whole answer, the object `{"groups": [...]}`; a bare list is refused with a reason (review T4-1).
  - `verification_lines(groups: Sequence[Group], lessons: Mapping[str, Lesson]) -> list[str]`: for each group a block: `group <n>`, one line per member (`<id>\t<claim>\t<context>`), and `proposed\t<claim>\t<context>`; `<n>` from 1.
  - `validate_verdicts(raw: object, groups: Sequence[Group]) -> tuple[list[Group], list[str]]`: `raw` is `{"verdicts": [{"group": <n>, "reason": "...", "same": bool, "faithful": bool, "general": bool}]}`. A group is kept only with exactly one verdict for it (a verdict whose `group` is not the number of an existing group keeps nothing at all), a non-empty reason, and `same`, `faithful` and `general` all exactly `true`; a group of one needs no `same` (it is read as true). Each group not kept gives a reason line naming `<n>` and which answer failed; a missing or malformed answer keeps nothing (C39).
  - `Action(kind: str, ...)` with kinds `merge`, `merge_global`, `write_global`, `sighting`, `link`, and `actions(group: Group, lessons: Mapping[str, Lesson]) -> list[Action]`, in this order: (1) `merge` for each project that has two or more members: the oldest keeps, each other is dropped into it, either reach; (2) `merge_global` when two or more global members: the oldest keeps; (3) for the members of reach `general` left after the merges: the target is the group's global member, else a `write_global` (kind of the oldest member, the heaviest weight among the members, the group's claim and context, one sighting entry per session of each member with that member's project key); then one `sighting` per entry the target lacks and one `link` per project member. Members of reach `project` from different projects produce no action. A global record that merely shares a session with a member is never a target, because one session carries several lessons (review of Task 4, round 2); a pass that stopped half way may therefore write a second global record, and a later pass joins the two as global members, through the verification. A member with no session produces no action and is not linked; the entries of one `write_global` hold each session once.

- [x] **Step 1: Write the failing tests** (invented records in `tmp_path`, `MEM_COUNT_TEMP_PROJECTS=1` except where the temporary root is the point): `counted_projects` leaves out a missing folder, a folder with no memory folder and one under a temporary root; `collect` leaves out a linked record, a `promote: no` record, a record of another origin and a superseded one; `fingerprint` changes when a source is added and not when the order of lessons changes; `validate_groups` drops each bad shape of Review Focus 2 and keeps the good group beside it; `actions` for: two general records of two projects (one `write_global` with two entries carrying two keys, two `link`), one general record alone (one `write_global`, one `link`), a general record with a global member (`sighting`, `link`, no `write_global`), a general record whose session a global record of another lesson holds (still a `write_global`), two records of one project (one `merge`, oldest kept), two global members (`merge_global`), two records of reach `project` from two projects (no action).
- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the whole suite.** Expected: all pass.
- [x] **Step 5: Commit** `feat(memory): corroborate.py decides what the matching pass reads and does`.

### Task 5: `mem-corroborate`, the command

**Files:**
- Create: `plugins/memory/bin/mem-corroborate` (session, lock, status, log, journal, applying through `bin/mem`)
- Modify: `plugins/memory/engine/mem.py` (`mem promote --done <h> --to <global handle>` writes `general`)
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py` (new)

**Interfaces:**
- Consumes: Task 4; from `bin/mem-settle` the pattern of `session_cmd`, `session`, `run_env` and the self-check; from `auto_state` the lock, status and failure helpers that `mem-capture` uses.
- Produces: commands `run [--claude PATH] [--budget USD] [--dry-run --out FILE] [--groups FILE]`, `auto [--claude PATH]` (does nothing unless the option is on; never raises, never prints), `undo <stamp>`, `status`, `ack`, `--self-check`. `--groups FILE` applies a reviewed file in the model's format and starts no model session.
- State under `<data>/corroborate/`: `status.json`; `log.jsonl` (one line of counts per run: `lessons`, `groups`, `dropped`, `written`, `sightings`, `links`, `merges`, `refused`, `skipped`, `cost`, `failed`, `ms`; no claim text); `seen.json`; `runs/<stamp>/` with the lessons file, the model's file, `log.txt`, `journal.jsonl` and `before/`. One lock for the folder; a run that finds it held ends with `skipped`.
- Two sessions per run (C39), both tool-less and each within the budget: the first writes the proposal from the lessons file with the proposal brief below; code runs `validate_groups`; the second, a fresh session that sees neither the first one's reasoning nor the full list, reads the file made from `verification_lines` and writes the verdicts with the verification brief below; code runs `validate_verdicts` and applies only the kept groups. A group not verified is recorded in `seen.json` like a refused one. The log line gains `proposed` and `verified`. `--groups FILE` skips both sessions; `--dry-run` runs both and writes the proposal, the verdicts and the planned actions to the out file.
- A global record is reworded once: no action of the pass changes the claim of an existing record.
- On exit 3 of `write_global` (the claim exists) the group's entries are added to that record as sightings (review T4-2).
- No repeated work (pre-mortem 5): `seen.json` holds the fingerprint of the last run's lessons and, per lesson id, the fingerprint it had when an action on it was refused or failed. A run whose lessons have the last fingerprint starts no model session (log line `skipped: "nothing new"`). A group that holds a lesson whose refused fingerprint is unchanged is not applied. A new sighting changes the fingerprint and lifts both.
- Applying: `write_global` is `mem remember --global --origin transcript --reach general ...` with one `--source` per entry and the fixed body `Written by the corroboration pass from <n> lessons of <m> projects.`, never text of a project record (pre-mortem 3); exit 3 with a handle means the claim exists: that record becomes the target; exit 4 or 5 counts as `refused` and the group's links are not written (Review Focus 3). `sighting` is `mem confirm m:<h> --global --source=<entry>` (exit 3 is not an error). `link` is `mem promote --done m:<h> --to <global handle>` with `MEM_PROJECT` set to that project. `merge` is `mem merge m:<keep> m:<drop>` with `MEM_PROJECT` set, `merge_global` adds `--global`; a merge that `mem` refuses is counted as `refused`, recorded in `seen.json` and left for curation, never forced.
- Undo (pre-mortem 7): before its first write to a record's file a run copies that file into `runs/<stamp>/before/` and appends to `journal.jsonl` the action, the file, whether the run created it, and the hash of the file after the action. `undo <stamp>` restores every copied file and removes every created one; it refuses, changing nothing, when a file's hash differs from the journal's (it was edited since), naming the file.

The proposal brief, verbatim (the file names are filled by code):

```
You compare short lessons that coding sessions wrote down, and say which of them state the same lesson.

Read {lessons}. Each line is: an id, a reach (general or project), the lesson, and when it applies, separated by tabs.
Ids starting with g: are lessons already kept for every project; ids starting with p1:, p2: ... belong to one project each.
An id is copied whole, exactly as written, with its g: or p1: start; a line number that your reading tool shows before a line is not an id.

Two lessons are the same when a reader who follows one would do what the other asks, in the same kind of situation,
even if the words, the example or the numbers differ. Lessons about the same topic that advise different things are
not the same. When you are not sure, leave them apart: a wrong group merges two lessons and loses one.

Write {out} as JSON: {{"groups": [{{"ids": ["..."], "claim": "...", "context": "..."}}]}}
- One group for each set of two or more lessons that are the same.
- Also one group for each general lesson with a p id that is in no other group and matches no g: lesson: a group of one.
- Never a group of one for a g: lesson or a project lesson.
- An id appears in at most one group.
- claim: the lesson in one to three sentences, as a suggestion or a recommendation that says what was seen and what
  is not known, never an order. It must hold in any project: name no project, company, client, person, repository,
  file, path, product or internal system. Keep what a reader needs to act: the situation, the action, the reason.
- context: one sentence on when the lesson applies, under the same rule about names.
Write nothing else and use no other tool.
```

The verification brief, verbatim:

```
You check proposals to treat several short lessons as one. Another reader made the proposals; it is often wrong, and
a wrong "yes" merges two different lessons and loses one, so say yes only when you are sure.

Read {groups}. Each block starts with "group <n>", then one line per lesson (an id, the lesson, when it applies,
separated by tabs), then a line starting with "proposed": the single wording that would replace them for every project.

For each group, answer in this order:
- reason: one sentence saying what each lesson asks the reader to do and whether that is the same thing.
- same: true only if a reader who follows any one of the lessons would do what each of the others asks, in the same
  kind of situation. The same topic with different advice is false. For a group of one lesson, write true.
- faithful: true only if the proposed wording keeps the situation, the action and the reason of the lessons, adds no
  claim they do not make, turns no suggestion into an order, and names no project, company, client, person,
  repository, file, path, product or internal system.
- general: true only if the lesson is about how to work (planning, delegating, verifying, using tools, reading what
  was asked) and would hold in another project; false if it only makes sense inside one codebase or product.

Write {out} as JSON: {{"verdicts": [{{"group": 1, "reason": "...", "same": true, "faithful": true, "general": true}}]}}
One entry per group, in order. Write nothing else and use no other tool.
```

- [x] **Step 1: Write the failing tests**, with the fake `claude` that `test_mem_capture.py` and `test_capture_auto.py` use (it writes a given file as the model's output), `MEM_DATA`, `MEM_MEMORIES` and a registry in `tmp_path`, `MEM_COUNT_TEMP_PROJECTS=1`:

```python
def test_two_projects_make_one_established_global_record(...)   # light lesson in two projects: one global record, two entries with two keys,
                                                                # standing established, triage pending, both project records promote done + general
def test_one_project_makes_a_quarantined_record(...)            # written, quarantined, not in `mem search`; its body is the fixed line
def test_rerun_after_a_stop_joins_the_record(...)               # Review Focus 5: the global record exists, links missing; the model groups the project
                                                                # record with it (g: member) -> sightings and links, no second record
def test_two_global_records_of_one_lesson_are_merged(...)       # a verified group of two g: members: merge_global, the oldest keeps the sightings
def test_nothing_new_starts_no_model(...)                       # second run, same lessons: the fake claude is not called
def test_bad_model_file_writes_nothing(...)                     # Review Focus 2: status ok, log line dropped > 0
def test_unverified_group_is_not_applied(...)                   # verdict same=false: no merge, no write, no link; recorded in seen.json
def test_missing_verdicts_apply_nothing(...)                    # the second session writes no file, or garbage
def test_existing_global_claim_is_never_rewritten(...)          # a group with a global member: its claim is unchanged after the run
def test_forbidden_term_refuses_the_group_once(...)             # Review Focus 3: refused == 1, no link, status ok; the next run does not apply it again
def test_same_project_duplicates_are_merged(...)                # one superseded, sightings united
def test_refused_merge_is_counted_not_forced(...)               # claims that differ by a number
def test_undo_restores_every_file(...)                          # after a run with a write, a sighting, a link and a merge: files equal to before
def test_undo_refuses_when_a_file_changed(...)
def test_groups_file_starts_no_model(...)
def test_dry_run_writes_only_the_out_file(...)
def test_auto_does_nothing_without_the_option(...)              # no folder created
def test_lock_held_skips(...)
def test_model_failure_leaves_a_failure_line_until_ack(...)
def test_no_project_name_or_path_in_log_and_lessons_file(...)
```

- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the whole suite.** Expected: all pass.
- [x] **Step 5: Commit** `feat(memory): mem-corroborate matches lessons by meaning and keeps one general record`.

### Task 6: Triage

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_curate`, `session_index`, `cmd_session_index`, a new `cmd_triage` and its parser), `plugins/memory/agents/memory-curator.md` (body), `plugins/memory/skills/memory-curation/SKILL.md` (body)
- Test: `plugins/memory/engine/tests/test_triage.py` (new), `plugins/memory/engine/tests/test_session_index.py`

**Interfaces:**
- Consumes: the fields of Task 1; `corroborate.counted_projects` (Task 4) to find the linked project records; `capture_state.failure_line`'s pattern for the pass's failure line.
- Produces:
  - `mem curate --global` prints a category `general lesson, out of quarantine, awaiting triage (decide: mem triage accept <h>, mem triage reject <h>, or reword it with mem edit and then accept)` with each record's sessions and projects counted, and one line `in quarantine: <n> general lessons, not shown to a reader until corroborated (mem memories --global --quarantine)`; a quarantined record is not listed under "from a transcript, not confirmed yet", whose advice to forget is for project records.
  - `mem triage accept <handle>`: removes `triage`. `mem triage reject <handle>`: retires the global record as `mem forget` does, and in every counted project sets `promote: no` and removes `general` on the records that name it. Both act on the global scope, log to the curation log as other edits do, and exit 2 when the record does not await triage.
  - The session start text gains `Triage: <n> general lessons await triage (mem curate --global).` when `n > 0`, and the failure line of a failed pass until `mem-corroborate ack`.
  - `memory-curator.md` and the skill say, as they do for `mem confirm`: the background curator does not run `mem triage`; a main session may accept or reject, and turning a lesson into a rule needs the owner.

- [x] **Step 1: Write the failing tests**: the category and the quarantine count in `mem curate --global`; accept clears the field and the session start line disappears; reject retires the record and marks a linked project record in a second project folder; reject of a record with no `triage` exits 2; the session start text shows the count and the pass's failure line.
- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the whole suite, `python3 scripts/validate.py` and `claude plugin validate .`.** Expected: all pass.
- [x] **Step 5: Commit** `feat(memory): triage of a general lesson in mem curate and at session start`.

### Task 7: Start after a capture, and the sweep of a session left open

**Files:**
- Modify: `plugins/memory/bin/mem-capture` (`auto` split into `hook_input` plus `auto_run(trigger, transcript, cwd, claude)`; a new command `sweep`), `plugins/memory/engine/capture_state.py` (constants, the swept size of a session), `plugins/memory/hooks/session-index.sh`
- Test: `plugins/memory/engine/tests/test_capture_auto.py`, `plugins/memory/engine/tests/test_capture_sweep.py` (new), the hook tests that cover `session-end.sh` and `pre-compact.sh`

**Interfaces:**
- Consumes: `bin/mem-corroborate auto` (Task 5).
- Produces:
  - `auto_run` starts `bin/mem-corroborate auto [--claude PATH]` detached (new session, standard streams to the null device) after it has released the capture lock, when the run wrote at least one `remembered` or `sighting` and did not fail.
  - `capture_state`: `SWEEP_IDLE_SECONDS = 6 * 3600`, `SWEEP_MAX_AGE_DAYS = 7`, `SWEEP_MAX_SESSIONS = 2`, `SWEEP_MAX_PER_DAY = 4` (sessions swept per UTC day for one data folder, kept in the capture folder: pre-mortem 10); the session state gains `swept_size` (the file's size at its last sweep).
  - `mem-capture sweep [--claude PATH] < hook.json`: reads `transcript_path` and `cwd`; among the `*.jsonl` files directly in that transcript's folder, never the transcript itself, takes those changed between 7 days and 6 hours ago, with more lines than their saved offset and a size different from `swept_size`, newest first, at most 2; runs `auto_run("sweep", file, <that file's cwd>, claude)` for each and saves `swept_size`; the cwd is the first `cwd` value found in the file's own lines, and a file with none is left out. Same option gate, lock, windows and offsets as `auto`; always exits 0 and prints nothing.
  - `session-index.sh` reads standard input once (bounded as `session-end.sh` does), gives it to `mem session-index --hook`, and, with the option exactly `true`, first starts `mem-capture sweep` detached with the same input.

- [x] **Step 1: Write the failing tests**: a run that wrote a record starts the pass (a fake `mem-corroborate` on a path given by a test variable records that it was started) and a run that wrote nothing, or failed, does not; the sweep takes an idle file with unread lines, and leaves out the starting session's file, a file changed 1 hour ago, a file 8 days old, a file fully read, a file whose size equals `swept_size`, a third candidate, a file with no `cwd`, a fifth session on one day, and a file in another folder (Review Focus 6); the hook prints the same session start text as before with the option off and on, exits 0 when `mem-capture` is missing, and starts nothing with the option off.
- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the whole suite.** Expected: all pass.
- [x] **Step 5: Commit** `feat(memory): corroboration starts after a capture; a session left open is swept at the next start`.

### Task 8: The gate with the real model, and the records (controller)

Not dispatched: the controller runs it.

- [x] Copy the three real projects' memory folders and the global memories into a private folder under the data folder (not the repository, not the temporary folder), with its own `MEM_DATA`, `MEM_MEMORIES` and registry.
- [x] `mem-corroborate run --dry-run --out <file>` on the copy, seven times. The run that writes was left out: `--dry-run` shows the same plan and the copy stays reusable.
- [x] Measures for the gate and for ADR 0023 (C39): run the pass twice on the copy with `--dry-run` and record how many applied groups the two runs share (agreement of the pass with itself); record how many proposed groups the verification refused; after the owner's review, record how many applied groups the owner accepts (agreement with the owner) and whether any refused group was in fact right.
- [x] Gate (spec, B3, as Known limits restate it): the two transcript wordings of the turn-limit lesson end as one global record, and the owner judges no accepted group to hold two different lessons. Show the owner every group, five per batch, with a yes or no key. If the gate fails, change the brief once and run again; a second failure stops the stage.
- [x] Migration, whatever the gate's result, and before any release carries Tasks 1 and 2: confirm the 15 recovered global lessons with the working-tree `bin/mem confirm --global --by-owner` on the real store (the owner reviewed them on 2026-11-21 and agreed to this on 2026-11-22), then check that no global transcript record is in quarantine with no end date.
- [ ] The first pass on the real store: `run --groups <the file the owner reviewed>`, not a new model session.
- [x] Records: `plugins/memory/README.md` (the pass, quarantine, triage, the sweep; implemented apart from planned), `plugins/memory/CHANGELOG.md`, ADR 0023 `### Stage B3` with the gate's figures and kill criteria, the state tables of [the stage plan](2026-11-17-memory-plugin.md) and of the spec's Phases, and the Results section below.
- [x] `python3 scripts/validate.py`, `claude plugin validate .`, the whole suite (1701 passed, 5 skipped); then the narrow final reviews of the plan loop (docs against code, the flow across tasks).

## Results

Built on 2026-11-22 on `feat/memory-capture-corroboration`; not merged, not released. Tasks 1 to 7 each had their task commit, a review, a fix round and a second review; the findings deferred are below.

| Task | State |
|---|---|
| 1 Sightings with a project, global standing, new fields | Done |
| 2 Quarantine on the reading side | Done |
| 3 A capture adds a sighting to a global record | Done |
| 4 `corroborate.py` | Done; C39 (propose, then verify) added after research the owner asked for |
| 5 `mem-corroborate` | Done |
| 6 Triage | Done |
| 7 Start after a capture, and the sweep | Done |
| 8 Gate, migration, records | Gate passed; migration done on the real store; the first pass on the real store waits for the release |

Gate figures and kill criteria: ADR 0023, "Stage B3". The owner accepted 15 of 15 groups.

Open, for the session that releases or continues:

| Item | Why it waits |
|---|---|
| First pass on the real store | Only after the installed plugin knows quarantine: with 0.3.0 a new global record would be read at once. The reviewed groups are in the private gate folder (`dry7.json`); its `p1` ids are positions in that copy's registry, so check them against the real registry before `run --groups`, or let the pass propose again |
| The older global record of the turn-limit lesson, written by hand | Outside C29; merge it by hand in `mem curate` |
| A lapsed lesson in quarantine | It lapses 30 days after its last sighting (C31) and is then no longer offered to the capture after 60; a second project may take longer than that. Read the first weeks of `corroborate/log.jsonl` before changing the figure |
| Project records linked to a global record that a later merge dropped | They keep pointing at the dropped handle |
| Restoring a rejected global record | Does not link its project records again |
| A mark blocks a group only when all its members keep it | A refused pair can come back inside a larger group; the verifying session judges it again |
| Undoing an older pass | Also clears a newer pass's fingerprint and marks (one more proposal) |
| A pass or a sweep killed by a signal | Leaves no log line; the status reads as failed after the stale limit |
| Usefulness of a released lesson | Stage B4: the `released` date separates sightings before and after a lesson was readable; a counter of evidence against a lesson does not exist yet |
| The `SessionEnd` hook's 1.5 s limit | In the stage plan's open items |
