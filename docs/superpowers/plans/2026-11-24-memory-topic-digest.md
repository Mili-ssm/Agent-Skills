# Digest per topic and new limits of the loaded lessons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The loaded lessons have no limit of number and twice the characters, with a third kept for an index of the rest by topic; and, behind the option value `rules_layout: digest`, each topic prints a heading with the situation its lessons share and one line per lesson that leans on it, written by the background pass and checked, with the short forms as fallback.

**Architecture:** The digest is a derived JSON file in the plugin's data folder, read by the engine at session start and written only by a new step of `bin/mem-corroborate`, built beside the fill and the rewording. Each text carries a fingerprint of what it was written from, so a stale or missing text falls back to the short form without a model. `rules.choose` keeps ranking and choosing on the short forms; only its limits change.

**Tech Stack:** Python 3 standard library and PyYAML, pytest. Engine in `plugins/memory/engine/`, commands in `plugins/memory/bin/`, hooks in `plugins/memory/hooks/`.

**Spec:** [the design](../specs/2026-11-24-memory-topic-digest-design.md), rows C86 to C97. Read it before any task.

## Global Constraints

- Branch `feat/memory-topic-digest`; one local commit per task; stage only the files the task names, by path; no push, no pull request, no merge.
- With `rules_layout` unset, `flat` or `grouped`, nothing of the digest runs, no digest file is written, and the block's lines are those of 0.8.0; only the limits of Task 1 and, when a fresh heading happens to exist, the index of Task 2 differ.
- The records' files are never written by this plan's code: the digest lives in the data folder only.
- `rules.choose` keeps its ranking; lessons are chosen on their short forms. The fill, the rewording and their briefs are not edited: what the new step needs from them it calls as it is or copies under a new name.
- A text of the digest is printed only when its fingerprint matches what it was written from; otherwise the short form (for a line) or the bare topic (for a heading) is printed. Nothing printed at session start calls a model.
- A background command never raises and never prints; a failure is a counted result.
- No real model is called by a test: tests use the fake `claude` script of `test_mem_corroborate.py`.
- The repository is public: no home path, private repository name, client name, note title, real handle, claim or short form of the owner's store in code, tests or docs.
- The whole suite, once at the end of each task: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q > <a file in a temporary directory> 2>&1` (about five minutes; foreground, timeout 600 s; read its last line). `test_merge_logs_both_files_and_restore_undoes_each` fails during the hour after local midnight; that is known.
- An existing test that asserts an exact output this plan changes is updated in the task that changes it and named in its report.

## Stop and report

| Observation | Action |
|---|---|
| A test of the fill, the rewording, corroboration or capture changes its result, other than a test that states the old limit of number (`test_reword.py`, `test_case_log.py`, `test_rules.py`, `test_rules_session.py` build cases from `RULES_MAX`): those are rewritten from the limit of characters in Task 1 and named in its report | Stop |
| A record file changes during a run of the digest step | Stop |
| The session start text passes 9500 characters in any test (text a hook injects is cut at 10,000 characters: [the plugin design](../specs/2026-11-17-memory-plugin-design.md)) | Stop and report the figure |
| Task 7: fewer than half of the lines that pass the code check are accepted, or more than one heading is refused | Stop: record the figures; do not edit the briefs |
| Task 7: an authentication error, nothing asked, or anything under the owner's real memory folders or the plugin's real logs changes | Stop; do not point `HOME` elsewhere |

## Review Focus

| Input or condition | Expected | Pinned in |
|---|---|---|
| A digest file that is missing, empty, not JSON, or holds values of the wrong type | Reads as no digest; the block prints as `grouped` | Task 2 |
| A lesson reworded, or its claim edited, since its line was written | Its short form is printed; the other lines of the topic stay | Task 2, Task 3 |
| A topic that lost or gained a lesson since its heading was written | The bare topic and, per lesson, its line if fresh | Task 2 |
| A topic with one lesson that is ready to load | Not digested: no heading asked, printed as `grouped` | Task 2, Task 4 |
| The writer returns a line for a lesson it was not asked about, or a heading for a topic that did not ask | Ignored | Task 4 |

## File Structure

| File | Change |
|---|---|
| `plugins/memory/engine/rules.py` | The limits; the index; the layout `digest` |
| `plugins/memory/engine/digest.py` | New: the file's shape, fingerprints, reading and writing, what is fresh; the pure functions of the step |
| `plugins/memory/engine/mem.py` | `mem rules --layout digest`, the session start text |
| `plugins/memory/hooks/session-index.sh`, `session-env.sh`, `plugins/memory/.claude-plugin/plugin.json` | The value `digest` of `rules_layout` |
| `plugins/memory/bin/mem-corroborate` | `DIGEST_BRIEF`, `DIGEST_CHECK_BRIEF`, `digest_auto`, the subcommand `digest`, the step in `cmd_auto` |
| `plugins/memory/engine/tests/test_digest.py` | New: the tests of Tasks 2, 3 and 4 |

---

### Task 1: New limits of the loaded lessons (C96)

**Files:**
- Modify: `plugins/memory/engine/rules.py` (`RULES_MAX`, `RULES_LIMIT`, `MORE_LIMIT`, `choose`, `more_line`)
- Modify: every test under `plugins/memory/engine/tests/` that states the old limits or builds a case from the limit of number (search for `RULES_MAX`, `RULES_LIMIT`, `MORE_LIMIT`; at least `test_rules.py`, `test_rules_session.py`, `test_reword.py`, `test_case_log.py`): a case that needed "one lesson more than the limit" is rebuilt from the limit of characters
- Modify: `docs/adr/0023-a-memory-plugin-makes-a-note-store-reachable-from-every-repository.md` (a new section at its end, `## Review 2026-11-24`; never edit an existing section or the Status line), `plugins/memory/CHANGELOG.md` (one line under `## [Unreleased]`, `### Changed`), `plugins/memory/README.md` where it states the limits

**Interfaces:**
- Produces: `RULES_LIMIT = 3200` (characters of lesson lines); `INDEX_LIMIT = 1600` (characters of the index; `MORE_LIMIT` is removed and every use of it reads `INDEX_LIMIT`); `RULES_MAX` is removed and `choose` no longer counts lessons. Everything else of `choose` (the order, `PROJECT_FIRST`, "nothing ranked lower jumps ahead of a rule that did not fit") is unchanged. `more_line` keeps its present text and logic within the new limit (it can now name more topics; `TOPICS_NAMED` stays).

- [ ] **Step 1: Change the tests that state the limits to the constants, and add `test_no_limit_of_number_only_of_characters` in `test_rules.py`**

Thirty lessons that are ready to load, with short forms of about 100 characters: the loaded ones fill at most `RULES_LIMIT` characters, there are more than 16 of them, and the rest are left out with the reason `OVER`.

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Change the constants and `choose`**

- [ ] **Step 4: Write the documents**

ADR 0023, `## Review 2026-11-24`, two or three sentences: the limits of C73 are replaced by C96 of the topic digest design (no limit of number; 3200 characters of lessons and 1600 of index); unmeasured; kill criterion: "Lower the limits again if, a month after the release that carries C96, the lessons that load only because of it show more `failed` than `worked` cases in their tallies, or the owner reports that loaded lessons are ignored more often." Changelog: what a user sees (more lessons load; nothing to do). No line numbers.

- [ ] **Step 5: Run the whole suite, `python3 scripts/validate.py` and `claude plugin validate .`**

- [ ] **Step 6: Commit**

```bash
git add plugins/memory/engine/rules.py plugins/memory/engine/tests plugins/memory/CHANGELOG.md plugins/memory/README.md docs/adr
git commit -m "feat(memory): no limit on the number of loaded lessons, 3200 characters of lessons and 1600 of index"
```

---

### Task 2: The digest file and what is fresh (C88, C89, C90)

**Files:**
- Create: `plugins/memory/engine/digest.py`
- Test: `plugins/memory/engine/tests/test_digest.py` (create)

**Interfaces:**
- Produces, in `digest.py`:
  - `FILE = "rules-digest.json"`, in the plugin's data folder (the folder `mem.py` and `bin/mem-corroborate` already resolve from `MEM_DATA`, `XDG_STATE_HOME` or `HOME`; read how `mem.py` finds it and use the same function).
  - `HEADING_LIMIT = 80`.
  - The file's shape: `{"topics": {"<topic>": {"heading": str, "of": str, "lines": {"<handle>": {"text": str, "of": str, "under": str}}}}}`: `of` is the fingerprint of what the text was written from, `under` the fingerprint of the heading a line was written under.
  - `line_print(m: Memory) -> str`: a fingerprint of the lesson's claim and short form.
  - `heading_print(lessons: Sequence[Memory]) -> str`: a fingerprint of the sorted handles of the topic's lessons and of each one's claim.
  - `read(data: Path | None) -> dict`: the file's content in the shape above; anything missing, unreadable or of the wrong type reads as `{"topics": {}}`, entry by entry (a bad entry is dropped, the good ones kept). `write(data: Path, digest: dict) -> None`: through a temporary file.
  - `topics_of(global_lessons: Sequence[Memory], today: datetime.date) -> dict[str, list[Memory]]`: the lessons that are ready to load (what `rules.choose` treats as ready: its `loaded` and its `left` with the reasons `OVER` or `INDEX`, when called with no project lesson and `today`) grouped by topic, keeping only the topics with at least two lessons; a lesson without a topic is in none.
  - `heading(digest, topic: str, lessons: Sequence[Memory]) -> str | None`: the stored heading when its `of` equals `heading_print(lessons)`, else None.
  - `line(digest, topic: str, m: Memory, lessons: Sequence[Memory]) -> str | None`: the stored text when its `of` equals `line_print(m)` and its `under` equals the `of` of the topic's stored heading and that heading is fresh, else None.
- [ ] **Step 1: Write the failing tests**

Build lessons as `test_rules.py` builds lessons that load (import its helpers).

| Test | Asserts |
|---|---|
| `test_fingerprints_follow_the_claim_and_the_short_form` | `line_print` changes with the claim and with the short form, not with `log`, `versions` or `topic`; `heading_print` changes when a lesson joins or leaves or a claim changes, not with the order |
| `test_read_drops_what_is_wrong_and_keeps_the_rest` | a missing file, an empty one, `[]`, a topic whose `lines` is a string, a line without `of`: `{"topics": {}}` or the good entries only; nothing raises |
| `test_topics_of_keeps_topics_with_two_ready_lessons` | three lessons under `a` (one index-only), one under `b`, one with no topic, one pending under `a`: `{"a": [the two ready ones and the index-only one]}` per the rule above |
| `test_heading_and_line_are_returned_only_when_fresh` | a digest written for three lessons: `heading` and `line` return the texts; after one lesson's short form changes its `line` is None and the others' are not; after a lesson joins the topic `heading` is None and every `line` is None; a line whose `under` differs from the stored heading's `of` is None |
| `test_write_then_read_round_trip` | `write` through a temporary file, then `read` gives the same dict; no record file is touched |

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_digest.py -q`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run `test_digest.py`, then the whole suite**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine/digest.py plugins/memory/engine/tests/test_digest.py
git commit -m "feat(memory): the digest file of the loaded lessons and what is fresh in it"
```

---

### Task 3: Printing the digest and the index (C93, C96, C97)

**Files:**
- Modify: `plugins/memory/engine/rules.py` (`LAYOUTS`, `block`, a new `index_lines`), `plugins/memory/engine/mem.py` (`session_index`, `cmd_rules` and its parser, the function that resolves the layout), `plugins/memory/hooks/session-index.sh`, `plugins/memory/hooks/session-env.sh`, `plugins/memory/.claude-plugin/plugin.json` (the description of `rules_layout` names the third value; the version is not changed)
- Test: `plugins/memory/engine/tests/test_digest.py`, `plugins/memory/engine/tests/test_rules.py` (it asserts `LAYOUTS`), `plugins/memory/engine/tests/test_rules_session.py`

**Interfaces:**
- Consumes: Task 2's `digest.read`, `digest.topics_of`, `digest.heading`, `digest.line`.
- Produces, in `rules.py`:
  - `HEADINGS_LIMIT = 800`.
  - `LAYOUTS = ("flat", "grouped", "digest")`.
  - `block(choice, layout="flat", *, digest=None, topics=None) -> list[str]`: for `digest`, the grouped block in which a topic with a fresh heading prints `<topic>: <heading>` in place of `<topic>:`, and a global lesson with a fresh line prints `- <line> <standing words>` in place of `rules.line(m)` (same standing words as today). A project lesson, a lesson without a fresh line, and a topic without a fresh heading print as `grouped` prints them. With `digest` None or empty the result equals the `grouped` block. Two bounds keep the text within what a hook may print: a digest line replaces a short form only while the characters of the lesson lines printed so far, this one included, stay within `RULES_LIMIT` (else the short form is printed for it and for every later lesson); and a heading is printed only while the characters of the headings printed so far, this one included, stay within `HEADINGS_LIMIT` (later topics print bare).
  - `index_lines(choice, *, digest=None, topics=None) -> list[str]`: the lines printed after the block for the lessons that did not fit or load by topic only (`not_fitted`): when no fresh heading exists for any of their topics, `[more_line(choice)]` (or `[]` when that is None), as today; otherwise the line `More lessons, by topic (mem rules --more <topic>):` followed by one line per topic, the most lessons first then by name, `- <topic> (<n>): <heading>` or `- <topic> (<n>)`, lessons without a topic under `other`, all within `INDEX_LIMIT` characters; topics that do not fit are summed in a last line `- and <n> more in <k> topics`.
- Produces, in `mem.py`: `mem rules --layout digest` and the session start text read the digest file and the global lessons and pass them to `block` and `index_lines`; `MEM_RULES_LAYOUT=digest` selects it as `grouped` is selected today; both hooks pass the value `digest` as they pass `grouped`. The index with headings is printed in every layout when fresh headings exist. Reading the digest sits inside the `try` that already protects the rules block; on any failure the block is the `grouped` one.


- [ ] **Step 1: Write the failing tests**

Build lessons as `test_rules.py` builds lessons that load (import its helpers).

| Test | Asserts |
|---|---|
| `test_a_fresh_digest_prints_heading_and_lines` | the exact block: `a: when doing x`, then `- <line> (the user vouched for it)` per lesson |
| `test_a_changed_lesson_prints_its_short_form_and_the_rest_keep_their_lines` | after one lesson's short form changes |
| `test_a_changed_topic_prints_the_bare_topic` | after a lesson joins the topic: `a:` and every lesson's short form (a line is fresh only under a fresh heading) |
| `test_no_digest_equals_grouped` | `block(choice, "digest")` and with an empty digest equal `block(choice, "grouped")` |
| `test_a_project_lesson_prints_its_short_form_under_the_heading` | C90 |
| `test_index_names_the_headings_of_topics_left_out` | lessons left out under `a` (fresh heading) and `b` (none): the heading line, `- a (2): when doing x`, `- b (1)`; with no fresh heading at all the result is `[more_line(choice)]` |
| `test_index_stays_within_its_limit` | forty topics left out: the text is within `INDEX_LIMIT`, ends with the summing line, and its counts add up to the lessons left out |
| `test_rules_command_and_session_start_take_the_digest_layout` | `mem rules --layout digest` and `MEM_RULES_LAYOUT=digest mem session-index` print the heading; with the variable unset the session start text equals that of the same store without a digest file, except for the index when fresh headings exist |
| `test_a_broken_digest_file_leaves_the_grouped_block` | the file holds `{`: `mem session-index` with the variable set prints the grouped block and exits 0 |
| `test_the_hooks_pass_the_digest_value` | `session-index.sh` and `session-env.sh` with `CLAUDE_PLUGIN_OPTION_RULES_LAYOUT=digest`, as the existing hook tests run them |
| `test_session_start_text_stays_printable` | thirty loading lessons with a full digest and a full index: the whole text is under the size named in "Stop and report" |
| `test_digest_lines_stay_within_the_limit_of_lesson_lines` | forty lessons with short forms of 60 characters and digest lines of 120: the lesson lines printed total at most `RULES_LIMIT`, the first ones are digest lines and the rest short forms |
| `test_headings_stay_within_their_limit` | thirty topics with headings of 80 characters: the characters of the headings printed total at most `HEADINGS_LIMIT`, the later topics print bare |
| `test_layouts` | `rules.LAYOUTS == ("flat", "grouped", "digest")` (replace the test that asserts two) |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run `test_digest.py`, `test_rules.py`, `test_rules_session.py`, `test_session_index.py`, `test_case_log.py`, then the whole suite, `python3 scripts/validate.py` and `claude plugin validate .`**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine/rules.py plugins/memory/engine/mem.py plugins/memory/hooks/session-index.sh plugins/memory/hooks/session-env.sh plugins/memory/.claude-plugin/plugin.json plugins/memory/engine/tests/test_digest.py plugins/memory/engine/tests/test_rules.py plugins/memory/engine/tests/test_rules_session.py
git commit -m "feat(memory): a digest per topic is printed when present and fresh, and the index names what each topic is about"
```

---

### Task 4: What the step asks for and what it keeps (C87, C89, C91, C92)

**Files:**
- Modify: `plugins/memory/engine/digest.py`
- Test: `plugins/memory/engine/tests/test_digest.py`

**Interfaces:**
- Consumes: Task 2's functions; `shortcheck.problems` (read how `corroborate.py` calls it on a claim and a short form); `records.SHORT_LIMIT`.
- Produces, all pure (no file, no model):
  - `DIGEST_ATTEMPTS = 2`; `DIGEST_LIMIT = 30` (lessons one run asks lines for).
  - `class Work(NamedTuple)`: `topic: str`, `lessons: list[Memory]` (every ready lesson of the topic), `heading_state: str` (`"keep"`: the stored heading is fresh; `"write"`: one must be written; `"given_up"`: one is needed and its try-key counts `DIGEST_ATTEMPTS`), `heading: str | None` (the stored text when the state is `keep`, else None), `write: list[Memory]` (lessons that need a line), `keep: dict[str, str]` (handle to the stored text of the lessons whose line is still written from their present claim and short form).
  - `work(topics: Mapping[str, list[Memory]], digest, state: Mapping) -> list[Work]`: one per topic that needs anything: a heading when the stored one is not fresh (`digest.heading` returns None), a line for every lesson whose stored line is not written from its present claim and short form (compare `of` only; when the heading is rewritten the kept lines are checked again under it, not rewritten). A topic whose heading state is `given_up` gives no work at all: without a heading no line is asked for. Left out besides: a line whose try-key counts `DIGEST_ATTEMPTS` in `state`; a topic that then has nothing to ask for. The works are in the order of the topics' names, and no further topic is added once the lessons to write reach `DIGEST_LIMIT` (a topic is never split). The try-key of a heading is `"h:" + topic + "@" + heading_print(lessons)`; of a line, `"l:" + handle + "@" + line_print(m) + "@" + heading_print(lessons)`. `state` is `{"tries": {key: int}, "failures": {"count": int, "fingerprint": str}}`.
  - `blocks(works: Sequence[Work]) -> str`: what the writer reads: per topic `topic: <name>`, then `heading: <text>` and `heading: keep` when a fresh one is kept or `heading: write`; then per lesson `id: g:<handle>`, `do: write` or `do: keep`, `claim:`, `context:` when there is one, `short:`, and `line: <stored text>` for a kept lesson. Every value on one line, a blank line between lessons and two between topics.
  - `validate(payload, works) -> dict[str, dict]`: the writer's whole answer `{"topics": [{"topic", "heading"?, "lines": [{"id", "line"}]}]}` turned into `{topic: {"heading": str | None, "lines": {handle: str}}}`, keeping only a heading for a topic that asked for one and lines for lessons marked `write`; a non-string reads as absent; raises `ValueError` when the payload is not an object with a list `topics`.
  - `heading_problem(text: str) -> str | None`: empty, more than one line, spaces at its ends, over `HEADING_LIMIT`, or ending with a period or a colon.
  - `line_problem(text: str, m: Memory) -> str | None`: empty, more than one line, spaces at its ends, over `records.SHORT_LIMIT`, or what `shortcheck.problems` reports against the lesson's claim.
  - `pairs(works, proposed) -> list[tuple[str, Memory, str, str]]`: `(id, lesson, heading, line)` for every lesson that has a line to judge: a proposed one that passed `line_problem`, or a kept one in a topic whose heading is being written; the heading is the proposed one when it passed `heading_problem`, else the kept one; a topic whose proposed heading has a problem, and that keeps none, yields no pair.
  - `decide(works, proposed, verdicts: Mapping[str, Mapping], digest, state) -> tuple[dict, dict, dict[str, int]]`: the new digest, the new state and the counts `headings_written`, `lines_written`, `refused_code`, `refused_check`, `missing`. `verdicts` maps an id to `{"fits": bool, "faithful": bool}`; only exact `true` counts. A written heading is accepted when it has no problem, at least one lesson of its topic has a pair, and `fits` is true for every lesson of its topic that has a pair. A line is accepted when its heading is accepted or kept, it has no problem, and both `fits` and `faithful` are true. An accepted heading and line are stored with their fingerprints (`of`, and for a line `under` equal to the `of` of the heading it stands under). When a heading is rewritten and accepted, every kept line of its topic that is still `fits` and `faithful` under it has its `under` set to the new heading's `of`, so that it keeps printing. A refused or missing heading or line adds one to its try-key; a kept line that is no longer `faithful` under a new heading is removed from the digest. A heading refused leaves the topic's stored lines unprinted by Task 2's rule, and none of the topic's proposed lines is stored. The inputs are not mutated.

- [ ] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_work_asks_for_a_new_topic_whole` | a topic with three ready lessons and no digest: one `Work` with `heading` None, three lessons to write, none kept |
| `test_work_asks_only_for_the_changed_lesson` | a fresh digest, then one lesson's short form changes: one lesson to write, the heading kept, the others kept with their texts |
| `test_work_asks_for_a_heading_when_the_topic_changed` | a lesson joined: `heading` None, the newcomer to write, the others kept |
| `test_nothing_to_ask_gives_no_work` | a fresh digest: `[]` |
| `test_tries_are_respected` | a heading whose try-key counts two is not asked for, and its topic is left out when nothing else is needed; a line likewise |
| `test_blocks_text` | the exact text for one topic with a kept heading, one lesson to write and one kept |
| `test_validate_keeps_only_what_was_asked` | an answer with a heading for a topic that keeps its own, and a line for a kept lesson, drops both; a non-list `topics` raises |
| `test_problems` | each problem of a heading and of a line; a line that drops the claim's `may` has a problem |
| `test_decide_stores_what_passed` | all accepted: the digest holds the heading and lines with fingerprints that make Task 2's `heading` and `line` return them |
| `test_a_refused_line_is_tried_twice_then_left` | `faithful` false: not stored, one try; a second refusal: `work` no longer asks for it |
| `test_a_heading_that_does_not_fit_stores_nothing_for_the_topic` | `fits` false for one lesson: no heading, no line stored, the heading's try counted, the lines' not |
| `test_a_kept_line_unfaithful_under_a_new_heading_is_removed` | then `work` asks for it at the next run |
| `test_a_kept_line_still_prints_under_a_rewritten_heading` | a lesson joins a digested topic; the heading is rewritten and accepted, the kept lines judged faithful: `digest.line` returns each kept line again, and `work` asks for nothing more |
| `test_a_given_up_heading_asks_for_nothing` | the heading's try-key counts two: the topic gives no work, although its lessons have no line |
| `test_a_heading_without_any_pair_is_not_accepted` | every proposed line of a new topic has a code problem: no heading stored, the heading's try counted |
| `test_the_limit_of_lessons_keeps_topics_whole` | topics of 20, 15 and 5 lessons to write: the first two are asked (35 passes the limit only after the second is added), the third waits |
| `test_decide_does_not_mutate_its_inputs` | deep copies compare equal |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run `test_digest.py`, then the whole suite**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/engine/digest.py plugins/memory/engine/tests/test_digest.py
git commit -m "feat(memory): what the digest step asks for, checks and keeps"
```

---

### Task 5: The step in the pass (C87, C91, C92)

**Files:**
- Modify: `plugins/memory/bin/mem-corroborate`
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py` (its fake `claude` chooses its answer by the end of the output file's name: name this step's two outputs `digest-write.json` and `digest-check.json`, which no existing rule of the fake matches, add their modes, and make the fake save the text it was given for these two, so a test can read what the writer was asked)

**Interfaces:**
- Consumes: `digest.py` of Tasks 2 and 4; in this file, called as they are: `_ask`, `PROPOSE_MODEL`, `CHECK_MODEL`, the run lock, the budget and cost accounting, the way `fill_auto` and `reword_auto` find the global lessons and the data folder. Read `reword_auto` and its locked body from their first line to their last before writing: the new step follows their order and failure handling in code of its own.
- Produces:
  - `DIGEST_BRIEF` and `DIGEST_CHECK_BRIEF`: the texts below, verbatim.
  - `digest_auto(claude, budget, *, apply: bool = True, sheet: Path | None = None) -> dict`: one run, never raising. Result keys: `topics` (works asked), `headings_written`, `lines_written`, `refused_code`, `refused_check`, `missing`, `cost`, `stopped`. Order: take the lock; read the global lessons, the digest and the state (`digest-attempts.json` beside the fill's state file); `digest.work`; stop with `stopped` when there is no work, or when the same work failed three runs in a row (a fingerprint over the try-keys asked); one writing session over `digest.blocks`; `digest.validate`; one checking session over `digest.pairs`, none when there is no pair; `digest.decide`; write the digest file and the state. A session that fails or whose answer cannot be read changes neither file except `failures`, and sets `stopped`. The records are never written.
  - `apply=False` writes neither the digest nor the state; both sessions still run. `sheet`, when given, receives a Markdown table, one row per lesson judged: topic, heading, id, claim, short form, line, outcome, the checker's reason; refused inside a git repository as the rewording's sheet is.
  - The subcommand `mem-corroborate digest [--dry-run] [--sheet PATH]`, built as `reword` is, printing its result as JSON.

```text
DIGEST_BRIEF = """You write, for groups of lessons that coding sessions wrote down, the text that later sessions read at their start. The lessons of one topic are printed together under one heading, so the heading says once what they share and each lesson's line does not repeat it.
Read {topics}: one block per topic, with its name, a heading (a text to keep, or the word write), and its lessons. Each lesson has an id, a claim, sometimes a context, its short form, and the word write or keep; a kept lesson shows the line it already has, for you to read and not to change.
For a topic whose heading says write, write: heading: at most 80 characters, the situation in which the topic's lessons apply, as a clause a line can follow ("when briefing or reading a subagent"), true of every lesson under it, holding no advice, ending without a period, and naming no project, person or company.
For each lesson that says write, write: line: one sentence of at most 120 characters (aim for 100) that reads on from the heading. It does not repeat the situation the heading names; it says what may be worth doing, and why when the claim says why, drawn from the claim and not from the short form. It is a suggestion and never stronger than the claim: keep the claim's hedge (may, once, sometimes, untested, provisional); if it is too long, drop alternatives and detail first, never the hedge. Name the action as a thing or an -ing form ("quoting the source line may catch errors"), not as a command to the reader, unless the claim itself is a command. If the claim applies in a narrower situation than the heading, say so in the line. Say "the user" and never "the owner", name no project, person or company, and add nothing the claim does not say. An id is copied whole.
Write {out} as JSON: {{"topics": [{{"topic": "example", "heading": "...", "lines": [{{"id": "g:example", "line": "..."}}]}}]}}
Leave "heading" out for a topic whose heading is kept, and write lines only for lessons that say write. Write nothing else and use no other tool.
"""

DIGEST_CHECK_BRIEF = """You check texts that are loaded into every later coding session. The lessons of one topic are printed under a heading that names a situation, each as a line that reads on from it. Another writer made the headings and lines; it sometimes makes a line stronger or wider than its lesson, so say true only when you are sure.
Read {pairs}: one block per lesson, with an id, a claim, sometimes a context that says when the lesson applies, the heading of its topic, and its line.
For each block answer in this order:
- reason: one sentence comparing what the claim asks, and when, with what the heading and the line ask together, and when.
- fits: true only if the situation the claim is about lies inside the situation the heading names.
- faithful: true only if the heading and the line, read together, ask for nothing the claim does not, in no wider a situation than the claim's (when the heading is wider, the line must narrow it), with no more certainty (a "may" or "once" in the claim is still there), as a suggestion and not an order unless the claim is an order, and name no project, person or company. A line that leaves out examples or alternatives is still faithful; one that adds a reason or a condition the claim does not state is not.
Write {out} as JSON: {{"verdicts": [{{"id": "g:example", "reason": "...", "fits": true, "faithful": true}}]}}
One entry per block. Write nothing else and use no other tool.
"""
```

- [ ] **Step 1: Write the failing tests**

Drive the step as the rewording's tests in `test_mem_corroborate.py` drive `reword`.

| Test | Asserts |
|---|---|
| `test_digest_writes_a_topic_and_session_start_prints_it` | three global lessons under one topic; the fake writer and checker accept: the digest file holds the heading and three lines; `mem rules --layout digest` prints them; every record file is byte-identical |
| `test_a_refused_line_falls_back_and_is_tried_twice` | the checker says `faithful` false for one lesson in two runs: its short form is printed, the others' lines are; a third run asks for nothing |
| `test_a_reworded_lesson_gets_a_new_line_and_the_rest_keep_theirs` | after the first run, change one lesson's short form with `mem memory edit --short ... --user-read`: the next run's writer is asked for one line only (assert on what the fake received), and the other stored texts are unchanged |
| `test_an_unusable_answer_changes_nothing_and_three_in_a_row_wait` | as the rewording's test |
| `test_dry_run_writes_the_sheet_and_nothing_else` | the digest file and the state are absent or unchanged, the sheet has one row per lesson judged; `--sheet` inside a git repository is refused before any session |
| `test_digest_respects_the_lock` | `stopped` names the lock, nothing asked |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run `test_mem_corroborate.py`, `test_digest.py`, `test_reword.py`, `test_fill_auto.py`, then the whole suite**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/bin/mem-corroborate plugins/memory/engine/tests/test_mem_corroborate.py
git commit -m "feat(memory): the pass can write a digest per topic, checked as a short form is"
```

---

### Task 6: The option turns the step on (C94)

**Files:**
- Modify: `plugins/memory/bin/mem-corroborate` (`cmd_auto`)
- Test: `plugins/memory/engine/tests/test_mem_corroborate.py`

**Interfaces:**
- Consumes: `digest_auto` of Task 5.
- Produces:
  - In `cmd_auto`, after the rewording and under the same condition on the loaded rules, when `CLAUDE_PLUGIN_OPTION_RULES_LAYOUT` is `"digest"`: `digest_auto(args.claude, budget)` and one log line `{"t", "digest": result, "ms"}`, in a `try` of its own. With any other value nothing runs and no line is written.

- [ ] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_auto_runs_digest_only_with_the_layout` | `CLAUDE_PLUGIN_OPTION_RULES_LAYOUT` unset, `flat` or `grouped`: no `digest` line in the log and no digest file; `digest`: one `digest` line after the others; with the loaded rules off: none |
| `test_a_failure_in_digest_does_not_fail_auto` | `digest_auto` patched to raise: exit 0, the other lines are there |
| `test_auto_without_the_layout_is_as_before` | with the option unset, the log lines and the store after `auto` equal those of a run before this task (the existing test of the rewording's option shows how to compare) |

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run `test_mem_corroborate.py`, then the whole suite, `python3 scripts/validate.py` and `claude plugin validate .`**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory/bin/mem-corroborate plugins/memory/engine/tests/test_mem_corroborate.py
git commit -m "feat(memory): the automatic run writes the digest when rules_layout is digest"
```

---

### Task 7: The gate's automatic half, and the documents (C95)

**Files:**
- Modify: `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md` (under `## [Unreleased]`), `docs/superpowers/specs/2026-11-21-memory-capture-design.md` (the `## Phases` table), `docs/superpowers/plans/2026-11-17-memory-plugin.md` ("Current state and where to resume")
- Modify: this file (`## Results`)

- [ ] **Step 1: Copy the store and isolate it, not the login**

As Task 6 of [the rewording plan](2026-11-23-memory-auto-reword.md) did: `HOME` stays; a copy of the owner's store folder under `mktemp -d`; `MEM_STORE`, `MEM_MEMORIES`, `MEM_DATA`, `MEM_PROJECT` and `XDG_STATE_HOME` pointing into it, `MEM_SETTLE_AUTO` unset; the resolved folders checked before any model call; checksums of the owner's real memory folders and of the plugin's real state folder before and after.

- [ ] **Step 2: Run the step once without applying**

Run: `plugins/memory/bin/mem-corroborate digest --dry-run --sheet <sheet>` with a real `claude` and a budget per session of 0.40 USD. `<sheet>` is `digest-gate-2026-11-24.md` in the folder that holds the owner's real store folder, outside every repository.

- [ ] **Step 3: Run it once applying, on the copy, and measure the block**

Run the step without `--dry-run` on the copy, then `mem rules --layout grouped` and `mem rules --layout digest` there: record the characters of each block and the number of lessons under a fresh heading. Nothing of the owner's real folders is involved.

- [ ] **Step 4: Record the figures**

In `## Results`: topics asked, headings written and refused, lines asked, refused by code, refused by the checking session, accepted, their share of the lines that passed the code check, the cost of each run, the characters of the two blocks, and whether the automatic half of C95 passed (at least 80% of the lines that passed the code check accepted; every heading with at least two lessons accepted). No text of a lesson, heading or line.

- [ ] **Step 5: Write the documents**

README: the third value of `rules_layout` and what it prints, the step and its subcommand, the new limits, the gate's figures and that the owner's reading is open. Changelog: lines for users. The resume section: where this plan stands. One home per fact; no line numbers.

- [ ] **Step 6: Run `python3 scripts/validate.py`, `claude plugin validate .`, `python3 scripts/port.py --check`, and the whole suite**

- [ ] **Step 7: Commit**

```bash
git add plugins/memory/README.md plugins/memory/CHANGELOG.md docs/superpowers
git commit -m "docs(memory): the digest per topic, its gate's first half and where it stands"
```

---

## Results

Filled by Task 7.
