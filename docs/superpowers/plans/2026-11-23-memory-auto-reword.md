# Automatic rewording of a lesson that got worse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With the option `auto_reword` on, the background pass writes one new short form for a loaded lesson whose present version got worse, checked as the fill's short forms are; a lesson whose reworded version got worse too, or that could not be reworded, stays listed for the owner.

**Architecture:** A third step of the automatic run of `bin/mem-corroborate`, after the fill and built like it: candidates chosen by code, one writing session, the code check, one checking session, applied through `mem memory edit`. Two frontmatter dates on the lesson, `reworded` and `reword_failed`, tell the step and `mem curate` what already happened; the listing rule of `records.got_worse` does not change.

**Tech Stack:** Python 3 standard library and PyYAML, pytest. Engine in `plugins/memory/engine/`, commands in `plugins/memory/bin/`.

**Spec:** [the design](../specs/2026-11-23-memory-reword-and-grouping-design.md), Part 1, rows C74 to C80. Read it before any task.

## Global Constraints

- Branch `feat/memory-reword-and-grouping`; one local commit per task; no push, no pull request, no merge.
- With `auto_reword` off or unset, every command and the automatic run behave exactly as in 0.7.0: same output, same files written, same log line (no `reword` key).
- `records.got_worse`, `tallies`, `versions`, `log`, `sources` and the fill step are not changed. `FILL_BRIEF` and `CHECK_BRIEF` are not edited.
- The step never writes a short form that fails `shortcheck.problems` or the checking session, never one equal to a text in `versions`, and never touches a lesson of weight `strong`.
- A background command never raises and never prints; a failure is a counted result, as in the fill.
- No real model is called by a test: tests use the fake `claude` script of `test_mem_corroborate.py`.
- The repository is public: no home path, private repository name, client name or note title in code, tests or docs.
- Fast check: the test files a task names. The whole suite, once at the end of each task: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (about five minutes; foreground, timeout 600 s). `test_merge_logs_both_files_and_restore_undoes_each` fails during the hour after local midnight; that is known.
- An existing test that asserts an exact output this plan changes is updated in the task that changes it and named in its report.

## Stop and report

| Observation | Action |
|---|---|
| A test of the fill, of corroboration or of capture changes its result | Stop: those steps must not move |
| The step would need to edit `FILL_BRIEF` or `CHECK_BRIEF`, or to weaken a check, to pass a test | Stop |
| Anything under the owner's real store or data folder changes during Task 5 | Stop |
| In Task 5, the checking session accepts fewer than half of the proposals | Stop: record the figures and do not tune the brief more than once |

## Review Focus

| Input or condition | Expected | Pinned in |
|---|---|---|
| A proposal that equals an earlier version except for case, spacing or a final period | Refused as the same text | Task 2 |
| The owner edits the short form of a lesson the step reworded | `reworded` is removed, and the step may try again when that wording gets worse | Task 1 |
| The model's answer is not JSON, lacks a lesson, or names an unknown id | Counted as a failed session, no attempt spent, nothing written | Task 3 |
| The step runs while another pass holds the lock | It does nothing and says so in its result | Task 3 |
| A lesson that is index-only, `load: no`, pending or quarantined got worse | Not a candidate | Task 2 |

## File Structure

| File | Change |
|---|---|
| `plugins/memory/engine/records.py` | `reworded`, `reword_failed`, `reword_state` |
| `plugins/memory/engine/mem.py` | `mem memory edit --reworded` and `--reword-failed`; the row of the `mem curate` category |
| `plugins/memory/engine/corroborate.py` | `reword_candidates`, `reword_blocks`, `same_text` |
| `plugins/memory/bin/mem-corroborate` | `REWORD_BRIEF`, `reword_auto`, the subcommand `reword`, the third step of `cmd_auto` |
| `plugins/memory/.claude-plugin/plugin.json`, `plugins/memory/hooks/` | The option `auto_reword` |
| `plugins/memory/engine/tests/test_reword.py` | New: every test of this plan that is not an update of an existing one |

---

### Task 1: The lesson says what the step did (C77, C78)

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `update`, one new function)
- Modify: `plugins/memory/engine/mem.py` (`cmd_memory` and its parser; the row of the category in `cmd_curate`)
- Test: `plugins/memory/engine/tests/test_reword.py` (create)

**Interfaces:**
- Produces:
  - `Memory.reworded: datetime.date | None` and `Memory.reword_failed: datetime.date | None`, frontmatter keys of the same names; a wrong value reads as absent.
  - `records.update(memory, today, **changes)`: when `changes` holds a `short` that differs from `memory.short` and does not hold `reworded`, the key `reworded` is removed from the file. `reword_failed` is never removed by `update`.
  - `records.reword_state(memory) -> str`: `"reworded"` when `reworded` equals the date of the last entry of `version_list(memory)`; else `"failed"` when `reword_failed` equals that date; else `"none"`.
  - `mem memory edit <h> --short TEXT --reworded`: as `--short` without `--user-read` (the code check runs, `short_by: model`), and writes `reworded: <today>`. `--reworded` without `--short`, or with `--user-read`, is a usage error (exit 2).
  - `mem memory edit <h> --reword-failed`: writes `reword_failed` with the date of the lesson's last version and changes nothing else; a usage error when the lesson has no version or another option is given with it.
  - `mem curate`, category "balance got worse after loading": after the words `loaded` / `left out by the cap` / `rules off` of each row, one of `no automatic rewording yet`, `the automatic rewording of <date> got worse too`, `an automatic rewording could not be written`, from `reword_state`, separated by `; `.

- [ ] **Step 1: Write the failing tests**

Reuse the helpers and fixtures of `plugins/memory/engine/tests/test_case_log.py` (`transcript`, `reload`, and how its tests build a lesson that got worse and run `mem.main([...])`); import them, do not copy them.

| Test | Asserts |
|---|---|
| `test_reworded_marks_the_present_version` | `mem memory edit --short "..." --reworded`: `reworded` is today, `short_by` is `model`, one more version, `reword_state == "reworded"` |
| `test_a_short_form_written_by_hand_removes_the_mark` | then `mem memory edit --short "..." --user-read` the next day (write the dates into the file): no `reworded` key, `reword_state == "none"` |
| `test_reworded_needs_a_short_form_and_no_user_read` | exit 2 for both misuses, file bytes unchanged |
| `test_reword_failed_names_the_version_it_gave_up_on` | `--reword-failed`: the date of the last version; `reword_state == "failed"`; a later new version makes it `"none"` while the key stays in the file |
| `test_wrong_values_read_as_absent` | `reworded: soon`, `reword_failed: 7`: the memory loads, both None |
| `test_curate_row_says_what_was_tried` | the three wordings of the row, for the three states, on a lesson that got worse |
| `test_restore_undoes_reworded` | `mem restore` after `--reworded`: the earlier short form, no `reworded` |

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_reword.py -q`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests of this file and of `test_case_log.py`, then the whole suite**

A test of `test_case_log.py` that asserts a whole row of the category now sees the added words: update it and name it.

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine
git commit -m "feat(memory): a lesson records an automatic rewording and one that could not be written"
```

---

### Task 2: Which lessons the step takes, and what it shows the writer (C74, C75, C76)

**Files:**
- Modify: `plugins/memory/engine/corroborate.py`
- Test: `plugins/memory/engine/tests/test_reword.py`

**Interfaces:**
- Consumes: `records.got_worse`, `records.tallies`, `records.version_list`, `records.cases`, `records.reword_state` (Task 1); `rules.choose`, `Choice.loaded`, `Choice.left`, `rules.OVER`; the existing `fill_records(projects, gfolder)` and `fill_key` of this module (read `fill_candidates` first: the new function takes its arguments in the same form and returns the same shape).
- Produces:
  - `REWORD_CAP = 5`, `REWORD_ATTEMPTS = 2`.
  - `reword_candidates(projects, gfolder, today, attempts: Mapping[str, Mapping]) -> list[tuple[str, Memory]]`: the lessons that `rules.choose` (called once with the project lessons of the starting project and the global ones, as `mem rules` does) loads or leaves out with `OVER`; for which `records.got_worse` is true; whose weight is not `strong`; whose `reword_state` is `"none"`; and whose entry in `attempts` (keyed by `reword_key`) counts fewer than `REWORD_ATTEMPTS` for the present version. Ordered by the `failed` count of the present tally, highest first, then by handle; at most `REWORD_CAP`.
  - `reword_key(project, handle, version_date) -> str`: the fill's key with the version's ISO date appended after a `@`.
  - `reword_blocks(items: Sequence[tuple[str, Memory]]) -> str`: what the writing session reads, one block per lesson, blank line between: `id:`, `claim:`, `context:` when there is one, then one line per version `version N (worked W, failed F): <text>`, the last marked `(present)`, then `failed after it loaded: <signals>` with the distinct signals found in the body's lines `Seen again (<signal>)` in order, or `not recorded` when there is none. Every value on one line. No evidence quote is copied.
  - `same_text(a: str, b: str) -> bool`: equal after lower-casing, collapsing whitespace and stripping final punctuation (`.`, `!`, `;`, `:`) and surrounding spaces.
  - `reword_problem(short: str, memory: Memory) -> str | None`: the fill's own problem for a short form (reuse `fill_problem`'s short part, without a topic), or `"same as an earlier wording"` when `same_text` holds against any text of `version_list(memory)`.

- [ ] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_candidates_are_loading_lessons_that_got_worse` | of six lessons (got worse and loads; got worse and index-only; got worse and `load: no`; got worse and pending; got worse and `strong`; loads and did not get worse) only the first is returned |
| `test_a_reworded_or_given_up_version_is_not_a_candidate` | `reword_state` `"reworded"` and `"failed"` are skipped; after a new version by hand the lesson is a candidate again |
| `test_attempts_for_the_present_version_count` | two attempts recorded under `reword_key` of the present version: skipped; recorded under an earlier version's key: taken |
| `test_cap_and_order` | seven candidates: five returned, most failed first |
| `test_the_block_shows_versions_tallies_and_signals` | exact text of one block for a lesson with two versions and a body holding `Seen again (rework): "x"` and `Seen again (owner_correction).`: the line `failed after it loaded: rework, owner_correction`, and the quote `x` nowhere in the block |
| `test_same_text` | `"Check the data first."` equals `"check  the data first"`, differs from `"Check the real data first."` |
| `test_reword_problem` | an over-long short, an empty one, and one equal to version 1 each give a problem; a new valid one gives None |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run `test_reword.py`, `test_corroborate.py`, `test_fill_auto.py`, then the whole suite**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine
git commit -m "feat(memory): the candidates and the reading of an automatic rewording"
```

---

### Task 3: The step itself (C75, C76, C77, C78)

**Files:**
- Modify: `plugins/memory/bin/mem-corroborate`
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py` (extend its fake `claude` script if it needs a new mode), `plugins/memory/engine/tests/test_reword.py`

**Interfaces:**
- Consumes: Task 1's `mem memory edit --short ... --reworded` and `--reword-failed`; Task 2's `reword_candidates`, `reword_key`, `reword_blocks`, `reword_problem`; the fill's own machinery in this file: `_ask`, `PROPOSE_MODEL`, `CHECK_MODEL`, `CHECK_BRIEF`, the pairs text the checker reads, `shortcheck.problems`, the run lock, the budget and cost accounting, the applier that runs `mem`.
- Produces:
  - `REWORD_BRIEF`: the text below, verbatim.
  - `reword_auto(claude, budget, *, every: bool = False, apply: bool = True, sheet: Path | None = None) -> dict`: one run of the step, never raising. Result keys: `asked`, `written`, `refused_code`, `refused_check`, `same_text`, `gave_up`, `cost`, `stopped` (None or a short reason, as the fill has). Order: take the lock; candidates; one writing session over all of them; per proposal `reword_problem` (a same text counts in `same_text`, another problem in `refused_code`) and `shortcheck.problems` against the claim (`refused_code`); one checking session over the survivors with `CHECK_BRIEF` (`refused_check`); apply each accepted one with `mem memory edit m:<handle> [--global] --short=<text> --reworded`. Each refusal spends one attempt for that lesson and version in `reword-attempts.json` beside the fill's file; a lesson that reaches `REWORD_ATTEMPTS` gets `mem memory edit ... --reword-failed` and counts in `gave_up`. A session that fails or returns an unusable answer spends no attempt.
  - `every=True` takes every loading lesson with a short form as a candidate, whatever its tally (for the gate); `apply=False` writes nothing to a record and spends no attempt; `sheet` receives one Markdown table row per proposal: id, claim, present short form, proposed short form, the code check's answer, the checker's verdict and reason.
  - The subcommand `mem-corroborate reword [--every] [--dry-run] [--sheet PATH]`, built as `fill` is, printing its result as JSON.

```text
REWORD_BRIEF = """You rewrite the short form of lessons that coding sessions wrote down. Each short form below was loaded into later sessions and the thing the lesson warns about still happened, so the present wording did not reach its reader.
Read {lessons}: one block per lesson, with an id, a claim, sometimes a context, every wording tried so far with how often the lesson then worked and failed, and what kind of failure followed where it is recorded.
For each lesson write: short: one sentence of at most 120 characters (aim for 100), drawn from the claim and not from the earlier wordings, that differs from all of them. Start with the situation in which it applies, in words a reader in that situation would recognize, then name what may be worth doing as a thing or an -ing form ("quoting the source line may catch errors"), not as a command to the reader, unless the claim itself is a command. It is a suggestion and never stronger than the claim: keep the claim's hedge (may, once, sometimes, untested, provisional); if it is too long, drop alternatives and detail first, never the hedge. It must stand on its own, say "the user" and never "the owner", name no project, person or company, and add nothing the claim does not say. An id is copied whole.
Write {out} as JSON: {{"items": [{{"id": "g:example", "short": "..."}}]}}
One item per lesson. Write nothing else and use no other tool.
"""
```

- [ ] **Step 1: Write the failing tests**

Drive the step as the fill's tests in `test_mem_corroborate.py` drive `fill` (the fake `claude`, its environment variables, a temporary store).

| Test | Asserts |
|---|---|
| `test_reword_applies_an_accepted_wording` | one lesson that got worse; the fake writer proposes a valid new text and the fake checker accepts: the record has the new short form, one more version, `reworded` today, `short_by: model`; result `asked 1, written 1`; `got_worse` is now false |
| `test_a_same_text_proposal_is_refused_and_spends_an_attempt` | `same_text 1`, nothing written, one attempt in the state file |
| `test_two_refusals_give_up_and_mark_the_lesson` | two runs with a proposal the checker refuses: after the second, `reword_failed` on the record, `gave_up 1`; a third run asks nothing |
| `test_an_unusable_answer_spends_no_attempt` | the fake writer returns text that is not JSON: nothing written, no attempt, `stopped` says why |
| `test_the_step_does_not_touch_a_reworded_version_that_got_worse` | after an applied rewording, add two failed cases dated after it: the next run asks nothing and the lesson is listed by `mem curate` with "got worse too" |
| `test_dry_run_writes_the_sheet_and_nothing_else` | `--every --dry-run --sheet`: every memory file byte-identical, no attempt file change, the sheet has one row per loading lesson with a short form |
| `test_reword_respects_the_lock` | with the run lock held, the result's `stopped` names the lock and nothing is asked |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

Read `fill_auto` and its helpers first and reuse them; where a helper is specific to the fill only by a name or a key, give it a parameter instead of copying it.

- [ ] **Step 4: Run `test_mem_corroborate.py`, `test_reword.py`, `test_fill_auto.py`, then the whole suite**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory
git commit -m "feat(memory): the pass can reword a lesson that got worse, checked as a first short form is"
```

---

### Task 4: The option and the automatic run (C79)

**Files:**
- Modify: `plugins/memory/.claude-plugin/plugin.json` (the `userConfig` key `auto_reword`, a boolean, default false, described in one sentence in the style of `auto_capture`; the version is not changed)
- Modify: `plugins/memory/bin/mem-corroborate` (`cmd_auto`)
- Modify: `plugins/memory/hooks/` only if the option has to be passed on as `auto_capture` is (read how `CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE` reaches `cmd_auto`)
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py`, `plugins/memory/engine/tests/test_plugin_shell.py` if it lists the options

**Interfaces:**
- Consumes: `reword_auto` of Task 3.
- Produces: in `cmd_auto`, after the fill and inside the same condition on the loaded rules, when `CLAUDE_PLUGIN_OPTION_AUTO_REWORD` is `"true"`: `reword_auto(args.claude, budget)` and one log line `{"t", "reword": result, "ms"}`, in a `try` of its own as the fill has. With any other value nothing runs and no line is written.

- [ ] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_auto_runs_reword_only_with_the_option` | with `auto_capture` on and the option absent or `false`: no `reword` line in the log and no record changed by the step; with `true`: one `reword` line after the `fill` line |
| `test_auto_skips_reword_when_loaded_rules_are_off` | `CLAUDE_PLUGIN_OPTION_LOADED_RULES=false`: no `reword` line |
| `test_a_failure_in_reword_does_not_fail_auto` | with `reword_auto` patched to raise: exit code 0, the `fill` line is there |
| `test_plugin_json_has_the_option_off` | the key exists with default false; `claude plugin validate` is not run by the test |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the test files, then the whole suite, then `python3 scripts/validate.py` and `claude plugin validate .`**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory
git commit -m "feat(memory): the option auto_reword, off by default, adds the rewording step to the automatic run"
```

---

### Task 5: The gate's automatic half, and the documents (C80)

**Files:**
- Modify: `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md` (under `## [Unreleased]`), `plugins/memory/skills/memory-curation/SKILL.md` (the row of the category: the three wordings of the row and what each asks of the reader), `docs/superpowers/specs/2026-11-21-memory-capture-design.md` (one row reserving C74 to C85 with a link to the design, after row C73; the Phases table), `docs/superpowers/plans/2026-11-17-memory-plugin.md` ("Current state and where to resume")
- Modify: this file (`## Results`)

- [ ] **Step 1: Copy the store and isolate the environment**

As Task 8 of [the case log plan](2026-11-22-memory-case-log.md) did: copies under a temporary directory, every `MEM_*` and `XDG_*` variable and `HOME` pointing into it, `MEM_SETTLE_AUTO` unset, checksums of the real folders before and after.

- [ ] **Step 2: Run the step on every loading lesson, without applying**

Run: `plugins/memory/bin/mem-corroborate reword --every --dry-run --sheet <private path>` with a real `claude` and a budget of 0.50 USD. The sheet goes to the owner's private state folder (`<state>/reword-gate-2026-11-23.md`), never into the repository.

- [ ] **Step 3: Record the figures**

In `## Results`: the number of lessons asked, proposals, code refusals, same-text refusals, checker acceptances and its share of the proposals that passed the code checks, the cost, and whether the automatic half of C80 passed (at least 80% accepted, none equal to an earlier text). One revision of `REWORD_BRIEF` is allowed after a miss, scored on a second run; record both.

- [ ] **Step 4: Write the documents**

One home per fact; the feature is described as implemented and off by default, with the gate's owner half open. No claim, short form or handle of the owner's store in any of them.

- [ ] **Step 5: Run `python3 scripts/validate.py`, `claude plugin validate .`, `python3 scripts/port.py --check`, and the whole suite**

- [ ] **Step 6: Commit**

```bash
git add plugins/memory docs
git commit -m "docs(memory): the automatic rewording, its gate's first half and where it stands"
```

---

## Results

Filled by Task 5.
