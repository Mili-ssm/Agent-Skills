# Automatic rewording of a lesson that got worse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With the option `auto_reword` on, the background pass writes one new short form, once per lesson, for a loaded lesson whose present version got worse, checked as the fill's short forms are; every later worsening of that lesson, and a rewording that could not be written, stay with the owner.

**Architecture:** A third step of the automatic run of `bin/mem-corroborate`, after the fill and built beside it: candidates chosen by code, one writing session, the code check, one checking session, applied through `mem memory edit`. Two frontmatter dates on the lesson, `reworded` and `reword_failed`, and a state file beside the fill's, tell the step what already happened; the listing rule of `records.got_worse` does not change.

**Tech Stack:** Python 3 standard library and PyYAML, pytest. Engine in `plugins/memory/engine/`, commands in `plugins/memory/bin/`.

**Spec:** [the design](../specs/2026-11-23-memory-reword-and-grouping-design.md), Part 1, rows C74 to C80. Read it before any task.

## Global Constraints

- Branch `feat/memory-reword-and-grouping`; one local commit per task; stage only the files the task names, by path (`git add <path> ...`, never `-A` or a folder); no push, no pull request, no merge.
- With `auto_reword` off or unset and no lesson carrying `reworded` or `reword_failed`, every command and the automatic run behave exactly as in 0.7.0: same output, same files written, same log line (no `reword` key).
- `records.got_worse`, `tallies`, `versions`, `log`, `sources` are not changed. The fill step is not changed: `FILL_BRIEF`, `CHECK_BRIEF`, `fill_candidates`, `validate_fill`, `fill_problem`, `apply_fill`, `fill_auto` keep their text and behavior; what the new step needs from them it calls as they are or copies under a new name.
- The step never writes a short form that fails `shortcheck.problems` or the checking session, never one equal to a text in `versions`, and never touches a lesson of weight `strong`, a lesson that already carries `reworded`, or one the owner kept as worded (`reviewed`).
- A background command never raises and never prints; a failure is a counted result, as in the fill.
- No real model is called by a test: tests use the fake `claude` script of `test_mem_corroborate.py`. A test must not pass only because the fake answer carries a `topic`: the step's answers have none.
- The repository is public: no home path, private repository name, client name or note title in code, tests or docs.
- Fast check: the test files a task names. The whole suite, once at the end of each task: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (about five minutes; foreground, timeout 600 s). `test_merge_logs_both_files_and_restore_undoes_each` fails during the hour after local midnight; that is known.
- An existing test that asserts an exact output this plan changes is updated in the task that changes it and named in its report.

## Stop and report (kill criteria, from the pre-mortem of 2026-11-23)

| Observation | Action |
|---|---|
| A test of the fill, of corroboration or of capture changes its result, or a fill function had to be edited | Stop |
| `git diff --cached` shows a file the task does not name | Stop |
| After an undo or a `mem restore` of a rewording, the next run asks for that lesson again | Stop |
| Task 6: the session ends with an authentication error, nothing is asked, or anything under the owner's real memory folders or the plugin's real logs changes | Stop; do not point `HOME` elsewhere to get around it |
| Task 6: the checking session accepts fewer than half of the proposals | Stop: record the figures; one revision of the brief at most |

## Review Focus

| Input or condition | Expected | Pinned in |
|---|---|---|
| The owner undoes a rewording (`mem restore`, or the pass's undo) | The lesson is not reworded again: it is listed for the owner | Task 4 |
| The owner writes a short form by hand after a rewording, and it gets worse | No second automatic rewording; the row says a rewording was made and this wording is the owner's | Task 1, Task 2 |
| A proposal that equals an earlier version except for case, spacing or a final period | Refused as the same text | Task 2 |
| The model's answer is not JSON, or lacks a lesson | A failed session, or no proposal for that lesson; after three failed runs in a row on the same candidates the step waits until they change | Task 3, Task 4 |
| A lesson that is index-only, `load: no`, pending or quarantined got worse | Not a candidate | Task 2 |

## File Structure

| File | Change |
|---|---|
| `plugins/memory/engine/records.py` | `reworded`, `reword_failed`, `reword_note` |
| `plugins/memory/engine/mem.py` | `mem memory edit --reworded` and `--reword-failed`; the row of the `mem curate` category |
| `plugins/memory/engine/corroborate.py` | `reword_candidates`, `reword_blocks`, `same_text`, `reword_problem`, `validate_reword` |
| `plugins/memory/bin/mem-corroborate` | `REWORD_BRIEF`, `reword_auto`, the subcommand `reword`, the third step of `cmd_auto` |
| `plugins/memory/.claude-plugin/plugin.json` | The option `auto_reword` |
| `plugins/memory/engine/tests/test_reword.py` | New: the tests of Tasks 1 to 3 |

---

### Task 1: The lesson says what the step did (C77, C78)

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, one new function)
- Modify: `plugins/memory/engine/mem.py` (`cmd_memory` and its parser; the row of the category in `cmd_curate`)
- Test: `plugins/memory/engine/tests/test_reword.py` (create)

**Interfaces:**
- Produces:
  - `Memory.reworded: datetime.date | None` and `Memory.reword_failed: datetime.date | None`, frontmatter keys of the same names; a wrong value reads as absent. Neither is ever removed by `records.update` unless the caller passes the key as None.
  - `records.reword_note(memory) -> str`: with `last` the date of the last entry of `version_list(memory)`: `"the automatic rewording of <reworded> got worse too"` when `reworded == last`; `"an automatic rewording was made on <reworded>; this wording is the owner's"` when `reworded` is set and differs from `last`; `"an automatic rewording could not be written"` when `reworded` is None and `reword_failed == last`; else `""`.
  - `mem memory edit <h> --short TEXT --reworded`: as `--short` without `--user-read` (the code check runs, `short_by: model`), and writes `reworded: <today>`. `--reworded` without `--short`, or with `--user-read`, is a usage error (exit 2).
  - `mem memory edit <h> --reword-failed`: writes `reword_failed` with the date of the lesson's last version and changes nothing else; a usage error (exit 2) when the lesson has no version or any other change option is given with it. It is journaled like any edit, and does not start a settle run (read how `cmd_memory` decides to start one and keep this option out of it).
  - `mem curate`, category "balance got worse after loading": when `reword_note(m)` is not empty, the row's state word (`loaded` / `left out by the cap` / `rules off`) is followed by `; <reword_note>`. A lesson with neither key prints its row exactly as in 0.7.0.

- [x] **Step 1: Write the failing tests**

Reuse the helpers of `plugins/memory/engine/tests/test_case_log.py` (`transcript`, `reload`, and how its tests build a lesson that got worse and run `mem.main([...])`): import them, do not copy them.

| Test | Asserts |
|---|---|
| `test_reworded_marks_the_lesson` | `mem memory edit --short "..." --reworded`: `reworded` is today, `short_by` is `model`, one more version |
| `test_a_short_form_written_by_hand_keeps_the_mark` | then `mem memory edit --short "..." --user-read` dated the next day (write the dates into the file): `reworded` still there; `reword_note` is the "was made on ... the owner's" text |
| `test_reworded_needs_a_short_form_and_no_user_read` | exit 2 for both misuses, file bytes unchanged |
| `test_reword_failed_names_the_version_it_gave_up_on` | `--reword-failed`: the date of the last version; `reword_note` is "could not be written"; after a new version by hand the note is `""` while the key stays |
| `test_wrong_values_read_as_absent` | `reworded: soon`, `reword_failed: 7`: the memory loads, both None |
| `test_curate_row_says_what_was_tried` | the three notes on the row of a lesson that got worse; a lesson with neither key has the row of 0.7.0 (compare with the row built before the keys are written) |
| `test_restore_undoes_reworded` | `mem restore` after `--reworded`: the earlier short form, no `reworded` |

- [x] **Step 2: Run them and see them fail**

Run: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_reword.py -q`

- [x] **Step 3: Implement**

- [x] **Step 4: Run `test_reword.py` and `test_case_log.py`, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine/records.py plugins/memory/engine/mem.py plugins/memory/engine/tests/test_reword.py
git commit -m "feat(memory): a lesson records an automatic rewording and one that could not be written"
```

---

### Task 2: Which lessons the step takes, and what it shows the writer (C74, C75, C76)

**Files:**
- Modify: `plugins/memory/engine/corroborate.py`
- Test: `plugins/memory/engine/tests/test_reword.py`

**Interfaces:**
- Consumes: `records.got_worse`, `records.tallies`, `records.version_list`, `Memory.reworded`, `Memory.reword_failed`, `Memory.reviewed`; `rules.choose`, `Choice.loaded`, `Choice.left`, `rules.OVER`; `capture.outcome`; this module's `fill_records(projects, gfolder)` and `fill_key` (read `fill_candidates` first: the new function takes its arguments in the same form and returns the same shape).
- Produces:
  - `REWORD_CAP = 5`, `REWORD_ATTEMPTS = 2`.
  - `reword_key(project, handle) -> str`: the fill's key, unchanged (one per lesson).
  - `reword_candidates(projects, gfolder, today, state: Mapping) -> list[tuple[str, Memory]]`, where `state` is `{"lessons": {key: {"version": "<ISO date>", "count": int, "spent": bool}}, ...}`. A lesson is taken when: it is among the lessons `rules.choose` loads or leaves out with `OVER`, for some project of `projects` together with the global lessons; `records.got_worse` is true; its weight is not `strong`; `reworded` is None; `reviewed` is None; `reword_failed` is not the date of its last version; its state entry is not `spent`; and its state entry does not count `REWORD_ATTEMPTS` or more for the date of its last version. Ordered by the `failed` count of the present tally, highest first, then by id; at most `REWORD_CAP`. With `every=True` (keyword argument, default False) the tests on `got_worse` and on the cap are left out and every other one stays.
  - `reword_blocks(items: Sequence[tuple[str, Memory]]) -> str`: what the writing session reads, one block per lesson, blank line between: `id:`, `claim:`, `context:` when there is one, then one line per version `version N (worked W, failed F): <text>`, the last marked `(present)`, then `failed after it loaded: <signals>` with the distinct signals found in the body's lines `Seen again (<signal>)`, in order, kept only when `capture.outcome(signal) == "failed"`, or `not recorded` when none is left. Every value on one line. No evidence quote is copied.
  - `same_text(a: str, b: str) -> bool`: equal after lower-casing, collapsing whitespace and stripping surrounding spaces and final punctuation (`.`, `!`, `;`, `:`).
  - `reword_problem(short: str, memory: Memory) -> str | None`: why a proposed short form cannot be applied: the same tests on the text that `fill_problem` makes on a short form (empty, spaces at its ends, more than one line, over `records.SHORT_LIMIT`), copied here without the topic, then `"same as an earlier wording"` when `same_text` holds against any text of `version_list(memory)`; else None.
  - `validate_reword(payload, items) -> dict[str, dict]`: the model's whole answer `{"items": [{"id", "short"}]}` turned into `{id: {"short": str, "problem": str | None}}` for the ids of `items` only; an id that is missing from the answer is absent from the result; a `short` that is not a string reads as `""`; the first item of an id wins. It raises `ValueError` when the payload is not an object with a list `items`.

- [x] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_candidates_are_loading_lessons_that_got_worse` | of seven lessons (got worse and loads; got worse and index-only; got worse and `load: no`; got worse and pending; got worse and `strong`; got worse with `reviewed` set; loads and did not get worse) only the first is returned |
| `test_a_reworded_lesson_is_never_taken_again` | `reworded` set, also after a later version by hand that got worse |
| `test_a_given_up_version_and_a_spent_lesson_are_skipped` | `reword_failed` equal to the last version's date; a state entry with `spent: true`; a state entry counting two for the present version: each skipped. A count recorded for an earlier version's date: taken |
| `test_cap_and_order` | seven candidates: five returned, most failed first |
| `test_every_takes_lessons_that_did_not_get_worse` | `every=True`: the loading lesson that did not get worse is returned, the `strong` and the `reworded` ones are not |
| `test_the_block_shows_versions_tallies_and_failure_signals` | exact text of one block for a lesson with two versions and a body holding `Seen again (rework): "x"`, `Seen again (effective_practice).` and `Seen again (owner_correction).`: the line `failed after it loaded: rework, owner_correction`, and the quote `x` nowhere in the block |
| `test_same_text` | `"Check the data first."` equals `"check  the data first"`, differs from `"Check the real data first."` |
| `test_reword_problem` | an over-long short, an empty one, and one equal to version 1 each give a problem; a new valid one gives None |
| `test_validate_reword` | an answer without any `topic` is read; a missing id is absent; a non-list `items` raises |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

- [x] **Step 4: Run `test_reword.py`, `test_corroborate.py`, `test_fill_auto.py`, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine/corroborate.py plugins/memory/engine/tests/test_reword.py
git commit -m "feat(memory): the candidates and the reading of an automatic rewording"
```

---

### Task 3: What the step decides from the two answers (C76, C78)

**Files:**
- Modify: `plugins/memory/engine/corroborate.py`
- Test: `plugins/memory/engine/tests/test_reword.py`

**Interfaces:**
- Consumes: Task 2's `validate_reword`, `reword_problem`, `reword_key`; `shortcheck.problems` (read how the fill calls it on a claim and a short form); the fill's parser of the checker's answer in this module (the function that turns `{"verdicts": [...]}` into accepted ids: call it as it is).
- Produces, all pure (no file, no model):
  - `reword_survivors(proposed: Mapping[str, dict], items) -> tuple[list[tuple[str, Memory, str]], dict[str, str]]`: the proposals that pass `reword_problem` and `shortcheck.problems`, as `(id, memory, short)`, and for the others `{id: "same_text" | "refused_code"}`.
  - `reword_outcome(items, proposed, accepted: Collection[str]) -> dict[str, str]`: one word per candidate id: `"written"` (a survivor the checker accepted), `"same_text"`, `"refused_code"`, `"refused_check"` (a survivor the checker did not accept), or `"no_proposal"` (the id is missing from the writer's answer).
  - `reword_state_after(state, items, outcome, today) -> tuple[dict, list[str]]`: the new state and the ids to give up on. `written` sets `spent: true`. `same_text`, `refused_code` and `refused_check` add one to the count for the lesson's present version date (a count for another date starts again at one). `no_proposal` changes nothing. An id whose count reaches `REWORD_ATTEMPTS` is in the list to give up on. The input state is not mutated.

- [x] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_survivors_and_refusals` | three proposals: a valid new one survives; one equal to an earlier text is `same_text`; one that drops the claim's hedge is `refused_code` |
| `test_outcome_words` | the five words, one candidate each |
| `test_a_written_lesson_is_spent` | `spent: true`, and `reword_candidates` no longer returns it even when the record has no `reworded` (the case of an undo) |
| `test_two_refusals_for_one_version_give_up` | first refusal: count 1, no give-up; second: count 2, in the list |
| `test_a_refusal_for_a_new_version_starts_again` | a count of 1 for an earlier date, then a refusal for the present date: count 1 |
| `test_no_proposal_spends_nothing` | the state is equal to the input |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

- [x] **Step 4: Run `test_reword.py`, `test_corroborate.py`, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory/engine/corroborate.py plugins/memory/engine/tests/test_reword.py
git commit -m "feat(memory): what an automatic rewording decides from the writer's and the checker's answers"
```

---

### Task 4: The step in the pass (C75, C77, C78)

**Files:**
- Modify: `plugins/memory/bin/mem-corroborate`
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py` (its fake `claude` script chooses its answer by the name of the output file it is asked to write: give the step's two sessions output names of their own and add their modes to the fake)

**Interfaces:**
- Consumes: Task 1's `mem memory edit --short ... --reworded` and `--reword-failed`; Tasks 2 and 3's functions; in this file, called as they are: `_ask`, `PROPOSE_MODEL`, `CHECK_MODEL`, `CHECK_BRIEF` and the function that writes the pairs the checker reads, the run lock, the budget and cost accounting, the helper that runs `mem`, the run folder and journal that make `mem-corroborate undo` work. Read `fill_auto` from its first line to its last before writing: the new function follows its order and its failure handling, in code of its own.
- Produces:
  - `REWORD_BRIEF`: the text below, verbatim.
  - `reword_auto(claude, budget, *, every: bool = False, apply: bool = True, sheet: Path | None = None, limit: int = 30) -> dict`: one run of the step, never raising. Result keys: `asked`, `written`, `refused_code`, `refused_check`, `same_text`, `no_proposal`, `gave_up`, `cost`, `stopped` (None, or a short reason as the fill gives). Order: take the lock; load the state (`reword-attempts.json` beside the fill's file: `{"lessons": {...}, "failures": {"count": int, "fingerprint": str}}`); candidates (`every` passes through; `limit` caps them when `every`); stop with `stopped` when the same candidates failed three runs in a row (the fingerprint of the fill, over the candidates' keys and present version dates); one writing session; `validate_reword`; `reword_survivors`; one checking session over the survivors, none when there is no survivor; `reword_outcome`; apply each `written` one with `mem memory edit m:<handle> [--global] --short=<text> --reworded`, a refused edit turning its outcome into `refused_code`; `reword_state_after` and save; for each id to give up on, `mem memory edit ... --reword-failed`, counted in `gave_up`. A session that fails or whose answer cannot be parsed changes no lesson state, adds one to `failures`, and sets `stopped`.
  - The run is journaled so that `mem-corroborate undo` undoes it as it undoes a fill run: write the same kind of run marker the fill writes, so that the undo does not take the run for a corroboration run.
  - `apply=False` writes nothing to a record, saves no state and spends no attempt; both sessions still run, since the sheet needs their answers. `sheet`, when given, receives a Markdown table, one row per candidate: id, claim, present short form, proposed short form, outcome, and the checker's reason when it gave one.
  - The subcommand `mem-corroborate reword [--every] [--limit N] [--dry-run] [--sheet PATH]`, built as `fill` is (same `--claude` and budget arguments), printing its result as JSON.

```text
REWORD_BRIEF = """You rewrite the short form of lessons that coding sessions wrote down. Each short form below was loaded into later sessions and the thing the lesson warns about still happened, so the present wording did not reach its reader.
Read {lessons}: one block per lesson, with an id, a claim, sometimes a context, every wording tried so far with how often the lesson then worked and failed, and what kind of failure followed where it is recorded.
For each lesson write: short: one sentence of at most 120 characters (aim for 100), drawn from the claim and not from the earlier wordings, that differs from all of them. Start with the situation in which it applies, in words a reader in that situation would recognize, then name what may be worth doing as a thing or an -ing form ("quoting the source line may catch errors"), not as a command to the reader, unless the claim itself is a command. It is a suggestion and never stronger than the claim: keep the claim's hedge (may, once, sometimes, untested, provisional); if it is too long, drop alternatives and detail first, never the hedge. It must stand on its own, say "the user" and never "the owner", name no project, person or company, and add nothing the claim does not say. An id is copied whole.
Write {out} as JSON: {{"items": [{{"id": "g:example", "short": "..."}}]}}
One item per lesson. Write nothing else and use no other tool.
"""
```

- [x] **Step 1: Write the failing tests**

Drive the step as the fill's tests in `test_mem_corroborate.py` drive `fill` (the fake `claude`, its environment variables, a temporary store).

| Test | Asserts |
|---|---|
| `test_reword_applies_an_accepted_wording` | one lesson that got worse; the fake writer proposes a valid new text with no `topic` and the fake checker accepts: the record has the new short form, one more version, `reworded` today, `short_by: model`; result `asked 1, written 1`; `records.got_worse` is now false |
| `test_two_refusals_give_up_and_mark_the_lesson` | two runs with a proposal the checker refuses: after the second, `reword_failed` on the record, `gave_up 1`; a third run asks nothing |
| `test_an_unusable_answer_changes_no_lesson_and_three_in_a_row_wait` | the fake writer returns text that is not JSON: nothing written, no lesson count; on the fourth run with the same candidates no session is started and `stopped` says why |
| `test_undo_does_not_bring_a_second_rewording` | apply one; `mem-corroborate undo` (or `mem restore` on the record): the earlier short form is back without `reworded`; the next run asks nothing, and `mem curate` lists the lesson |
| `test_a_reworded_version_that_got_worse_stays_with_the_owner` | after an applied rewording, two failed cases dated after it are written into the record: the next run asks nothing; `mem curate` shows the row with "got worse too" |
| `test_dry_run_writes_the_sheet_and_nothing_else` | `--every --dry-run --sheet`: every memory file and the state file byte-identical, the sheet has one row per candidate |
| `test_reword_respects_the_lock` | with the run lock held, `stopped` names the lock and nothing is asked |
| `test_the_fill_is_unchanged_by_the_new_modes_of_the_fake` | the existing fill tests of the file pass untouched (name them in the report; do not edit them) |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

- [x] **Step 4: Run `test_mem_corroborate.py`, `test_reword.py`, `test_fill_auto.py`, then the whole suite**

- [x] **Step 5: Commit**

```bash
git add plugins/memory/bin/mem-corroborate plugins/memory/engine/tests/test_mem_corroborate.py
git commit -m "feat(memory): the pass can reword a lesson that got worse, checked as a first short form is"
```

---

### Task 5: The option and the automatic run (C79)

**Files:**
- Modify: `plugins/memory/.claude-plugin/plugin.json` (the `userConfig` key `auto_reword`, declared as `auto_capture` is, default false, one sentence of description; the version is not changed)
- Modify: `plugins/memory/bin/mem-corroborate` (`cmd_auto`)
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py`, and `plugins/memory/engine/tests/test_plugin_shell.py` if it lists the options

**Interfaces:**
- Consumes: `reword_auto` of Task 4.
- Produces: in `cmd_auto`, after the fill and under the same condition on the loaded rules, when `CLAUDE_PLUGIN_OPTION_AUTO_REWORD` is `"true"`: `reword_auto(args.claude, budget)` and one log line `{"t", "reword": result, "ms"}`, in a `try` of its own as the fill has. With any other value nothing runs and no line is written. If `cmd_auto` receives its options through a hook script rather than straight from the environment, pass this one the same way.

- [x] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_auto_runs_reword_only_with_the_option` | with `auto_capture` on and the option absent or `false`: no `reword` line in the log and no record changed by the step; with `true`: one `reword` line after the `fill` line |
| `test_auto_skips_reword_when_loaded_rules_are_off` | `CLAUDE_PLUGIN_OPTION_LOADED_RULES=false`: no `reword` line |
| `test_a_failure_in_reword_does_not_fail_auto` | with `reword_auto` patched to raise: exit code 0, the `fill` line is there |
| `test_plugin_json_has_the_option_off` | the key exists with default false |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

- [x] **Step 4: Run the test files, then the whole suite, then `python3 scripts/validate.py` and `claude plugin validate .`**

- [x] **Step 5: Commit**

```bash
git add plugins/memory/.claude-plugin/plugin.json plugins/memory/bin/mem-corroborate plugins/memory/engine/tests/test_mem_corroborate.py
git commit -m "feat(memory): the option auto_reword, off by default, adds the rewording step to the automatic run"
```

---

### Task 6: The gate's automatic half, and the documents (C80)

**Files:**
- Modify: `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md` (under `## [Unreleased]`), `plugins/memory/skills/memory-curation/SKILL.md` (the row of the category: the three notes a row may carry and what each asks of the reader; no link that leaves the plugin folder), `docs/superpowers/specs/2026-11-21-memory-capture-design.md` (one row reserving C74 to C85 with a link to the design, after row C73; the Phases table), `docs/superpowers/plans/2026-11-17-memory-plugin.md` ("Current state and where to resume")
- Modify: this file (`## Results`)

- [ ] **Step 1: Copy the global lessons and isolate the store, not the login**

A real `claude` cannot run with `HOME` pointed elsewhere (it loses its login), so `HOME` stays. Copy the owner's store folder to a directory made with `mktemp -d` and point `MEM_STORE`, `MEM_MEMORIES`, `MEM_DATA` and `XDG_STATE_HOME` into it, with `MEM_SETTLE_AUTO` unset; `MEM_DATA` starts empty, so no project is registered and the gate reads the global lessons only. Before anything is run, print the folders the commands resolve and check that each is under the temporary directory. Take a checksum list of the owner's real memory folders and of the plugin's real state folder (its capture and corroboration logs) before and after: they must be equal.

- [ ] **Step 2: Run the step on every loading lesson, without applying**

Run: `plugins/memory/bin/mem-corroborate reword --every --limit 30 --dry-run --sheet <sheet>` with a real `claude` and a budget whose total is at most 1.00 USD (read how the budget argument bounds one session and choose it so that two sessions stay under the total). `<sheet>` is `reword-gate-2026-11-23.md` in the folder that holds the owner's real store folder (beside the store, not inside it): outside every repository, as the command requires, and outside the folders whose checksums are compared. A dry run calls both sessions and costs what a real run costs.

- [ ] **Step 3: Record the figures**

In `## Results`: the lessons asked, proposals, code refusals, same-text refusals, checker acceptances and their share of the proposals that passed the code checks, the cost, and whether the automatic half of C80 passed (at least 80% accepted, none equal to an earlier text). One revision of `REWORD_BRIEF` is allowed after a miss, scored on a second run; record both.

- [ ] **Step 4: Write the documents**

One home per fact; the feature is described as implemented and off by default, with the gate's owner half open. No claim, short form or handle of the owner's store in any of them.

- [ ] **Step 5: Run `python3 scripts/validate.py`, `claude plugin validate .`, `python3 scripts/port.py --check`, and the whole suite**

- [ ] **Step 6: Commit**

```bash
git add plugins/memory/README.md plugins/memory/CHANGELOG.md plugins/memory/skills/memory-curation/SKILL.md docs/superpowers
git commit -m "docs(memory): the automatic rewording, its gate's first half and where it stands"
```

---

## Results

Filled by Task 6.
