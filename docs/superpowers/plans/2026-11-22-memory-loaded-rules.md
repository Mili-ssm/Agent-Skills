# Memory Loaded Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Established lessons load by themselves at session start as a short list of rules, each in a short form of at most 120 characters, followed by one line that counts the recommendations that did not load and names their topics.

**Architecture:** A lesson record gains two fields, `short` and `topic`, written by the small model (never at session start). A new pure module, `engine/rules.py`, picks and orders the lessons that qualify and builds the block under a character limit; `mem.py` prints it through `mem rules` and adds it to the session start text. The corroboration pass writes the two fields for new global lessons and fills them, in one bounded run, for established lessons that lack them.

**Tech Stack:** Python 3 standard library and PyYAML, as the rest of `plugins/memory/engine`; pytest.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md), decisions C46 to C48, C52, C53 (and C13, C15, C18 to C20, C38 behind them). Research and the measurement: [the B4 handoff](2026-11-22-memory-loaded-rules-and-reminders.md).

## Global Constraints

- Session start never fails and never waits: every new call in `cmd_session_index` is inside its own `try`, a failure adds no rule lines and changes nothing else, and no model runs there. The hook's 4 second limit holds.
- A lesson in quarantine (`records.quarantined`) never appears in the rules block, in the line that follows it, or in `mem rules --more`.
- Only a record with `origin == "transcript"` and `records.standing(m) == "established"` that is live can load. A memory written by hand (`origin` absent) is reached by search, as today.
- A global lesson with `triage == "pending"` does not load; it is counted in the line that follows the block.
- The rules block is assembled by code from the records. No command rewrites the whole list with a model.
- Exact values: `short` at most 120 characters, one line; `topic` one or two lowercase words, at most 24 characters, matching `[a-z0-9][a-z0-9-]*( [a-z0-9][a-z0-9-]*)?`; rules block at most 1200 characters without its header; the line that follows at most 200 characters and at most 4 topics; the whole session start text at most 2400 characters (1500 before).
- The header, measured (C53), verbatim: `memory: rules learned in earlier sessions. Follow them unless you have a reason not to, and say so when you do not.`
- The standing after each rule is written by code, never by a model: `(confirmed by the owner)` when `owner_confirmed` is set; else for a global lesson `(held in N projects)`; else `(seen once)` for one session and `(held in N sessions)` for more.
- The hook log holds numbers only.
- At least one test runs the real hook script as a subprocess with a clean environment holding only `HOME`, `PATH`, `MEM_STORE` and `MEM_DATA` (the defect of 0.4.0 came from an environment no test used).
- A test for "cannot be read" removes the permission for real.
- Text written into the project is English. Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (about four minutes).
- The changelog line under `## [Unreleased]` is written in Task 6; the version does not change in this plan.

## Review Focus

- No lesson qualifies, or none has a short form yet (the state of every store on the day of the update): the session start text is exactly what it was, plus at most the one line that counts what did not load.
- A `short` or `topic` edited by hand into a bad value (too long, several lines, wrong type): the record still loads as a memory, the bad field reads as absent, and the lesson is counted as having no short form.
- The same lesson in the project and in the global scope (a project record linked by `general` to a global one): it loads once, as the global one.
- More rules qualify than fit: the order decides, the rest are counted, and the text stays within its limits with long project memory rows present.
- A store with thousands of memories: building the block reads each folder once and stays far inside the hook's time limit.

---

### Task 1: The `short` and `topic` fields

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `write_memory`), `plugins/memory/engine/mem.py` (`cmd_remember`, `cmd_memory` edit, `cmd_show`, their parser entries)
- Test: `plugins/memory/engine/tests/test_short_topic.py`

**Interfaces:**
- Produces:
  - `records.SHORT_LIMIT = 120`, `records.TOPIC_LIMIT = 24`, `records.valid_short(text) -> bool`, `records.valid_topic(text) -> bool`.
  - `Memory.short: str | None`, `Memory.topic: str | None`; a stored value that is not valid reads as `None` and does not make the record broken.
  - `write_memory(..., short=None, topic=None)`: raises `ValueError` on an invalid value.
  - `mem remember ... [--short TEXT] [--topic TEXT]`; `mem memory edit <h> [--global] [--short TEXT] [--topic TEXT]` (an empty value removes the field; `--short` or `--topic` alone is enough for an edit); `mem show m:<h>` prints both when set.
  - A global `--short` passes the same refusals as the claim (`_refuse_secret`, `_check_terms`).

- [ ] **Step 1: Write the failing tests**

```python
def test_remember_and_edit_store_short_and_topic(gfolder, capsys):
    assert mem.main(["remember", "--global", "--kind", "lesson", "--claim", CLAIM, "--short", "Run the checks before reporting a change.", "--topic", "testing"]) == 0
    m = records.load_memories(gfolder, "global")[0]
    assert m.short == "Run the checks before reporting a change." and m.topic == "testing"
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--global", "--short", "", "--topic", "process"]) == 0
    m = records.load_memories(gfolder, "global")[0]
    assert m.short is None and m.topic == "process"

@pytest.mark.parametrize("flag,bad", [("--short", "x" * 121), ("--short", "two\nlines"), ("--topic", "Testing"), ("--topic", "three word topic"), ("--topic", "x" * 25)])
def test_invalid_values_are_refused(flag, bad, gfolder, capsys): ...       # exit 2, nothing written

def test_a_bad_stored_value_reads_as_absent_and_keeps_the_record(gfolder): ...   # front matter `short: [1, 2]`, `topic: 7`: error is None, both None
def test_an_edit_of_the_claim_keeps_short_and_topic(gfolder, capsys): ...
def test_a_global_short_with_a_secret_is_refused(gfolder, capsys): ...      # exit 4
def test_show_prints_both(gfolder, capsys): ...
```

- [ ] **Step 2: Run them and see them fail** — `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_short_topic.py -q`.
- [ ] **Step 3: Implement.** `_render` writes the two keys after `weight`.
- [ ] **Step 4: Run the file's tests, `test_memory_edit.py`, `test_core.py` and `test_quarantine.py`**; expected: all pass.
- [ ] **Step 5: Commit** — `feat(memory): a short form and a topic on a lesson record`

### Task 2: Choosing and building the rules

**Files:**
- Create: `plugins/memory/engine/rules.py`
- Modify: `plugins/memory/engine/mem.py` (new `cmd_rules`, parser entry, `_NO_STORE_NEEDED`)
- Test: `plugins/memory/engine/tests/test_rules.py`

**Interfaces:**
- Consumes: Task 1; `records.is_live`, `records.standing`, `records.quarantined`, `records.sessions`, `records.projects`.
- Produces:
  - `HEADER` (the verbatim header of Global Constraints), `RULES_LIMIT = 1200`, `MORE_LIMIT = 200`, `TOPICS_NAMED = 4`.
  - `@dataclass Choice`: `loaded: list[Memory]`, `left: list[tuple[Memory, str]]` with the reason one of `"awaits triage"`, `"over the limit"`, `"no short form"`.
  - `choose(project: Sequence[Memory], global_: Sequence[Memory], today, limit: int = RULES_LIMIT) -> Choice`. Qualifies: live, `origin == "transcript"`, standing `established`, not quarantined. A project record whose `general` names a live global record that qualifies is dropped (the global one stands for it). Of those: `triage == "pending"` goes to `left` as `awaits triage`; no `short` goes to `left` as `no short form`; the rest are ordered and loaded while the sum of their line lengths (plus one newline each) stays within `limit`, the others go to `left` as `over the limit`.
  - Order, most significant first: `owner_confirmed` set; weight (`strong`, `medium`, `light`; absent counts as `medium`); number of projects; number of sessions; `last_observed` (newest first, absent last); handle.
  - `standing_words(m) -> str` (Global Constraints) and `line(m) -> str`: `- <short> <standing_words>`.
  - `block(choice) -> list[str]`: empty when nothing loaded, else `[HEADER, *lines]`.
  - `more_line(choice) -> str | None`: `None` when `left` is empty. `N more recommendations on <t1>, <t2>: mem rules --more`, with the topics of `left` by how many lessons carry them (then alphabetically), at most 4, the count of all of `left`; `1 more recommendation`; without topics `N more recommendations: mem rules --more`; topics are removed from the end until the line fits 200 characters.
  - `mem rules`: prints the block and the line exactly as session start will, or `No rules loaded.`; `mem rules --more`: one line per left-out lesson: handle, scope, reason, topic or `-`, and the claim cut at 160 characters.

- [ ] **Step 1: Write the failing tests** — build `Memory` objects through `mem.main(["remember", ...])` with `--origin transcript --weight ... --source "session a project <key>"`, as `test_quarantine.py` does.

```python
def test_only_established_transcript_lessons_with_a_short_form_load(both_scopes): ...
    # loaded: a confirmed global one, a project one seen once; not loaded: a hand-written memory, a quarantined one, an unconfirmed project one

def test_order_is_confirmed_then_weight_then_corroboration_then_recency(): ...   # six records, one differing key each

def test_lines_carry_the_standing_written_by_code():
    assert rules.line(confirmed) == "- Run the checks before reporting a change. (confirmed by the owner)"
    assert rules.line(global_two_projects).endswith("(held in 2 projects)")
    assert rules.line(project_once).endswith("(seen once)") and rules.line(project_three).endswith("(held in 3 sessions)")

def test_the_limit_moves_the_last_ones_to_left(): ...            # limit=260 with three lines of ~100: two loaded, one "over the limit"
def test_pending_triage_and_no_short_form_are_counted_not_loaded(): ...
def test_quarantine_is_nowhere(): ...                            # not in block, more_line, or `mem rules --more` output
def test_a_project_record_linked_to_a_loaded_global_one_loads_once(): ...
def test_more_line_names_topics_by_frequency_and_fits():
    assert rules.more_line(choice) == "5 more recommendations on testing, process, shell: mem rules --more"
def test_more_line_singular_and_without_topics(): ...
def test_nothing_qualifies_gives_an_empty_block_and_no_line(): ...
def test_mem_rules_prints_what_loads_and_more_lists_the_rest(project, gfolder, capsys): ...
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement `rules.py` and `cmd_rules`.**
- [ ] **Step 4: Run the file's tests and `test_core.py`**; expected: all pass.
- [ ] **Step 5: Commit** — `feat(memory): choose and build the loaded rules; mem rules`

### Task 3: The rules in the session start text

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`_INDEX_LIMIT`, `session_index`, `cmd_session_index`)
- Test: `plugins/memory/engine/tests/test_rules_session.py`

**Interfaces:**
- Consumes: `rules.choose`, `rules.block`, `rules.more_line`.
- Produces:
  - `_INDEX_LIMIT = 2400`.
  - `session_index(..., rules_lines: Sequence[str] = ())`: the block and the line go after the rule lines of `_INDEX_RULES` and after `notice`, before the project memory rows. When the text is over the limit, project rows are dropped first (as today); if it is still over with no row left, rule lines are dropped from the last one, never the header alone (a header with no rule is removed) and never the line that counts what did not load.
  - `cmd_session_index` builds the choice once from the project's and the global folder's records, in its own `try`; the hook log line gains `"rules": <number loaded>`, `"rules_left": <number left>`, `"rules_chars": <characters of block and line>`.
  - The head line's count `This project: N memories.` and the project rows are unchanged; a lesson that loads as a rule may also appear as a row.

- [ ] **Step 1: Write the failing tests**

```python
def test_with_no_lesson_the_text_is_what_it_was(project, gfolder, capsys): ...      # compare with the text captured before any transcript lesson exists
def test_rules_block_and_more_line_are_in_the_text_in_order(project, gfolder, capsys):
    ...; assert out.index(rules.HEADER) < out.index("- Run the checks") < out.index("more recommendation") and out.index(rules.HEADER) > out.index("To remember:")
def test_project_rows_give_way_before_any_rule(project, gfolder, capsys): ...       # 40 long project memories, --list 50: every rule line present, len(text) <= 2400
def test_a_failure_while_choosing_changes_nothing_else(project, gfolder, capsys, monkeypatch): ...   # rules.choose raises: text equals the text without rules
def test_an_unreadable_global_folder_keeps_the_text(project, gfolder, capsys): ...   # chmod 0, restored in finally
def test_the_hook_log_counts_rules(project, gfolder, capsys): ...                   # "rules": 2, "rules_left": 1, numbers only
def test_the_real_hook_script_with_only_mem_store(tmp_path):
    # subprocess: hooks/session-index.sh; env only HOME, PATH, MEM_STORE (a store with mem-store.yaml), MEM_DATA; cwd a real git project.
    # One established global lesson with a short form written under the same environment with bin/mem, one project lesson likewise.
    ...; assert rules.HEADER in out and "(confirmed by the owner)" in out and "(seen once)" in out
def test_two_thousand_memories_build_in_under_a_second(tmp_path): ...               # time cmd_session_index; assert < 1.0 s
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite once, in the background**; expected: all pass, 5 skipped.
- [ ] **Step 5: Commit** — `feat(memory): established lessons load as rules at session start`

### Task 4: The small model writes the short form and the topic

**Files:**
- Modify: `plugins/memory/engine/corroborate.py` (`validate_groups`, `verification_lines`, `actions`; new `fill_candidates`, `validate_fill`), `plugins/memory/bin/mem-corroborate` (the proposal brief, the write of a global record, a new `fill` step and subcommand)
- Test: `plugins/memory/engine/tests/test_corroborate.py`, `plugins/memory/engine/tests/test_mem_corroborate.py`

**Interfaces:**
- Consumes: Task 1 (`--short`, `--topic` on `mem remember` and `mem memory edit`), `records.valid_short`, `records.valid_topic`.
- Produces:
  - A proposed group gains `short` and `topic` (both required for a group that will write a new global record; a group with either invalid is refused like a group with a bad claim). The verifying session sees the short form beside the reworded claim, and its `faithful` answer covers both.
  - `actions` passes them on; the global record is written with `--short` and `--topic`.
  - `corroborate.fill_candidates(project, global_, today, cap=30) -> list[tuple[str, Memory]]`: established, not quarantined lessons (as `rules.choose` qualifies them) with no `short` or no `topic`, ids `g:<handle>` and `p:<handle>`, the confirmed and the most corroborated first, at most `cap`.
  - `corroborate.validate_fill(payload, ids) -> tuple[dict[str, dict], list[str]]`: `{"items": [{"id", "short", "topic"}]}`; an item with an unknown id or an invalid field is dropped with a reason.
  - `mem-corroborate fill [--dry-run --out FILE] [--items FILE]`: one proposing session and one verifying session (`faithful` per item, as the pass does); writes each kept item with `mem memory edit <h> [--global] --short ... --topic ...`; journal and `undo` as the pass; a line in `corroborate/log.jsonl` with `"fill": {"asked", "written", "dropped"}`.
  - `mem-corroborate auto` runs `fill` after the pass when `fill_candidates` is not empty, under the same budget and lock.
- The brief for a short form, verbatim: `short: one sentence of at most 120 characters that says what to do and when, in the form of a suggestion or a recommendation, never stronger than the claim. It must stand on its own, name no project, person or company, and add nothing the claim does not say. topic: one or two lowercase words for the area (for example: testing, process, shell, review, docs).`

- [ ] **Step 1: Write the failing tests** — unit tests for `validate_groups` with and without the two fields, `validate_fill` (unknown id, short of 121 characters, topic with a capital), `fill_candidates` (quarantine excluded, cap, order); and, with the fake `claude` the existing tests of `test_mem_corroborate.py` use, one test that a pass writes a global record carrying both fields, one that `fill --dry-run --out` writes nothing and `fill --items FILE` writes exactly the kept items, one that `undo` puts the records back, one that a refused item (`faithful` false) is not written.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `test_corroborate.py`, `test_mem_corroborate.py`, `test_capture_auto.py`**; expected: all pass.
- [ ] **Step 5: Commit** — `feat(memory): the corroboration pass writes a lesson's short form and topic`

### Task 5: Only grave lessons wait for the owner (C52)

**Do not start this task without the owner's word on C52's reading** (only weight `strong` waits). Tasks 1 to 4 and 6 do not depend on it: without it every released global lesson keeps waiting at triage, as today.

**Files:**
- Modify: `plugins/memory/engine/records.py` (`TRIAGES`, `standing_changes`), `plugins/memory/engine/mem.py` (`cmd_triage`, the triage part of `cmd_curate`, the `Triage:` count of `session_index`)
- Test: `plugins/memory/engine/tests/test_triage_grave.py`

**Interfaces:**
- Produces:
  - `TRIAGES = ("pending", "review")`. On the first establishment of a global transcript record without the owner's confirmation: `released = today`, and `triage = "pending"` when its weight is `strong`, else `"review"`.
  - `review` loads (it is not `pending`); `mem triage accept` clears either value; `mem triage reject` works on either.
  - `mem curate --global` lists the two groups apart: `Await triage (do not load yet)` and `Loaded, to review`; the session start count `Triage:` counts `pending` only.

- [ ] **Step 1: Write the failing tests** — a light lesson seen in two projects is released with `review` and is in `rules.choose(...).loaded`; a strong one seen in three sessions across two projects is released with `pending` and is in `left` as `awaits triage`; `accept` and `reject` on both; the curate listing; the session start count; a record written by 0.4.1 with `triage: pending` and weight light keeps `pending` (no silent change of an existing record).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the file's tests, `test_quarantine.py`, `test_confirm_owner.py`, `test_curation.py`, `test_rules.py`**; expected: all pass.
- [ ] **Step 5: Commit** — `feat(memory): only a strong lesson waits at triage before it loads`

### Task 6: Documentation

**Files:**
- Modify: `plugins/memory/README.md` (a `## Loaded rules` section after "Corroboration, quarantine and triage"; the limits table), `plugins/memory/CHANGELOG.md` (`## [Unreleased]`), `docs/adr/0023-*.md` (append `### Stage B4: loaded rules`), `docs/superpowers/plans/2026-11-17-memory-plugin.md` (state table, "Current state and where to resume"), the Phases row B4 of the spec.
- Test: `python3 scripts/port.py --check`, `python3 scripts/validate.py`, `claude plugin validate .`

- [ ] **Step 1: README.** What loads and what never does (quarantine, hand-written memories, pending triage); the header and one example block; the order; the limits; `mem rules`, `mem rules --more`, `--short`, `--topic`, `mem-corroborate fill`; who writes the short form; how to change or remove a rule (`mem memory edit --short`, `mem triage reject`, `mem forget`); limits as a table.
- [ ] **Step 2: CHANGELOG**, for users: after the update nothing loads until lessons have a short form; the session start text may grow up to 2400 characters; the migration note (`mem-corroborate fill --dry-run --out FILE` to see the short forms first).
- [ ] **Step 3: ADR 0023 section.** Decisions by reference; the measurement of C53 by reference; what ships unmeasured (the brief for the short form; rules beside the owner's own instruction files); kill criteria (below).
- [ ] **Step 4: State tables; run the three validation commands**; expected: all exit 0.
- [ ] **Step 5: Commit** — `docs(memory): loaded rules in the README, changelog and ADR 0023`

---

## After the tasks

- [ ] Gate on a private copy of the real store and of this project's memory folder: `mem-corroborate fill --dry-run --out FILE` with the real small model; the short forms and topics of the established lessons go to the owner as one table, once (the first batch only; later ones go by themselves, C52). Record how many the verifying session refused.
- [ ] With the kept items applied on the copy: `mem rules` and the real hook script; read the text and its length.
- [ ] Three runs with a real model, the real rules loaded and a task on which at least one of them bears; one run with the owner's own instruction file present. Record the outcome in ADR 0023 as observed.
- [ ] Narrow reviews in parallel (the two modules; the commands against this plan; the docs against the code), then one fix wave.
- [ ] Pull request to `dev` and release only with the owner's word.

## Known limits

Filled in by the pre-mortem and at the end of execution.

## Kill criteria

- The subprocess test of Task 3 fails with `MEM_STORE` alone: fix the lookup, not the test.
- In the gate, the verifying session refuses more than a third of the short forms, or the owner rejects more than a fifth of those kept: the brief is not good enough to go by itself; C52 falls back to review before loading.
- In the three real runs no loaded rule that bears on the task is followed: stop before release and re-read C53's limits.
- After release, the hook's `ms` at the 99th percentile in `hooks/log.jsonl` is over 1500 (the slowest run seen before was 742): build the block outside the hook.
- After two weeks, the same lesson is captured again in sessions where it was loaded (read by hand from the capture log until C49 is built): the rule is loaded and not followed; revisit its wording or its place on the ladder of C18.
