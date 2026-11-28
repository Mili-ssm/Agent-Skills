# Memory Loaded Rules Implementation Plan

Status: done · merged in #161, 2026-11-22 · unticked boxes are not open work

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A few established lessons load by themselves at session start as short rules, each in a short form of at most 120 characters, followed by one line that counts the recommendations that did not fit and names their topics; any one rule can be turned off without losing the lesson.

**Architecture:** A lesson record gains three fields: `short`, `topic` and `load`. A new pure module, `engine/rules.py`, picks and orders the lessons that qualify and builds the block under a line and a character limit; `mem.py` prints it through `mem rules` and adds it to the session start text. A manual command, `mem-corroborate fill`, has the small model propose the short form and the topic of the lessons that lack them, for the owner to read before they are applied. Nothing in this release writes a short form without that reading.

**Tech Stack:** Python 3 standard library and PyYAML, as the rest of `plugins/memory/engine`; pytest.

**Spec:** [the capture design](../../specs/2026-11-21-memory-capture-design.md), decisions C46 to C48, C53, C54 (and C13, C15, C18 to C20, C38 behind them). Research and the measurement: [the B4 handoff](../2026-11-22-memory-loaded-rules-and-reminders.md).

## Scope of this release, and what waits

The pre-mortem of 2026-11-22 found that the first draft would have loaded lessons nobody had read, the same eight in every project, with no way to turn one off. This release is the smaller one it proposed (C54).

| In this release | Waits for a later plan |
|---|---|
| Lessons that are established, have a short form, and are not turned off; a project lesson also needs two sessions or the owner's confirmation | A project lesson seen once |
| Short forms proposed by the small model on request and applied after the owner read them | The corroboration pass writing them for new lessons, and filling them by itself (C52) |
| Every released global lesson waits at triage, as today | Only grave lessons waiting (C52, confirmed by the owner on 2026-11-22) |
| At most 6 rules and 900 characters | Usefulness of a loaded lesson (C49), which needs a date on each sighting |

## Global Constraints

- Session start never fails and never waits: every new call in `cmd_session_index` is inside its own `try`, a failure adds no rule lines and changes nothing else, and no model runs there. The hook's 4 second limit holds. The records `session_index` already loads are reused, never loaded twice.
- With no lesson that qualifies, the session start text is byte for byte what it was.
- A lesson in quarantine (`records.quarantined`) never appears in the rules block, in the line that follows it, or in `mem rules --more`.
- A lesson loads only when all of these hold: live; `origin == "transcript"`; `records.standing(m) == "established"`; `triage` is not `pending`; `load` is not `no`; it has a valid `short`; and, for a project lesson, it was seen in at least two sessions or `owner_confirmed` is set.
- The rules block is assembled by code from the records. No command rewrites the list with a model, and nothing writes a `short` without the owner having read it (`fill` proposes into a file; `fill --items FILE` applies that file).
- Exact values: `short` at most 120 characters, one line; `topic` one or two lowercase words, at most 24 characters, matching `[a-z0-9][a-z0-9-]*( [a-z0-9][a-z0-9-]*)?`; `load` absent, `index` (C55: never among the rules, counted in the line that follows) or `no`; at most 6 rules and 900 characters of rule lines (header not counted); the line that follows at most 200 characters and at most 4 named topics.
- The header, measured (C53), verbatim: `memory: rules learned in earlier sessions. Follow them unless you have a reason not to, and say so when you do not.`
- The standing after each rule is written by code: `(confirmed by the user)` when `owner_confirmed` is set; else for a global lesson `(held in N projects)`; else `(held in N sessions)`.
- An edit of a lesson's claim removes its `short` (the command says so), because a short form must never outlive the claim it was drawn from.
- The existing limit of the session start text (`_INDEX_LIMIT`, 1500 characters, applied to the project rows) is not changed: it is applied to the text without the rules block, which has its own limits.
- The hook log holds numbers only.
- One test runs the real hook script as a subprocess with a clean environment holding only `HOME`, `PATH`, `MEM_STORE` and `MEM_DATA`.
- A test for "cannot be read" removes the permission for real.
- Text written into the project is English. Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (about four minutes).
- The changelog line under `## [Unreleased]` is written in Task 5; the version does not change in this plan.

## Review Focus

- The day of the update: no record has a `short`. Nothing loads, no line is added, and `mem rules` says how to get the first ones.
- A `short`, `topic` or `load` edited by hand into a bad value: the record still loads as a memory, the bad field reads as absent.
- The same lesson in the project and in the global scope (a project record whose `general` names a global one): it loads once, as the global one.
- More rules qualify than fit: the order decides, the rest are counted in one line, and the block never passes 6 lines or 900 characters.
- A rule the owner turned off (`load: no`) stays off: no command proposes a short form for it again or counts it as waiting.

---

### Task 1: The `short`, `topic` and `load` fields

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `write_memory`), `plugins/memory/engine/mem.py` (`cmd_remember`, `cmd_memory` edit, `cmd_show`, their parser entries)
- Test: `plugins/memory/engine/tests/test_short_topic.py`

**Interfaces:**
- Produces:
  - `records.SHORT_LIMIT = 120`, `records.TOPIC_LIMIT = 24`, `records.valid_short(text) -> bool`, `records.valid_topic(text) -> bool`.
  - `Memory.short: str | None`, `Memory.topic: str | None`, `Memory.load: str | None` (`"no"` or `None`); a stored value that is not valid reads as `None` and does not make the record broken.
  - `write_memory(..., short=None, topic=None)`: raises `ValueError` on an invalid value.
  - `mem remember ... [--short TEXT] [--topic TEXT]`; `mem memory edit <h> [--global] [--short TEXT] [--topic TEXT] [--no-load | --load]` (an empty `--short` or `--topic` removes the field; any one of these flags alone is enough for an edit).
  - `mem memory edit <h> --claim TEXT` without `--short` removes `short` and prints on stderr `mem: the short form was removed with the old claim: write a new one with --short`.
  - `mem show m:<h>` prints `short`, `topic` and `load: no` when set.
  - A global `--short` passes the same refusals as the claim (`_refuse_secret`, `_check_terms`).

- [x] **Step 1: Write the failing tests**

```python
def test_remember_and_edit_store_short_and_topic(gfolder, capsys):
    assert mem.main(["remember", "--global", "--kind", "lesson", "--claim", CLAIM, "--short", "Run the checks before reporting a change.", "--topic", "testing"]) == 0
    m = records.load_memories(gfolder, "global")[0]
    assert m.short == "Run the checks before reporting a change." and m.topic == "testing" and m.load is None
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--global", "--short", "", "--topic", "process", "--no-load"]) == 0
    m = records.load_memories(gfolder, "global")[0]
    assert m.short is None and m.topic == "process" and m.load == "no"
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--global", "--load"]) == 0
    assert records.load_memories(gfolder, "global")[0].load is None

@pytest.mark.parametrize("flag,bad", [("--short", "x" * 121), ("--short", "two\nlines"), ("--topic", "Testing"), ("--topic", "three word topic"), ("--topic", "x" * 25)])
def test_invalid_values_are_refused(flag, bad, gfolder, capsys): ...       # exit 2, nothing written

def test_a_bad_stored_value_reads_as_absent_and_keeps_the_record(gfolder): ...   # front matter `short: [1, 2]`, `topic: 7`, `load: maybe`: error is None, all three None
def test_an_edit_of_the_claim_removes_the_short_form_and_says_so(gfolder, capsys): ...   # topic and load are kept
def test_an_edit_of_claim_and_short_together_keeps_the_new_short(gfolder, capsys): ...
def test_confirm_merge_and_triage_keep_the_three_fields(gfolder, capsys): ...   # the kept record of a merge keeps its own
def test_a_global_short_with_a_secret_is_refused(gfolder, capsys): ...      # exit 4
def test_show_prints_the_fields(gfolder, capsys): ...
```

- [x] **Step 2: Run them and see them fail** — `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_short_topic.py -q`.
- [x] **Step 3: Implement.** `_render` writes the keys after `weight`.
- [x] **Step 4: Run the file's tests, `test_memory_edit.py`, `test_core.py` and `test_quarantine.py`**; expected: all pass.
- [x] **Step 5: Commit** — `feat(memory): a short form, a topic and a load switch on a lesson record`

### Task 2: Choosing and building the rules

**Files:**
- Create: `plugins/memory/engine/rules.py`
- Modify: `plugins/memory/engine/mem.py` (new `cmd_rules`, parser entry, `_NO_STORE_NEEDED`)
- Test: `plugins/memory/engine/tests/test_rules.py`

**Interfaces:**
- Consumes: Task 1; `records.is_live`, `records.standing`, `records.quarantined`, `records.sessions`, `records.projects`.
- Produces:
  - `HEADER` (verbatim, Global Constraints), `RULES_MAX = 6`, `RULES_LIMIT = 900`, `MORE_LIMIT = 200`, `TOPICS_NAMED = 4`.
  - `@dataclass Choice`: `loaded: list[Memory]`; `left: list[tuple[Memory, str]]` with the reason `"over the limit"` or `"awaits triage"`; `unready: int`, the number of lessons that would qualify but have no valid `short`.
  - `eligible(m, today) -> bool`: every condition of Global Constraints except `triage` and `short`.
  - `choose(project: Sequence[Memory], global_: Sequence[Memory], today) -> Choice`. Of the eligible ones: a project record whose `general` names an eligible global record is dropped; `triage == "pending"` goes to `left` as `awaits triage`; no valid `short` adds 1 to `unready`; the rest are ordered and loaded while the count stays within `RULES_MAX` and the sum of the line lengths (plus one newline each) within `RULES_LIMIT`; the others go to `left` as `over the limit`.
  - Order: project lessons first, at most 3 of them; then all remaining ones together. Inside each group, most significant first: `owner_confirmed` set; weight (`strong`, `medium`, `light`; absent counts as `medium`); number of projects; number of sessions; `last_observed` (newest first, absent last); handle.
  - `standing_words(m) -> str` and `line(m) -> str`: `- <short> <standing_words>`.
  - `block(choice) -> list[str]`: empty when nothing loaded, else `[HEADER, *lines]`.
  - `more_line(choice) -> str | None`: `None` when `left` is empty. `N more recommendations by topic: <t1> <n1>, <t2> <n2>, other <k> (mem rules --more <topic>)`, with the topics of `left` by how many lessons carry them (then alphabetically), at most 4 named; the lessons of any further topic and those with no topic are summed as `other <k>` (left out when 0); `1 more recommendation`; when no lesson of `left` has a topic: `N more recommendations: mem rules --more`; named topics are folded into `other` from the end until the line fits 200 characters.
  - `mem rules`: prints the block and the line exactly as session start will. With nothing loaded: `No rules loaded.`, and when `unready > 0` a second line `<N> established lessons have no short form: mem-corroborate fill --dry-run --out FILE proposes them.`
  - `mem rules --more [TOPIC]`: one line per left-out lesson, grouped by topic: handle, scope, reason, topic or `-`, and the claim cut at 160 characters; with TOPIC only that group (`other` gives the lessons with no topic); then the `unready` count.

- [x] **Step 1: Write the failing tests** — records written through `mem.main(["remember", ...])` with `--origin transcript --weight ... --source "session a project <key>"`, and `mem confirm ... --by-owner` where needed, as `test_quarantine.py` and `test_confirm_owner.py` do.

```python
def test_what_loads_and_what_does_not(both_scopes): ...
    # loaded: a confirmed global one, a project one seen in two sessions.
    # not loaded: a hand-written memory, a quarantined one, a project one seen once, one with load: no, one with no short (unready == 1)

def test_order_inside_a_group(): ...                              # six records, one differing key each
def test_project_lessons_come_first_and_take_at_most_three(): ...   # five project and five global ones: 3 project then 3 global load

def test_lines_carry_the_standing_written_by_code():
    assert rules.line(confirmed) == "- Run the checks before reporting a change. (confirmed by the user)"
    assert rules.line(global_two_projects).endswith("(held in 2 projects)") and rules.line(project_three).endswith("(held in 3 sessions)")

def test_never_more_than_six_lines_or_900_characters(): ...       # ten that qualify, each 120 characters: loaded <= 6, sum <= 900, the rest "over the limit"
def test_pending_triage_is_counted_not_loaded(): ...
def test_quarantine_and_turned_off_lessons_are_nowhere(): ...     # not in block, more_line, unready, or `mem rules --more`
def test_a_project_record_linked_to_a_loaded_global_one_loads_once(): ...
def test_more_line_names_topics_by_frequency_and_fits():
    assert rules.more_line(choice) == "7 more recommendations by topic: testing 3, process 2, shell 1, other 1 (mem rules --more <topic>)"
def test_more_with_a_topic_prints_only_that_group(project, gfolder, capsys): ...
def test_more_line_singular_and_without_topics(): ...
def test_nothing_qualifies_gives_an_empty_block_and_no_line(): ...
def test_mem_rules_and_more(project, gfolder, capsys): ...         # including the `No rules loaded.` texts
```

- [x] **Step 2: Run them and see them fail.**
- [x] **Step 3: Implement `rules.py` and `cmd_rules`.**
- [x] **Step 4: Run the file's tests and `test_core.py`**; expected: all pass.
- [x] **Step 5: Commit** — `feat(memory): choose and build the loaded rules; mem rules`

### Task 3: The rules in the session start text

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`session_index`, `cmd_session_index`)
- Test: `plugins/memory/engine/tests/test_rules_session.py`

**Interfaces:**
- Consumes: `rules.choose`, `rules.block`, `rules.more_line`.
- Produces:
  - `session_index` builds the choice from the project and global records it already loads (no second read of either folder), inside its own `try`, and places the block and the line after the rule lines of `_INDEX_RULES` and after `notice`, before the project rows. The 1500 character limit keeps applying to the text without the block and the line.
  - `session_index` returns the text as today; the numbers for the log are exposed without changing its signature for existing callers (for example an optional `stats: dict | None = None` argument that it fills).
  - The hook log line gains `"rules": <number loaded>`, `"rules_left": <number left>`, `"rules_chars": <characters of block and line>`.

- [x] **Step 1: Write the failing tests**

```python
def test_with_no_short_form_anywhere_the_text_is_byte_for_byte_what_it_was(project, gfolder, capsys): ...
    # established lessons exist but none has a short: compare with the text of a store that holds the same records
def test_rules_block_and_more_line_are_in_the_text_in_order(project, gfolder, capsys):
    ...; assert out.index("To remember:") < out.index(rules.HEADER) < out.index("- Run the checks") < out.index("more recommendation")
def test_project_rows_keep_their_own_limit(project, gfolder, capsys): ...        # 40 long project memories, --list 50: every rule line present; the text minus the block and the line is <= 1500
def test_a_failure_while_choosing_changes_nothing_else(project, gfolder, capsys, monkeypatch): ...   # rules.choose raises
def test_an_unreadable_global_folder_keeps_the_text(project, gfolder, capsys): ...   # chmod 0, restored in finally
def test_the_hook_log_counts_rules(project, gfolder, capsys): ...                # numbers only
def test_the_folders_are_read_once(project, gfolder, capsys, monkeypatch): ...   # count calls of records.load_memories per folder
def test_the_real_hook_script_with_only_mem_store(tmp_path):
    # subprocess: hooks/session-index.sh; env only HOME, PATH, MEM_STORE (a store with mem-store.yaml), MEM_DATA; cwd a real git project.
    # One confirmed global lesson and one project lesson seen twice, both with a short form, written under the same environment with bin/mem.
    ...; assert rules.HEADER in out and "(confirmed by the user)" in out and "(held in 2 sessions)" in out
```

- [x] **Step 2: Run them and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the whole suite once, in the background**; expected: all pass, 5 skipped.
- [x] **Step 5: Commit** — `feat(memory): established lessons load as rules at session start`

### Task 4: Proposing short forms for the owner to read

**Files:**
- Modify: `plugins/memory/engine/corroborate.py` (new `fill_candidates`, `fill_lines`, `validate_fill`), `plugins/memory/bin/mem-corroborate` (new subcommand `fill`)
- Test: `plugins/memory/engine/tests/test_corroborate.py`, `plugins/memory/engine/tests/test_mem_corroborate.py`

**Interfaces:**
- Consumes: Task 1 (`mem memory edit --short --topic`), `rules.eligible`, `corroborate.counted_projects` and the id scheme of `corroborate.collect` (`g:<handle>` for a global record, `p<n>:<handle>` for the n-th project).
- Produces:
  - `corroborate.fill_candidates(projects, global_, today, cap=30) -> list[tuple[str, Memory]]`: lessons for which `rules.eligible` holds, whose `triage` is not `pending`, and that lack a valid `short` or `topic`; the confirmed and the most corroborated first; at most `cap`. A lesson with `load: no` or in quarantine is never a candidate.
  - `corroborate.fill_lines(candidates) -> str`: what the model reads, one lesson per block: id, claim, context.
  - `corroborate.validate_fill(payload, ids) -> tuple[dict[str, dict], list[str]]`: `{"items": [{"id", "short", "topic"}]}`; an item with an unknown id, a repeated id or an invalid field is dropped with a reason; the rest are kept.
  - `mem-corroborate fill --dry-run --out FILE`: one session of the small model, with the tools, environment and budget rules of the pass's proposing session; writes to FILE a JSON list of `{id, handle, scope, claim, short, topic}` for the kept items and prints the count kept and dropped. It changes no record.
  - `mem-corroborate fill --items FILE`: applies a file of that form (the owner may have edited or deleted entries): each item through `mem memory edit <handle> [--global] --short ... --topic ...`, run for the right project as the pass's `Applier` does; journal and `undo <stamp>` as the pass; one line in `corroborate/log.jsonl` with `"fill": {"asked", "written", "dropped", "failed"}`.
  - `fill` with neither flag prints its usage and exits 2: nothing in this release writes a short form unread.
- The brief for the model, verbatim: `For each lesson write: short: one sentence of at most 120 characters that says what to do and when, as a suggestion or a recommendation, never stronger than the claim. Keep a hedge the claim has (may, once, sometimes, provisional). It must stand on its own, name no project, person or company, and add nothing the claim does not say. topic: one or two lowercase words for the area (for example: testing, process, shell, review, docs). An id is copied whole.`

- [x] **Step 1: Write the failing tests** — unit: `fill_candidates` (quarantine, `load: no`, pending triage and a project lesson seen once are excluded; cap; order), `validate_fill` (unknown id, repeated id, short of 121 characters, topic with a capital, a kept item). With the fake `claude` that `test_mem_corroborate.py` already uses: `fill --dry-run --out` writes the file and changes no record; `fill --items FILE` writes exactly the items of the file, in two projects that share a handle and in the global scope; `undo` puts the records back; an item whose record changed its claim since the file was made is not written (`failed`); `fill` alone exits 2.
- [x] **Step 2: Run them and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run `test_corroborate.py`, `test_mem_corroborate.py`**; expected: all pass.
- [x] **Step 5: Commit** — `feat(memory): mem-corroborate fill proposes a lesson's short form and topic`

### Task 5: Documentation

**Files:**
- Modify: `plugins/memory/README.md` (a `## Loaded rules` section after "Corroboration, quarantine and triage"; the limits table), `plugins/memory/skills/memory-curation/SKILL.md` (one short paragraph: a rule that is wrong is turned off with `mem memory edit --no-load`, reworded with `--claim` then `--short`, or forgotten), `plugins/memory/CHANGELOG.md` (`## [Unreleased]`), `docs/adr/0023-*.md` (append `### Stage B4: loaded rules, the same day`), `docs/superpowers/plans/2026-11-17-memory-plugin.md` (state table, "Current state and where to resume"), the Phases row B4 of the spec.
- Test: `python3 scripts/port.py --check`, `python3 scripts/validate.py`, `claude plugin validate .`

- [x] **Step 1: README.** What loads and what never does; the header and one example block; the order; the limits; `mem rules`, `mem rules --more`, `--short`, `--topic`, `--no-load`, `mem-corroborate fill`; how to change or remove one rule; limits as a table (below).
- [x] **Step 2: Curation skill paragraph and CHANGELOG**, the latter for users: after the update nothing loads until lessons have a short form, and the two commands that give them one.
- [x] **Step 3: ADR 0023 section.** Decisions by reference; the measurement of C53 by reference; what ships unmeasured (the brief for the short form; rules beside the owner's own instruction files); the kill criteria below.
- [x] **Step 4: State tables; run the three validation commands**; expected: all exit 0.
- [x] **Step 5: Commit** — `docs(memory): loaded rules in the README, the curation skill, the changelog and ADR 0023`

---

## After the tasks

- [x] Gate on a private copy of the real global lessons, with the real small model (2026-11-22): `fill --dry-run` asked 15, kept 13, dropped 2 whose short form passed 120 characters; cost 0.004 USD. The 13 keep the hedges of their claims (the author's reading; the owner's reading is pending). A second dry run dropped the same two again; since then such a proposal stays in the file marked with its problem.
- [x] The 13 applied on the copy: `mem rules` loads 6 and the real hook prints 1692 characters (the owner's hook log held a median of 644 over 63 session starts before). Thirteen of the fifteen lessons tie on every order key, so most of the six were the first by handle: the reason for the index-only state (C55).
- [x] Runs with a real model, the real plugin and five general rules loaded from the copy, on a task with an ambiguous term: without rules the model stated its reading in 2 of 3 runs (mean 0.054 USD), with rules in 2 of 3 (0.064 USD), and with the owner's instruction file beside them in none of 1 (0.098 USD). No reply announced a rule it did not follow and none went against the instruction file. No effect measurable on this task, whose base rate is high; no harm. A first batch was void: with no store option the hook switches to the default store, which the test's temporary folders had created empty.
- [x] The owner's reading (2026-11-22): two batches of five read, all to load, with "the user" in place of "the owner" (C56) and one short form widened back to its claim; then the owner said this should work with no interaction, so the last five were set to load by the author, two of them with short forms written by hand (the small model passed 120 characters twice). The file of 15 was applied on a fresh copy (15 written), then on the real store (15 written, 0 dropped, 0 failed); a copy of the file is kept in the data folder under `corroborate/`. They take effect once a version with the loaded rules is installed.
- [x] Reviews: one per task, a docs review and a process review, with three fix waves; whole suite 1781 passed, 5 skipped.
- [x] Pull request 161 merged into `dev` with the owner's word (2026-11-22).
- [x] Before the release, at the owner's request: a prompt review and a release review. The loaded wording changed (C57) and was measured again (3 of 3 and 3 of 3); the short-form brief changed and gave 15 of 15 valid short forms in three runs; an option switches the feature off; the capture keeps a step the user asked for that paid off (C58), kept in 2 of 2 trial runs.
- [x] Released as memory 0.5.0 on 2026-11-22 (pull requests 162 and 163, tag `memory-v0.5.0`) and installed. First session start text of the installed version on the owner's store: 6 lessons loaded, 9 in the index line, 1810 characters, 162 ms in the hook log.
- [ ] Next plans: short forms written with no reading and only strong lessons waiting at triage (C52); usefulness of a loaded lesson (C49); the `Curation due` count shown at every session start; whether text for a main session should say "the user" beyond the loaded rules (C56 keeps "owner" elsewhere).

## Known limits

From the pre-mortem of 2026-11-22.

| Limit | Why it stays |
|---|---|
| A new global lesson has no short form until `fill` is run by hand and its file read | Nothing unread loads in this release (C54); the automatic path is the next plan (C52) |
| A project lesson seen once never loads | It was read by nobody; one of today's would contradict the owner's instructions |
| All fifteen global lessons that qualify today tie on most keys, so which six load is decided by the latest sighting and the handle | Corroboration will separate them; the owner can turn any off |
| A rule may repeat what the owner's instruction files already say | The gate's table lets the owner turn those off |
| Rules do not reach subagents | The session start hook runs in the main session only |
| Every loaded rule gets the same space, not more by weight (C19) | Six lines leave nothing to share out |
| "Loaded and it still happened" is read by hand from the capture log | C49 needs a date on each sighting |

## Kill criteria

- The subprocess test of Task 3 fails with `MEM_STORE` alone: fix the lookup, not the test.
- In the gate, the owner rewords more than 1 in 5 of the proposed short forms because they are stronger than their claims: the brief is not good enough; do not build the automatic path of C52 on it.
- In the real runs no loaded rule that bears on the task is followed, or a loaded rule that contradicts the owner's instruction file is followed: stop before release.
- After release, the hook's `ms` at the 99th percentile in `hooks/log.jsonl` is over 1500 (the slowest run seen before was 742): build the block outside the hook.
- After two weeks, the owner turned off or forgot more than two loaded rules, or the same lesson was captured again in a session where it was loaded: revisit the order, the limit of six, or the wording.
