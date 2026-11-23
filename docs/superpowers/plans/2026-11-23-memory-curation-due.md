# The `Curation due` count and a quieter curation queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The session start count names the decisions of the curation queue that the last pass did not list, within the hook's time, and `mem curate` prints pairs grouped, state memories as a proposal of their own and `differ in` without stopwords.

**Architecture:** One helper in `mem.py` loads a folder, drops superseded memories and builds its decision items (refuted again, same or opposite, newer state, expired, seen often, not confirmed in 90 days); `mem curate` prints from it, `mem curate --done` records its keys in a new derived file, and the session index counts the items whose keys are not recorded. At session start the pair search covers only memories changed since the pass, newest first, under one shared budget of comparisons.

**Tech Stack:** Python 3 standard library and PyYAML, pytest. Engine in `plugins/memory/engine/`.

**Spec:** [the design](../specs/2026-11-23-memory-curation-due-design.md), rows C98 to C107. Read it before any task.

## Global Constraints

- Branch `feat/memory-curation-due`; one local commit per task; stage only the files the task names, by path; no push, no pull request, no merge.
- `curated.json` keeps its format (`{resolved folder: "YYYY-MM-DD"}`); the keys go to `curated-items.json` beside it, `{resolved folder: [key, ...]}`, written atomically (temporary file and `os.replace`) as `_write_passes` does. A missing, unreadable or malformed `curated-items.json`, or a value of the wrong type, reads as no keys.
- `records.pairs` and `records.refuted_pairs` return what they return today when called without the new keyword arguments: `settle.py` calls `pairs`.
- At session start all pair searches of both folders share one budget, `PAIR_WORK = 150_000` comparisons (C101); `mem curate` and `--done` compare all.
- A memory is *changed since the pass* when its `created` is on or after the pass date, or its file's modification date (local time) is on or after it, or it has no `created`.
- Nothing in this plan changes a memory file; `mem curate` without `--done` writes nothing.
- The session index never raises and never loses its other lines: each folder's count runs in its own `try`, and a failure leaves that folder out of the count.
- Tests never run `mem` against the default environment: they use the fixtures of `test_curation.py` (`MEM_*` pointed at temporary folders).
- The repository is public: no home path, private repository name, client name, note title, real handle or claim of the owner's store in code, tests or docs.
- The whole suite, once at the end of each task: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q > <a file in a temporary directory> 2>&1` (about five minutes; foreground, timeout 600 s; read its last line).
- An existing test that asserts an exact output this plan changes is updated in the task that changes it and named in its report.

## Stop and report

| Observation | Action |
|---|---|
| A test of settle, corroboration, capture or the loaded rules changes its result | Stop and report which and why |
| The timed test of Task 3 takes 2 seconds or more | Stop and report the figure |
| A memory file changes in any test of `mem curate` without `--done` | Stop |
| Task 5: `mem curate --done` on the unchanged copy, then any `Curation due` line | Stop: the keys of `--done` and of session start differ |
| Task 5: `bin/mem session-index --hook` on the copy takes over 1 second, or over 0.3 seconds more than `main` on the same copy | Stop and report the figures |

## Review Focus

| Input or condition | Expected | Pinned in |
|---|---|---|
| A folder with a pass date but no keys (a store passed before this change) | Pairs of two memories unchanged since the pass are not counted; every other decision item counts | Task 3 |
| A pair made after the pass by `mem memory edit`, `mem restore` or `mem confirm --until` between two memories created before it | Counted (the file was written) | Task 3 |
| `--done`, then session start, on a fixture with superseded-but-active, unconfirmed, quarantined, expired and state memories | No line | Task 3 |
| `curated-items.json` holding a list, a string, or keys that are not strings | Reads as no keys; no exception | Task 3 |
| `mem curate --done --global` | Records keys for the global folder only; the project's keys stay | Task 3 |

---

### Task 1: Faster pair search, restricted and budgeted, and `differ in` without stopwords

**Files:**
- Modify: `plugins/memory/engine/records.py` (`pairs`, `refuted_pairs`, `differing_words`)
- Test: `plugins/memory/engine/tests/test_curation.py`; `plugins/memory/engine/tests/test_consolidation.py` if it asserts a notes `differ in` line (`_curate_notes` in `mem.py` also calls `differing_words`; its output changes the same way)

**Interfaces:**
- Produces: a mutable budget `records.Budget(left: int)`; `records.pairs(memories, today, *, tokenize, among: Sequence[str] | None = None, budget: Budget | None = None) -> list[tuple[Memory, Memory, float]]`. Each claim is tokenized once and its set built once. With `among` (handles, in the order to search), only pairs with at least one handle in `among` are compared, each pair once, searching `among` in its order. With `budget`, each comparison spends 1 and the search stops when `budget.left` reaches 0, returning what it found; the caller reads `budget.left == 0` as "not all compared" only when comparisons remained. Without both, the result equals today's, order included.
- Produces: `records.refuted_pairs(..., among=None, budget=None)`, same contract; each refuted claim is tokenized once; with `among`, only live memories whose handle is in `among` are compared.
- Produces: `records.differing_words(a, b) -> list[str]` leaves out `STOPWORDS` except `_NEGATIONS`; digits stay; `[]` when nothing is left.

- [x] **Step 1: Write the failing tests**: `test_pairs_unchanged_without_new_arguments` (on a fixture of about 30 claims with several pairs, the result equals a copy of today's implementation kept in the test); `test_pairs_among_compares_only_pairs_with_a_listed_memory` (A~B and B~C pair; `among=["c"]` returns only B–C); `test_pairs_budget_stops_and_reports` (a budget of 1 with two listed among ten live: at most one comparison spent, `left == 0`); `test_refuted_pairs_among_and_budget`; `test_differing_words_drops_stopwords_and_keeps_negations` (`"the cache is warm"` against `"cache is not warm"` gives `["not"]`; `"retry 3 times"` against `"retry 5 times"` gives `["3", "5"]`).
- [x] **Step 2: Run them**: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_curation.py -q -k "pairs or differing"`; expected FAIL.
- [x] **Step 3: Implement** the three changes. `pairs` keeps its sort and its `distinct_from` rule.
- [x] **Step 4: Run them**, then the whole suite; expected PASS. Any test asserting a `differ in` line (memories or notes) is updated and named.
- [x] **Step 5: Commit**: stage `records.py` and the changed tests by path; `git commit -m "feat(memory): pair search tokenizes once, takes a list and a budget; differ in without stopwords"`

### Task 2: One builder of decision items, and the queue printed from it

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_curate` listing part)
- Test: `plugins/memory/engine/tests/test_curation.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: in `mem.py`, a frozen dataclass `Decisions` with fields `refuted: list[tuple[Memory, Memory]]`, `same: list[tuple[Memory, Memory]]`, `state: list[tuple[Memory, Memory]]` (old, new), `expired: list[Memory]`, `seen: list[Memory]`, `stale: list[Memory]`, `pairs_checked: bool`; a method `keys() -> dict[str, str]` mapping each key of C100 (`refuted:<live>|<refuted>`, `pair:<a>|<b>` sorted, `state:<old>|<new>`, `expired:<h>`, `seen:<h>`, `stale:<h>`) to its part label (`"refuted again"`, `"same or opposite"`, `"newer state"`, `"expired"`, `"seen often"`, `"not confirmed in 90 days"`).
- Produces: `_decisions(loaded: Sequence[Memory], today: date, *, since: date | None = None, budget: records.Budget | None = None) -> Decisions`. It drops superseded memories itself (`superseded_by` set), so every caller passes what `records.load_memories` returned. With `since`, the pair kinds use `among` = handles of live memories changed since the pass (Global Constraints), newest change first; with `budget`, the searches spend it and `pairs_checked` is False when it ran out with comparisons left. `expired`, `seen`, `stale` are the lists `cmd_curate` builds today, with the unconfirmed handles left out as today. A pair of two live `kind == "state"` memories goes to `state` (older by `created`, a missing `created` oldest, then handle, first), never to `same`.
- `PAIR_WORK = 150_000` in `mem.py`.

- [x] **Step 1: Write the failing tests**: `test_curate_groups_pairs_by_memory` (a memory in three pairs prints once, then per partner its indented tagged line with its claim and a `differ in` line below, each pair once); `test_curate_lists_state_pairs_as_newer_state` (two state memories that pair print under `newer state of the same project? (decide: mem supersede <old> <new>, or mem distinct <a> <b>)` as the older memory's tagged line then an indented `-> ` line with the newer one's tag and claim, not under same or opposite); `test_curate_seen_often_says_note_in_the_store` (header `seen 3 times or more: general enough for a note in the store? (mem promote <h>)`); `test_differ_in_wording_only`; `test_decisions_keys` (each key form, pair handles sorted); `test_decisions_drops_superseded`.
- [x] **Step 2: Run them**; expected FAIL.
- [x] **Step 3: Implement** `Decisions`, `_decisions` and the listing from it. Grouping (C102): repeatedly take the memory in the most remaining pairs (ties by handle), print it with `_tagged`, then per partner its `_tagged` line indented two more spaces and below it `      differ in: ...`, and drop those pairs. Newer state: per pair `_tagged(old)` then `    -> ` followed by the newer one's tag and claim. The other blocks keep their order and text except C105. The listing calls `_decisions` per folder without `since` or `budget`.
- [x] **Step 4: Run them**, then the whole suite; update and name the tests that asserted the old pairs block or the old seen-often header.
- [x] **Step 5: Commit**: stage `mem.py` and `test_curation.py` by path; `git commit -m "feat(memory): the curation queue groups pairs and proposes newer state"`

### Task 3: Keys recorded by `--done`, the count at session start, and the end of the remember nudge

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_curate --done`, beside `read_passes`, `session_index`, `cmd_session_index`, `cmd_remember`), `plugins/memory/engine/records.py` (remove `curation_due`)
- Test: `plugins/memory/engine/tests/test_curation.py`; `plugins/memory/engine/tests/test_transcript_records.py` (its `curation_due` test is rewritten against the new count, keeping what it proved: an unconfirmed memory from a transcript is not counted); `plugins/memory/engine/tests/test_remember.py` (the test asserting `new memories since the last curation pass` now asserts that line is absent)

**Interfaces:**
- Consumes: Task 2.
- Produces: `read_marks(env) -> dict[str, frozenset[str]]` and `_write_marks(env, covered: Mapping[Path, Collection[str]])` for `curated-items.json` in the data folder, beside `curated.json`. `--done` computes `_decisions(...)` per covered folder (no `since`, no budget), writes its keys replacing that folder's entry only, and prints `recorded <K> items` per covered folder (`item` when K is 1), `global` or `project` first (C107).
- Produces: `session_index(..., marks: Mapping[str, frozenset[str]] | None = None)`; one `records.Budget(PAIR_WORK)` shared by both folders (project first); the count per folder is the keys of `_decisions(loaded, today, since=<the folder's pass date>, budget=<shared>)` not in the folder's marks. Line (C99): `Curation due: {n} {item|items} ({parts}) (run mem curate after the current task).`, parts `"<k> <label>"` joined by `", "` in the order of `Decisions` fields, summed over both folders; when a folder's pairs were not all checked and n > 0: `Curation due: at least {n} {item|items} ({parts}) (run mem curate after the current task).`; no line when n is 0.
- `cmd_remember` no longer prints the count of new memories (C106).

- [ ] **Step 1: Write the failing tests**: `test_new_memories_alone_do_not_make_curation_due` (fifteen new memories that pair with nothing: no line); `test_done_clears_the_count_and_a_new_pair_counts_one` (one pair → `Curation due: 1 item (1 same or opposite) ...`; after `--done`, no line; a new memory pairing an old one → 1 again); `test_done_on_a_mixed_store_leaves_no_line` (superseded but active, unconfirmed from a transcript, quarantined, expired, a state pair, a refuted-again pair; `--done`; no line); `test_done_prints_recorded_items`; `test_count_names_its_parts`; `test_old_pairs_are_not_searched_after_a_pass_without_marks` (pass date set, no keys file, a pair of two memories created before it with file times before it: no line); `test_edited_old_memory_pair_is_counted` (same, then one file's time set after the pass: counted); `test_marks_file_malformed_reads_as_none`; `test_done_global_keeps_project_marks`; `test_curated_json_keeps_its_format`; `test_budget_shared_across_folders_never_exceeded` (count comparisons through a wrapped `records.Budget`: at most `PAIR_WORK`); `test_past_the_budget_found_items_say_at_least_and_none_say_nothing` (monkeypatch `PAIR_WORK` small); `test_count_failure_keeps_the_rules` (`_decisions` forced to raise: no `Curation due` line, the loaded lessons still print); `test_session_index_near_the_budget_is_fast` (2000 generated memories of about 60 words each in one folder, 70 changed since the pass, so the search stays within the budget and `pairs_checked` is True; `session_index` under 1 second by `time.perf_counter`); `test_remember_prints_no_curation_count`.
- [ ] **Step 2: Run them**; expected FAIL.
- [ ] **Step 3: Implement**. Remove `records.curation_due` once nothing calls it.
- [ ] **Step 4: Run them**, then the whole suite; update and name `test_curation_due_rule`, `test_index_line_says_curation_is_due`, the `test_transcript_records.py` test and the `test_remember.py` test.
- [ ] **Step 5: Commit**: stage the named files by path; `git commit -m "feat(memory): Curation due counts the decisions the last pass did not list"`

### Task 4: Curator texts, changelog, design records and the digest dates

**Files:**
- Modify: `plugins/memory/skills/memory-curation/SKILL.md` (queue table: a `newer state of the same project?` row, action `mem supersede <old> <new>` after reading both whole, or `mem distinct`; the seen-often row's text; step 4 says `--done` records what the queue held and prints how many, so only later decisions are announced), `plugins/memory/agents/memory-curator.md` (step 2 covers the newer-state category as a proposed `supersede` row, never applied by `apply --safe`), `plugins/memory/CHANGELOG.md` (`## [Unreleased]`: the count's new meaning, its parts, the new file, `--done` printing what it recorded, no count after `mem remember`, grouped pairs, newer state, `differ in`), `plugins/memory/README.md` where it describes the count, `docs/superpowers/specs/2026-11-21-memory-capture-design.md` (reservation row C98 to C107 and phase row B7), `docs/adr/0023-a-memory-plugin-makes-a-note-store-reachable-from-every-repository.md` (`## Review 2026-11-23`: the curator and skill texts changed unmeasured; kill criteria: a curator pass that supersedes a state memory still in use; a `Curation due` line left after `--done` on an unchanged store; "at least" in three sessions in a row on the owner's store; a session-index duration over 2 seconds in the hooks log)
- Also: the digest work of 0.9.0 was dated 2026-11-24 by mistake; it was built and released on 2026-11-23 (the tag's commit). Rename `docs/superpowers/specs/2026-11-24-memory-topic-digest-design.md` and `docs/superpowers/plans/2026-11-24-memory-topic-digest.md` to `2026-11-23-…` with `git mv`, update every link to them, and change `2026-11-24` to `2026-11-23` in those two files, the 0.9.0 heading of `plugins/memory/CHANGELOG.md`, ADR 0023 (merge two `## Review` sections of the same date into one if that results), `docs/superpowers/plans/2026-11-17-memory-plugin.md` and the capture design.

- [ ] **Step 1**: Make the edits. Plain English, tables over prose; no line numbers.
- [ ] **Step 2: Check**: `python3 scripts/validate.py` and `claude plugin validate .` pass; `grep -rn "2026-11-24" docs plugins` prints nothing; every link to the renamed files resolves (`grep -rn "memory-topic-digest" docs plugins`).
- [ ] **Step 3: Commit**: stage the named files and the renames by path; `git commit -m "docs(memory): curator texts, changelog and records for the Curation due count; digest dates corrected"`

### Task 5: The count on a copy of the owner's store

**Files:**
- Modify: this plan's `## Results`; `docs/superpowers/plans/2026-11-17-memory-plugin.md` ("Current state and where to resume": unreleased work, next step)

- [ ] **Step 1**: Copy with `cp -p` (file times kept) the owner's global memory folder, this project's `.memory` folder and `curated.json` to a temporary folder; point `MEM_STORE`, `MEM_MEMORIES`, `MEM_PROJECT`, `MEM_DATA` and `XDG_STATE_HOME` there (keep `HOME`); take checksums of the real folders.
- [ ] **Step 2**: On the copy, time `bin/mem session-index --hook` end to end (three runs) on the branch and on `main`; record the count line, its parts and the length of `mem curate`; then `mem curate --done` and `mem session-index` again (expected: no line).
- [ ] **Step 3**: Checksums of the real folders unchanged. Record the figures under `## Results` without handles or claims.
- [ ] **Step 4: Commit** the two plan files by path.

## Results

Filled by Task 5.
