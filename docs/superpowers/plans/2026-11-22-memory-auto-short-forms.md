# Memory Automatic Short Forms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lesson that becomes established gets its short form and topic written, checked and applied by the background pass with nobody reading it first; only a `strong` lesson, or one whose short form was refused twice, waits for the owner.

**Architecture:** `mem-corroborate auto` gains a second step after the matching pass: one small-model session writes the short forms (the existing `FILL_BRIEF`), code refuses the ones that are stronger than their claim (new pure module `engine/shortcheck.py`), a second session with a different brief checks the rest against their claims, and the survivors are applied through the journal `fill --items` already uses. A short form nobody read carries `short_by: model`, so the owner can list and read afterwards what loaded unread. `records.standing_changes` puts only a `strong` general lesson into triage.

**Tech Stack:** Python 3 standard library and PyYAML, as the rest of `plugins/memory/engine`; pytest.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md), decision C52 and the rows C59 to C62 this plan adds (C33, C46, C54, C55 behind them).

## What was recalled and researched (2026-11-22)

| Finding | Source | What it changes here |
|---|---|---|
| Memory rewritten at each consolidation collapses (a playbook cut from 18,282 to 122 tokens, accuracy below baseline); small updates merged by code avoid it | Our store, from the ACE paper (arXiv 2510.04618) | A short form is always written from the claim, never from an earlier short form; code applies it |
| A rule enforced by a validator stopped repeated errors; prose alone did not | Our store | The length limit and the hedge check are code (C59), not only words in the brief |
| Self-review without outside feedback did not raise accuracy in one study | Our store | The checker has a different brief and never sees the writer's reasoning; which model checks is decided by the gate (C60) |
| A model judge is trusted only after it agrees with human labels on the same task | Our store | The gate scores the checks against the short forms the owner read (C62) |
| No published system holds a learned rule back until it is corroborated; ExpeL removes an insight when its count reaches zero, ACE and Dynamic Cheatsheet publish no removal rule | Our store; arXiv 2308.10144, 2510.04618, 2504.07952 | Nothing to copy for admission: the corroboration gate stays ours. The counting belongs to the usefulness plan (C49), not here |
| Text read from the web or a transcript is a lasting injection path; one 2026 paper found no validation step between the decision to write and the storage | Our store; arXiv 2606.04329 | The writer and the checker keep `Read` and `Write` only; code refuses a short form with a link (C59) |
| Our own trial: the writer passed 120 characters twice in a row on two lessons | The loaded rules plan, "After the tasks" | A refused short form is asked again once, then left for the owner (C61) |

## Scope

| In this plan | Waits |
|---|---|
| Short forms written, checked and applied by `mem-corroborate auto` | Usefulness of a loaded lesson (C49): needs a date on each sighting |
| Only a `strong` general lesson waits at triage; a `strong` project lesson the owner did not confirm is never filled by the pass | Rules that reach subagents |
| `short_by: model`, `mem rules --unread`, `mem rules --read`, `mem triage hold` | A project lesson seen once (still never loads) |
| The gate on a private copy, with its rule written below before any run | Release: only with the owner's word |

## Global Constraints

- Everything in the loaded rules plan's Global Constraints still holds, except its line "nothing writes a `short` without the owner having read it", which C52 replaces.
- Session start runs no model and its text does not change in this plan.
- The automatic step runs only when `mem-corroborate auto` runs (option `auto_capture` is `true`) and the option `loaded_rules` is not off. With either off, no session starts and nothing is written.
- `cmd_auto` never raises and never prints. A failure of the fill step never undoes or fails the matching pass that ran before it, and never touches the pass's `seen.json`, status failure line or retry count.
- A short form is written only from the claim and context of its record. No brief receives an existing short form.
- The pass applies a short form only when all hold: `corroborate.fill_problem` returns `None`, `shortcheck.problems` returns `[]`, the checker answered `faithful: true` for its id, and the record's claim digest is the one the writer saw.
- The pass writes at most one short form for one wording of a claim, ever: once applied, that wording is never asked again, so a short form that was undone, or removed by the owner, does not come back until the claim changes.
- The only way to store a short form without the code check and without the mark `short_by: model` is `mem memory edit --short TEXT --user-read`, which is for a short form the owner read.
- The writer and checker sessions run through `session_cmd` unchanged: tools `Read,Write`, no Bash, no web, hooks disabled, `research_pipeline.session_env`.
- `load` is never set by the automatic step. A record with `load == "no"` is not a candidate (already so in `rules.eligible`).
- An edit of a claim removes `short` and `short_by` together.
- The fill step's log line and status hold numbers only; memory text goes only into the private run folder and the records.
- Exact values: at most `corroborate.FILL_CAP` (30) lessons a run; `FILL_ATTEMPTS = 2` per claim wording; `FILL_FAILURES = 3` failed sessions in a row before the step waits for the candidates to change; budget per session `budget_of(...)` as the pass.
- No test fixture holds text from the owner's store: this repository is public.
- Text written into the project is English. Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`.
- The changelog line under `## [Unreleased]` is written in Task 6; the version does not change in this plan.

## Review Focus

- A claim with a hedge whose short form states it flatly ("may help" → "Do X"): refused by code, never applied (Task 1).
- The owner undoes a fill run or removes a short form: the next run starts no session for that lesson (Task 4).
- An answer file that cannot be used (no list, not JSON) from the writer or the checker: a failed session, no attempt counted, no lesson sent to triage (Task 4).
- A model rewording a short form through `mem memory edit --short`: checked by code and marked as unread, never silently "read" (Task 2).
- The fill step crashes or its session fails: the pass's own result, `seen.json` and status are what they would be without the step (Task 5).

---

### Task 1: The code check of a short form against its claim

**Files:**
- Create: `plugins/memory/engine/shortcheck.py`
- Test: `plugins/memory/engine/tests/test_shortcheck.py`

**Interfaces:**
- Produces: `shortcheck.problems(claim: str, short: str) -> list[str]`: English reasons in the table's order, `[]` when the short form passes. `shortcheck.HEDGES: frozenset[str]`, `shortcheck.ABSOLUTES: frozenset[str]`. Length and the one-line rule stay where they are (`records.valid_short`, `corroborate.fill_problem`, `_check_short_topic`); this module adds the rules below.

Words are compared whole and lowercase; a word keeps its apostrophe (`can't` is not `can`, `maybe` is not `may`).

| Rule | Reason text |
|---|---|
| The claim holds a word of `HEDGES` and the short form holds none | `the claim is hedged and the short form is not` |
| The short form holds a word of `ABSOLUTES` that the claim does not hold | `the short form says "<word>" and the claim does not` (one reason per word, in the order of the short form) |
| The short form holds `http://`, `https://` or `www.` | `the short form holds a link` |
| The short form holds the word `owner` | `the short form says "owner": say "the user"` |

`HEDGES`: may, might, can, could, sometimes, often, usually, once, untested, provisional, seems, seemed, likely, probably, consider, perhaps. `ABSOLUTES`: always, never, must, every, all, only, none, cannot, can't, guarantees, ensures, proves.

- [x] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("claim,short,expected", [
    ("Smaller briefs may avoid the turn limit (untested).", "Smaller briefs may avoid a subagent's turn limit.", []),
    ("Smaller briefs may avoid the turn limit.", "Use smaller briefs to avoid the turn limit.", ["the claim is hedged and the short form is not"]),
    ("Check the count in the run log before calling a backfill complete.", "Always check the run log.", ['the short form says "always" and the claim does not']),
    ("Never push without asking.", "Never push without asking.", []),
    ("Read the docs.", "Read https://example.org first.", ["the short form holds a link"]),
    ("It may be so.", "Maybe do it.", ["the claim is hedged and the short form is not"]),
    ("It can't be undone.", "It can't be undone.", []),                      # `can't` is not the hedge `can`
    ("Ask the owner first.", "Ask the owner first.", ['the short form says "owner": say "the user"']),
])
def test_problems(claim, short, expected): assert shortcheck.problems(claim, short) == expected

def test_two_problems_are_both_reported_hedge_first(): ...   # hedge dropped and "must" added
def test_case_and_punctuation_do_not_hide_a_word(): ...      # "MAY," in the claim, "Never." in the short
```

- [x] **Step 2: Run and see them fail** — `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_shortcheck.py -q`.
- [x] **Step 3: Implement** `shortcheck.py`, pure, no import from the engine.
- [x] **Step 4: Run the file's tests**; expected: all pass.
- [x] **Step 5: Commit** — `feat(memory): a code check that a short form is not stronger than its claim`

### Task 2: `short_by`, the unread list, and holding a lesson at triage

**Files:**
- Modify: `plugins/memory/engine/records.py` (`Memory`, `_parse`, `_render`, `write_memory`), `plugins/memory/engine/mem.py` (`cmd_remember`, `cmd_memory` edit, `cmd_show`, `cmd_curate`, `cmd_triage`, `cmd_rules` and their parsers), `plugins/memory/bin/mem-corroborate` (`fill_items` passes `--user-read`)
- Test: `plugins/memory/engine/tests/test_short_by.py`, `plugins/memory/engine/tests/test_triage.py`

**Interfaces:**
- Consumes: `shortcheck.problems` (Task 1).
- Produces:
  - `Memory.short_by: str | None` (`"model"` or `None`; any other stored value reads as `None`; rendered after `short`) and `Memory.triage_reason: str | None` (one line, at most 200 characters; rendered after `triage`; read as `None` unless `triage == "pending"`).
  - `mem memory edit <h> --short TEXT` and `mem remember ... --short TEXT`: run `shortcheck.problems(claim, TEXT)`; any reason exits 2, printing the reasons on stderr, and writes nothing; otherwise the short form is stored with `short_by: model`.
  - `... --short TEXT --user-read`: no code check, `short_by` removed. `--user-read` without `--short` exits 2. `fill --items FILE` (a file the owner read) applies with `--user-read`; its behavior is otherwise unchanged.
  - A claim edit that removes `short` removes `short_by` too.
  - `mem rules --unread`: one block per live lesson with `short_by == "model"` and a valid `short`, project scope first then global, as `m:<handle>\t<scope>\t<short>` then `\tclaim: <claim on one line>`; with none, the line `No short form is waiting to be read.` Exit 0.
  - `mem rules --read <handle>... | --read all`: removes `short_by` from the named lessons (or from every lesson `--unread` lists), logging before each change as the edit command does; prints `m:<handle>\tread` per lesson; an unknown handle exits 2 and changes nothing.
  - `mem triage hold <handle> --because TEXT` (a third subcommand in the triage parser, beside `accept` and `reject`): global scope, an active lesson that is not in quarantine; sets `triage: pending` and `triage_reason`; logged as the other triage commands. `mem triage accept` and `reject` clear `triage_reason`. `mem curate --global` and `mem show` print the reason after a lesson that has one.
  - `mem curate` (both scopes) adds one line when any exist: `short forms nobody read: <N> (mem rules --unread)`.
  - `mem show m:<h>` prints `short_by: model` when set.

- [x] **Step 1: Write the failing tests**

```python
def test_a_plain_short_edit_is_checked_and_marked_as_the_models(gfolder, capsys): ...
def test_a_plain_short_edit_that_drops_the_hedge_is_refused_with_the_reason(gfolder, capsys): ...   # exit 2, record unchanged
def test_user_read_skips_the_check_and_clears_the_mark(gfolder, capsys): ...
def test_user_read_without_short_is_refused(gfolder, capsys): ...            # exit 2
def test_a_claim_edit_removes_short_and_short_by(gfolder, capsys): ...
def test_a_bad_stored_short_by_reads_as_absent(gfolder): ...                 # `short_by: 7` and `short_by: owner`
def test_unread_lists_project_then_global_and_skips_invalid_shorts(project, gfolder, capsys): ...
def test_unread_with_nothing_says_so(gfolder, capsys): ...
def test_read_all_clears_every_listed_lesson_and_read_of_an_unknown_handle_changes_nothing(gfolder, capsys): ...
def test_confirm_merge_and_triage_keep_short_by(gfolder, capsys): ...
def test_curate_counts_the_unread_short_forms_and_says_nothing_with_none(gfolder, capsys): ...
def test_fill_items_applies_a_read_file_without_the_mark(world): ...         # in test_mem_corroborate.py
# test_triage.py
def test_hold_sets_pending_with_its_reason_and_accept_clears_both(gfolder, capsys): ...
def test_hold_refuses_a_lesson_in_quarantine_and_a_missing_reason(gfolder, capsys): ...
def test_a_held_lesson_does_not_load_and_curate_prints_its_reason(gfolder, capsys): ...
```

- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the two files' tests, `test_short_topic.py`, `test_memory_edit.py`, `test_rules.py`, `test_rules_session.py`, `test_mem_corroborate.py`**; expected: all pass (tests that store a short form by hand add `--user-read` or use a short form that passes the check).
- [x] **Step 5: Commit** — `feat(memory): a mark on a short form nobody read, the unread list, and mem triage hold`

### Task 3: The pure parts of the automatic fill

**Files:**
- Modify: `plugins/memory/engine/corroborate.py`, `plugins/memory/bin/mem-corroborate` (`stable_key` calls the engine's new `fill_key`; the applying core of `fill_items` becomes one function)
- Test: `plugins/memory/engine/tests/test_fill_auto.py`, `plugins/memory/engine/tests/test_mem_corroborate.py`

**Interfaces:**
- Produces, in `corroborate.py`:
  - `FILL_ATTEMPTS = 2`, `FILL_FAILURES = 3`.
  - `fill_key(project: Path | None, handle: str) -> str`: `g:<handle>` or `<records.project_key(project)>:<handle>`; `bin/mem-corroborate`'s `stable_key` calls it.
  - `fill_candidates(..., cap=FILL_CAP, attempts: dict | None = None)`: with `attempts`, a lesson whose entry is `{"digest": <its claim digest>, "count": >= FILL_ATTEMPTS}` is dropped before the cap is applied (a changed digest starts again at zero); a project lesson of weight `strong` without `owner_confirmed` is dropped too when `attempts` is given. Without `attempts` the function behaves as today (`fill --dry-run`).
  - `check_lines(items: Sequence[tuple[str, str, str | None, str]]) -> str`: blocks of `id:`, `claim:`, `context:` (when there is one), `short:`, each on one line, separated by a blank line.
  - `validate_check(payload: object, ids: Sequence[str]) -> dict[str, bool] | None`: for `{"verdicts": [{"id", "reason", "faithful"}]}`, id → faithful, `False` unless `faithful` is exactly `true`; a verdict for an id that was not asked is ignored. `None` (an unusable answer) when `payload` is not an object with a list `verdicts`, or when it does not hold exactly one verdict for every id asked (changed in the fix round: a partial answer must not cost attempts).
  - `validate_fill` keeps its return, and its caller treats the reason `the answer is not an object with a list \`items\`` as an unusable answer.
- Produces, in `bin/mem-corroborate`: `apply_fill(items: list[dict], run: Path, user_read: bool) -> dict` (as built; the first draft had an unused `cdir`), returning `{"written": int, "dropped": int, "failed": int, "applied": list[str], "refused": list[str]}` (`applied` and `refused` hold the `id` of each item written, or refused by `mem memory edit`); with `user_read=False` it passes no load flag and drops a record whose `load` is `no`: the journal, the digest guard, the empty marker file `run / "fill"` that makes `undo` leave the pass's `seen.json` alone, and the `mem memory edit` calls `fill_items` has today; `user_read=True` adds `--user-read`. `fill_items` calls it with `user_read=True`. A run folder of a fill is named `<stamp>-<pid>-fill`.

- [x] **Step 1: Write the failing tests**

```python
# test_fill_auto.py
def test_fill_key_is_the_same_whatever_the_registry_order(tmp_path): ...
def test_candidates_drop_a_lesson_after_two_attempts_before_the_cap(world): ...    # 31 lessons, the first spent: 30 others asked
def test_a_changed_claim_is_a_candidate_again(world): ...
def test_a_strong_project_lesson_is_a_candidate_only_once_the_owner_confirmed_it(world): ...
def test_candidates_without_attempts_are_what_they_were(world): ...
def test_validate_check_counts_only_an_exact_true(): ...     # "yes", 1, missing, repeated id, unknown id: all False
def test_validate_check_of_an_unusable_answer_is_none(): ... # a list, a string, {"verdicts": 3}
def test_check_lines_puts_each_field_on_one_line_and_omits_an_empty_context(): ...
# test_mem_corroborate.py
def test_fill_items_and_undo_behave_as_before_through_apply_fill(world): ...
```

- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run `test_fill_auto.py`, `test_mem_corroborate.py`, `test_corroborate.py`**; expected: all pass.
- [x] **Step 5: Commit** — `refactor(memory): the fill's applying core and candidates take what the automatic fill needs`

### Task 4: The automatic fill

**Files:**
- Modify: `plugins/memory/bin/mem-corroborate`
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py` (with the fake `claude` that file already uses)

**Interfaces:**
- Consumes: Task 1 (`shortcheck.problems`), Task 2 (`mem triage hold --because`; a plain `--short` edit marks `short_by: model`), Task 3 (`fill_candidates(attempts=...)`, `fill_key`, `check_lines`, `validate_check`, `apply_fill`).
- Produces: `CHECK_BRIEF` (text below, verbatim) and `CHECK_MODEL = "haiku"` beside `FILL_BRIEF` (the gate may change `CHECK_MODEL` to `"sonnet"`); `fill_auto(claude: str | None, budget: float) -> dict` returning `{"asked", "written", "dropped", "refused_code", "refused_check", "to_triage", "left", "cost", "stopped"}`: numbers, except `stopped`, which is `None` or a short reason why the step did not finish (`apply_fill`'s `failed` count is added to `left`). It saves the same dict with `save_status(cdir, fill=...)` and writes the handles applied to `applied.json` in its run folder, so what the owner later rewords or turns off can be counted. State in `<corroborate dir>/fill-attempts.json`, a private file: `{"lessons": {<fill_key>: {"digest", "count"}}, "failures": {"count", "fingerprint"}}`.

Flow of `fill_auto`. It takes the run lock itself (`au.take_run_lock`), after the pass released it; with the lock taken it returns `stopped: "a run is going"` and writes nothing.

1. Candidates: `fill_candidates(..., attempts=state["lessons"])`. None: return zeros, start no session. If `state["failures"]["count"] >= FILL_FAILURES` and the fingerprint (a digest of the sorted `fill_key` and claim digest of the candidates) is the stored one: return `stopped: "waiting for the lessons to change"`, start no session.
2. Writer session (`PROPOSE_MODEL`, `FILL_BRIEF`), then `validate_fill`. No result, an error, or an unusable answer: go to step 9.
3. For each item without a `problem`: `shortcheck.problems(claim, short)`; an item with any reason counts in `refused_code`.
4. Checker session (`CHECK_MODEL`, `CHECK_BRIEF`) over the items that passed step 3 only; with none, no session. `validate_check`. No result, an error, or `None`: go to step 9. A `False` counts in `refused_check`.
5. `apply_fill(passed, ..., user_read=False)`. A dropped item (its claim digest changed) gets no attempt.
6. Attempts, saved after the apply: an applied lesson gets `{"digest", "count": FILL_ATTEMPTS}`; a lesson asked and refused (no proposal, a `problem`, refused by code or by the checker) gets its count raised by one.
7. A refused lesson whose count reached `FILL_ATTEMPTS`: a global one gets `mem triage hold m:<handle> --because "<the last reason, cut to 200 characters>"` (counted in `to_triage`); a project one is counted in `left`. Reasons: the `problem`, the first `shortcheck` reason, or `the checker did not find the short form faithful to the claim`.
8. A run that reached step 5 (every session it started gave a usable answer) resets `failures` to zero, whatever was refused.
9. A failed session: `stopped` set, no attempt counted for any lesson, `failures.count` raised by one with the fingerprint, nothing applied from this run.

`CHECK_BRIEF`, verbatim:

```
You check one-sentence short forms of lessons against the lessons they were drawn from. Another writer made them; it sometimes makes a short form stronger or wider than its lesson, and a short form is loaded into every later session, so say faithful only when you are sure.
Read {pairs}: one block per lesson, with an id, a claim, sometimes a context that says when the lesson applies, and a short.
For each block answer in this order:
- reason: one sentence comparing what the claim asks, and when, with what the short asks, and when.
- faithful: true only if the short asks for nothing the claim does not, in no wider a situation, with no more certainty (a "may" or "once" in the claim is still there in the short), as a suggestion and not an order unless the claim is an order (a command addressed to the reader, such as "remove the files" or "confirm it first", is an order even when a "may" stands elsewhere in the sentence), and names no project, person or company. A short that leaves out examples or alternatives is still faithful; one that leaves out the situation the claim is about is not.
Write {out} as JSON: {{"verdicts": [{{"id": "g:example", "reason": "...", "faithful": true}}]}}
One entry per block. Write nothing else and use no other tool.
```

- [x] **Step 1: Write the failing tests**

```python
def test_fill_auto_writes_a_checked_short_form_marked_as_the_models(world): ...   # short, topic, short_by: model; load untouched
def test_fill_auto_refuses_by_code_before_paying_the_checker(world): ...          # hedge dropped: refused_code 1, one session only
def test_fill_auto_does_not_write_what_the_checker_refused(world): ...
def test_a_general_lesson_is_held_at_triage_with_its_reason_after_two_refusals_and_a_project_lesson_is_left(world): ...
def test_a_third_run_starts_no_session_for_a_lesson_refused_twice(world): ...
def test_an_applied_short_form_that_was_undone_is_not_written_again(world): ...
def test_an_applied_short_form_the_owner_removed_is_not_written_again_until_the_claim_changes(world): ...
def test_a_claim_edited_during_the_run_gets_no_short_form_and_no_attempt(world): ...
def test_an_index_only_lesson_keeps_its_load_and_a_turned_off_lesson_is_not_asked(world): ...
@pytest.mark.parametrize("bad", ["no file", "not json", '{"items": 3}'])
def test_an_unusable_writer_answer_counts_no_attempt_and_sends_nothing_to_triage(world, bad): ...
def test_an_unusable_checker_answer_counts_no_attempt_and_applies_nothing(world): ...
def test_after_three_failed_sessions_no_session_starts_until_the_candidates_change(world): ...
def test_a_good_run_between_failures_starts_the_count_of_failures_again(world): ...   # fail, good, fail, fail: a session still starts
def test_the_run_folder_keeps_the_fill_marker_and_the_applied_handles(world): ...
def test_fill_auto_with_the_lock_taken_writes_nothing(world): ...
def test_two_fill_runs_in_the_same_second_keep_separate_run_folders(world): ...
def test_undo_of_an_automatic_fill_run_restores_the_records(world): ...
```

- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Run `test_mem_corroborate.py`, `test_fill_auto.py`**; expected: all pass.
- [x] **Step 5: Commit** — `feat(memory): the pass writes and checks short forms by itself`

### Task 5: The pass runs the fill, and only a strong lesson waits

**Files:**
- Modify: `plugins/memory/bin/mem-corroborate` (`cmd_auto`, `cmd_status`), `plugins/memory/engine/records.py` (`standing_changes`), `plugins/memory/engine/mem.py` (the `unready` line of `cmd_rules`)
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py`, `plugins/memory/engine/tests/test_triage.py`, `plugins/memory/engine/tests/test_quarantine.py`, `plugins/memory/engine/tests/test_rules.py`

**Interfaces:**
- Consumes: `fill_auto` (Task 4).
- Produces:
  - `cmd_auto`: after `execute(...)`, whatever its result, calls `fill_auto` in its own `try` unless the loaded rules are off (`os.environ.get("CLAUDE_PLUGIN_OPTION_LOADED_RULES") == "false"` or `os.environ.get("MEM_LOADED_RULES") == "off"`, the two forms the hooks use); appends one line `{"t", "fill": {...the dict of fill_auto}, "ms"}` with `append_log`.
  - `mem-corroborate status` reads the `fill` entry `fill_auto` saved in the status file and adds one line when that fill wrote, refused or stopped: `last fill: <written> written, <refused_code + refused_check> refused, <to_triage> to triage` plus `, stopped: <reason>`.
  - `records.standing_changes`: on the first establishment of a global record, `triage: "pending"` only when `(after.weight or "medium") == "strong"` and the owner has not confirmed it. A `light` or `medium` one gets `released` and no triage.
  - `cmd_rules` `unready` wording: `<N> established lesson(s) have no short form yet: the background pass writes them when auto_capture is on (mem-corroborate status shows the last one).`

- [x] **Step 1: Write the failing tests**

```python
def test_auto_runs_the_fill_after_the_pass_and_logs_its_counts(world): ...
def test_auto_skips_the_fill_when_loaded_rules_is_off(world, monkeypatch): ...
def test_a_fill_that_raises_leaves_the_pass_result_seen_and_status_alone(world, monkeypatch): ...
def test_status_shows_the_last_fill_and_its_failure(world, capsys): ...
def test_a_medium_general_lesson_is_released_without_triage_and_a_strong_one_waits(gfolder): ...
def test_a_released_medium_lesson_loads_once_it_has_a_short_form(gfolder): ...   # rules.choose puts it in `loaded`
def test_rules_says_the_pass_writes_the_missing_short_forms(gfolder, capsys): ...
```

- [x] **Step 2: Run and see them fail.**
- [x] **Step 3: Implement.** The tests of `test_triage.py` and `test_quarantine.py` that expect a `medium` lesson at triage now use `strong`.
- [x] **Step 4: Run the whole suite**; expected: all pass.
- [x] **Step 5: Commit** — `feat(memory): the background pass fills short forms; only a strong lesson waits at triage`

### Task 6: Documentation

**Files:**
- Modify: `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md`, `plugins/memory/skills/memory/SKILL.md` and `plugins/memory/skills/memory-curation/SKILL.md` only where they describe `fill`, `--short`, triage or `mem rules`; `docs/superpowers/plans/2026-11-17-memory-plugin.md` (state table and "Next")

- [x] **Step 1:** README: how a short form now comes to load (written and checked by the pass, marked, listed by `mem rules --unread`, read with `mem rules --read`, switched off with `--no-load` or the option `loaded_rules`); what waits for the owner (a `strong` lesson; a lesson refused twice, with its reason at triage). Mark what the gate measured apart from what is not measured.
- [x] **Step 2:** Changelog under `## [Unreleased]`, for users: short forms load without being read first when `auto_capture` is on; how to list, read and switch them off; a `medium` or `light` general lesson no longer waits at triage; `mem memory edit --short` now checks the text and marks it unread unless `--user-read` is given.
- [x] **Step 3:** The curation skill: the curator lists `mem rules --unread` in its table and proposes; it never runs `--read` and never passes `--user-read`, which are the owner's.
- [x] **Step 4:** `python3 scripts/validate.py` and `claude plugin validate .` pass.
- [x] **Step 5: Commit** — `docs(memory): short forms written by the pass, and what still waits for the owner`

## After the tasks

- [x] The six tasks built on 2026-11-22, each reviewed after its commit, with two fix rounds on the automatic fill (the path where the apply raises; a load the owner changed during a run; a partial answer of the checker) and one rule added by the docs review: the pass never touches a lesson that already has a valid short form, even without a topic. Whole suite: 1875 passed, 5 skipped before the last small fixes.
- [ ] **Gate, on a private copy of the real store, outside the repository.** The rule is fixed here, before any run (C62).

  | Set | What it is |
  |---|---|
  | Read | The 10 short forms the owner read on 2026-11-22, with their claims: the only human labels. The 5 the author set that day are scored and reported apart, and decide nothing |
  | Stronger | 20 variants of the Read set, two per form, written by a separate session that sees the claims and the five kinds (hedge removed; an absolute added; the situation widened; a claim added; a suggestion turned into an order) and does not see `shortcheck.py` or `CHECK_BRIEF` |

  | Measure | Pass |
  |---|---|
  | `shortcheck.problems` on Read | at most 1 of 10 refused |
  | The checker on Read, Haiku and Sonnet, 2 runs each | at least 9 of 10 faithful in both runs |
  | Code and checker together on Stronger, with each of the two models, 2 runs each | at least 17 of 20 refused in both runs |
  | `fill_auto` on the copy with every `short` removed | every applied short form is shown to the owner beside its claim in one table; the owner calls none stronger than its claim |

  The checker is Haiku if Haiku passes its rows on both sets, else Sonnet if Sonnet does. One revision of `CHECK_BRIEF` or the word lists is allowed after a miss; the whole table then runs again on a new Stronger set from a new session. A second miss: stop and put the figures to the owner; do not ship the automatic step. Ten labels can catch a bad checker; they cannot prove a good one, which is why the kill criteria below keep counting after release.
- [ ] One run of `mem-corroborate auto` from the installed copy of the branch (`claude --plugin-dir`), not only from the repository tests: its log line, and, with the option `loaded_rules` set to false, that the detached process skips the fill.
- [ ] On the owner's store, before the first automatic run: how many established lessons lack a short form (the first run loads up to 30 at once) and that none of weight `light` or `medium` is at `triage: pending`.
- [ ] Narrow reviews in parallel (the fill flow, the record fields and commands, the docs against the code, the process), one fix wave.
- [ ] Results written into this file under `## Results`; the design rows C59 to C62 corrected if the gate changed them.
- [ ] A pull request to `dev` and a release: only with the owner's word.

## Pre-mortem of 2026-11-22 and what changed

| Failure story | Amendment |
|---|---|
| A short form the owner undid or removed is written again at the next run | An applied wording is spent: the pass never writes a second short form for it (Global Constraints, Task 4 step 6) |
| An answer file that cannot be used counts an attempt for all 30 lessons and sends them to triage | An unusable answer is a failed session: no attempt, nothing to triage (Tasks 3 and 4) |
| A failing service pays a writer session at every capture | Three failures in a row and the step waits for the candidates to change (Task 4) |
| A curator model rewords a short form with `--short` and it loads unchecked and unmarked | A plain `--short` is checked by code and marked; only `--user-read` skips both (Task 2) |
| A `strong` project lesson loads unread, since triage exists only for general lessons | The pass does not fill it until the owner confirmed it (Task 3) |
| Holes in the word lists; the checker brief said both "less detail is fine" and "no wider a situation" | `only`, `none`, `cannot`, `can't` added, "owner" refused; the brief separates examples from the situation and the checker reads the context (Tasks 1 and 4). Not taken: requiring every hedge word of the claim, which would refuse a short form that keeps one of two hedges; the gate measures the simpler rule |
| The gate called 15 forms "owner-read" when the owner read 10, the author wrote the variants knowing the word lists, and a revision was scored on the same items | Ten labels; variants from a session blind to the checks; a new set after a revision; the owner, not the author, reads the applied short forms (After the tasks) |
| Spent lessons fill the cap of 30; no command set `triage: pending`; the attempts key and the run folder name were undefined | Spent lessons leave before the cap; `mem triage hold --because`; `fill_key`; `-fill` run folders (Tasks 2 to 4) |

## Known limits

| Limit | Why it stays |
|---|---|
| The word lists are English and fixed | Lessons are written in English (C11); the checker covers what the lists miss |
| A claim that is itself overstated yields a faithful, overstated short form | The claim is the capture's and the pass's responsibility; this plan checks the short form against it |
| The checker may be the same model family as the writer | The gate decides; a different brief and no shared reasoning is what the evidence supports cheaply |
| A short form that is faithful but useless still loads | Usefulness is C49 |
| A lesson held at triage after two refusals gets no short form from the pass once accepted | Its count is spent; the owner or the agent writes one with `mem memory edit --short` |
| A `mem triage hold` that fails leaves its lesson spent and not held (counted in `left`); a hold is not journaled, so `undo` of a fill run does not release it | Rare, and visible: the lesson shows as having no short form in `mem rules`; `mem triage accept` releases a hold |
| Two applies that fail in a row send a general lesson to triage with the reason "the apply failed" | Bounded by `FILL_FAILURES` and the kill criterion on `to_triage` |
| A plain `--short` that repeats a text the owner already read marks it unread again; a hyphenated word counts by its parts ("never-ending" reads as "never"); the `held:` line of `mem curate` prints in both scopes | Low findings of the task reviews, left open: each errs toward asking or refusing, never toward loading something unchecked |
| Nothing tells the owner at session start that unread short forms exist | The owner's wariness of noise there (C51); `mem curate` shows the count |

## Kill criteria

- The gate misses twice: the automatic step does not ship.
- A short form is written again after an undo or a removal, or a short form without the mark fails `shortcheck` on the store: stop the step until fixed.
- `to_triage` above 3 in one run, or more than 2 fill sessions in a day on unchanged candidates (both from the log): a counting or parsing defect; stop the step.
- Within two weeks of release, of the handles in the runs' `applied.json`, the owner reworded or turned off more than 1 in 5: back to reading before loading. If the owner read none by day 7, the agent shows the list once, since the criterion cannot be read otherwise.
- A loaded short form is found stronger than its claim: add the case to `test_shortcheck.py` or the gate's set, and run the gate again before the next release.
- The fill's sessions cost more than 0.05 USD a day on the owner's logs for a week: lower `FILL_CAP`, or run the fill only when a lesson was released.
