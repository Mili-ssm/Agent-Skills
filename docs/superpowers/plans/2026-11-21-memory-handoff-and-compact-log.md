# Memory handoff block and compaction log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a compaction the agent resumes from a handoff block it wrote itself, a hook checks that block against the files and speaks only on a mismatch, and every compaction leaves one log line that the usage script turns into outcome metrics.

**Architecture:** `PreCompact` prints the instruction that makes the summary carry a fixed handoff block. A new `PostCompact` hook runs `mem compact-log --hook`, which parses `compact_summary` with a new pure module `handoff.py`, appends one line to the hook log and, on a mismatch, writes a one-shot state file. `mem session-index --hook` prints that file's lines after a compaction and deletes it. No model runs in any hook.

**Tech Stack:** Python 3 standard library (the engine under `plugins/memory/engine/`), bash hook scripts, pytest through `uv`.

**Spec:** [the learning loop study](../../studies/2026-11-21-memory-learning-loop.md), proposals L1 and L2, and ADR 0023 `## Review 2026-11-21` (kill criteria). L3 to L5 are not in this plan.

## Global Constraints

- Every hook script exits 0 whatever happens and prints nothing on failure; `mem compact-log` returns 0 on any input, including empty or invalid JSON.
- The hook log (`hooks/log.jsonl` in the data folder) holds no text and no path: counts, booleans and field names only.
- A hook stays under 0.5 s; no hook starts `git` or a model.
- Text injected after a compaction: nothing when the handoff agrees with the files; at most 300 characters otherwise.
- This repository is public: no home path, private repository name or note title in code, tests or docs.
- Changes under `plugins/memory/` add a line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`; the version does not change.
- Engine tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`. Before every commit: `python3 scripts/validate.py` and `claude plugin validate .`.
- The `PreCompact` text keeps the sentence that makes summaries list items "not yet recorded" (12 of 13 summaries carried them before this change).

## Review Focus

- A summary with no handoff block (an older session, a model that ignored the instruction): one line asks for the task, state and next step; no crash, the log line says `"handoff": []`.
- A handoff whose `plan:` value is prose, a quoted path, a path with spaces or a path outside the project: treated as named; "does not exist" only when the cleaned value resolves to no file under the hook's `cwd`.
- `compact_summary` missing, not a string, or several megabytes long: exit 0, a log line with `"chars"` only, under 0.5 s.
- A `session_id` with characters outside `[A-Za-z0-9_-]`: no state file is written or read.
- Two compactions in a row without a session-index call between them: the second state file replaces the first; a state file older than one day is ignored and deleted.

---

### Task 1: Spike: order of the compaction events

No code enters the repository; the result is written into this plan's `## Results`.

**Files:**
- Create (throwaway, git-ignored): `target/compact-spike/` with a plugin whose `PreCompact`, `PostCompact` and `SessionStart` hooks append a timestamped line, their input's top-level keys and their own name to one file, and whose `PostCompact` and `SessionStart` each print a distinct marker word.
- Modify: this file, `## Results`.

- [ ] **Step 1:** Build the throwaway plugin and run one session with `claude --plugin-dir target/compact-spike`, compact it once (`/compact`; try print mode first, an interactive session if print mode cannot compact).
- [ ] **Step 2:** Record in `## Results`: the order of the three events; the keys `PostCompact` receives (expected: `session_id`, `cwd`, `trigger`, `compact_summary`); whether the model can quote the marker printed by `PostCompact`, and the one printed by `SessionStart` with source `compact`.
- [ ] **Step 3:** Apply the decision rule and record the choice: `PostCompact` before `SessionStart` → Task 4 as written. `SessionStart` first, and `PostCompact`'s marker reaches the model → Task 4 changes to "`post-compact.sh` prints the lines itself", no state file. Neither → stop and report to the owner.
- [ ] **Step 4:** Delete `target/compact-spike/`. Commit this file: `docs(plan): compaction event order (spike)`.

### Task 2: `handoff.py`: parse the block and find mismatches

**Files:**
- Create: `plugins/memory/engine/handoff.py`
- Test: `plugins/memory/engine/tests/test_handoff.py`

**Interfaces:**
- Produces:
  - `FIELDS: tuple[str, ...] = ("task", "state", "next", "verified", "unverified", "plan")`
  - `INSTRUCTION: str` — the `PreCompact` text (Task 3 copies it into the shell script; a test keeps them equal).
  - `parse(summary: str) -> dict[str, str]` — the fields found after the last line that is exactly `HANDOFF` (case-sensitive, surrounding `*`, `#`, `:` and spaces ignored); each field is a line `name: value`; a missing field is absent from the result; no block → `{}`.
  - `unrecorded(summary: str) -> int` — the number of lines that contain `not yet recorded` (case-insensitive).
  - `mismatches(found: dict[str, str], cwd: Path) -> list[str]` — the lines to show the agent, each under 150 characters, at most two.

`INSTRUCTION`, exact copy:

```
End the summary with this block, one line per field, so the next context resumes from it:
HANDOFF
task: <the task in progress, in one sentence>
state: <what is done>
next: <the next step>
verified: <what a check or the owner confirmed>
unverified: <what is claimed but not checked>
plan: <path of the active plan file, or "no plan">
Before the block, list every decision, constraint, pitfall or finding of this session that was not yet recorded with mem remember, one per line, each line starting with "not yet recorded:", so that the next context can record them.
```

Mismatch rules, in this order:

| Condition | Line |
|---|---|
| `found` is empty | `The summary has no handoff block: state the task, its state and the next step before you continue.` |
| `plan` names a file (not `no plan`, `none` or empty, after stripping quotes and backticks) that does not exist under `cwd` | `The handoff names a plan file that does not exist: <value, cut to 80 characters>. Find the plan before you continue.` |
| `plan` exists, contains at least one `- [x]` and no `- [ ]`, and `next` is not empty, `none` or `done` | `Every task of the plan the handoff names is ticked, but the handoff has a next step: check the plan against the work.` |

A `plan` value that resolves outside `cwd` (absolute path elsewhere, `..`) is never read: no mismatch.

- [ ] **Step 1: Write the failing tests** in `test_handoff.py`:

```python
import handoff
from pathlib import Path

BLOCK = "Earlier text\nnot yet recorded: the cache key ignores the locale\nHANDOFF\ntask: add the retry\nstate: tests written\nnext: implement backoff\nverified: unit tests pass\nunverified: staging\nplan: docs/plans/p.md\n"

def test_parse_reads_the_six_fields():
    assert handoff.parse(BLOCK) == {"task": "add the retry", "state": "tests written", "next": "implement backoff",
                                    "verified": "unit tests pass", "unverified": "staging", "plan": "docs/plans/p.md"}

def test_parse_tolerates_markdown_around_the_marker_and_takes_the_last_block():
    assert handoff.parse("HANDOFF\ntask: old\n\n## **HANDOFF**:\ntask: new\n") == {"task": "new"}

def test_parse_without_a_block_is_empty():
    assert handoff.parse("a summary that mentions handoff in prose") == {}
    assert handoff.parse("") == {}

def test_unrecorded_counts_lines():
    assert handoff.unrecorded(BLOCK) == 1
    assert handoff.unrecorded("Not Yet Recorded: a\nx\nnot yet recorded: b") == 2

def test_no_block_gives_one_line(tmp_path):
    assert handoff.mismatches({}, tmp_path) == [
        "The summary has no handoff block: state the task, its state and the next step before you continue."]

def test_a_plan_that_exists_with_open_tasks_gives_nothing(tmp_path):
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "p.md").write_text("- [x] a\n- [ ] b\n")
    assert handoff.mismatches({"plan": "`docs/p.md`", "next": "b"}, tmp_path) == []

def test_a_missing_plan_is_named(tmp_path):
    lines = handoff.mismatches({"plan": "docs/gone.md", "next": "b"}, tmp_path)
    assert len(lines) == 1 and "does not exist: docs/gone.md" in lines[0]

def test_no_plan_gives_nothing(tmp_path):
    for value in ("no plan", "None", '"no plan"', ""):
        assert handoff.mismatches({"plan": value, "next": "b"}, tmp_path) == []

def test_a_fully_ticked_plan_with_a_next_step(tmp_path):
    (tmp_path / "p.md").write_text("- [x] a\n- [x] b\n")
    assert len(handoff.mismatches({"plan": "p.md", "next": "write c"}, tmp_path)) == 1
    assert handoff.mismatches({"plan": "p.md", "next": "none"}, tmp_path) == []

def test_a_plan_outside_the_project_is_never_read(tmp_path):
    assert handoff.mismatches({"plan": "../../etc/passwd", "next": "b"}, tmp_path) == []
    assert handoff.mismatches({"plan": "/etc/hostname", "next": "b"}, tmp_path) == []

def test_lines_are_short(tmp_path):
    lines = handoff.mismatches({"plan": "x" * 500, "next": "b"}, tmp_path)
    assert all(len(line) < 150 for line in lines)
```

- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_handoff.py -q`. Expected: FAIL, `No module named 'handoff'`.
- [ ] **Step 3:** Implement `handoff.py` with the interface above. Reading a plan file: at most 1 MB, errors ignored, any `OSError` → no mismatch.
- [ ] **Step 4:** Run the same command. Expected: 11 passed.
- [ ] **Step 5:** Commit: `feat(memory): parse the handoff block of a compaction summary`.

### Task 3: `mem compact-log` and the two hooks

**Files:**
- Modify: `plugins/memory/engine/mem.py` (a `cmd_compact_log` beside `cmd_session_index`, its parser beside `session-index`, the command name in the list near the top of the file)
- Create: `plugins/memory/hooks/post-compact.sh`
- Modify: `plugins/memory/hooks/pre-compact.sh`, `plugins/memory/hooks/hooks.json`
- Test: `plugins/memory/engine/tests/test_compact_log.py`, `plugins/memory/engine/tests/test_plugin_shell.py`

**Interfaces:**
- Consumes: `handoff.parse`, `handoff.unrecorded`, `handoff.mismatches`, `handoff.FIELDS`, `handoff.INSTRUCTION`; `_hook_input()`, `_log_hook()`, `data_dir()` of `mem.py`.
- Produces:
  - `mem compact-log --hook`: reads the hook's JSON from standard input, prints nothing, returns 0.
  - Log line: `{"hook": "post-compact", "trigger": <str or null>, "chars": <int>, "handoff": [<names of the fields present, in FIELDS order>], "plan_named": <bool>, "unrecorded": <int>, "mismatches": <int>, "ms": <int>}`.
  - State file, written only when `mismatches > 0` and the session id matches `^[A-Za-z0-9_-]{1,64}$`: `<data folder>/handoff/<session_id>.json` holding `{"t": <epoch seconds>, "lines": [<str>, ...]}`. With no mismatch an existing file for that session is deleted.
  - `handoff_state_path(data: Path, session_id: str) -> Path | None` in `mem.py`, used by Task 4.

- [ ] **Step 1: Write the failing tests** in `test_compact_log.py`, running `bin/mem compact-log --hook` as a subprocess with `MEM_DATA` set to a temporary folder, the way `test_plugin_shell.py` runs `session-index`:
  - `test_logs_one_line_without_text`: input with the `BLOCK` summary of Task 2, `cwd` a folder where `docs/plans/p.md` holds `- [ ] a`. Assert exit 0, empty stdout, and the last hook-log line equals, ignoring `t` and `ms`: `{"hook": "post-compact", "trigger": "auto", "chars": len(BLOCK), "handoff": ["task", "state", "next", "verified", "unverified", "plan"], "plan_named": True, "unrecorded": 1, "mismatches": 0}`; the raw log line contains neither `retry` nor `docs/plans`; no file under `handoff/`.
  - `test_a_mismatch_writes_the_state_file`: the same with no plan file. Assert `handoff/<session_id>.json` holds one line that contains `does not exist`, and the log line has `"mismatches": 1`.
  - `test_agreement_deletes_an_old_state_file`.
  - `test_bad_input_is_silent` (parametrized: empty stdin, `not json`, `{}`, `{"compact_summary": 5}`, a `session_id` of `../x` with a summary that has no block): exit 0, empty stdout and stderr, no file outside `hooks/` in the data folder.
  - `test_a_large_summary_stays_fast`: a 5 MB summary, under 2 s wall time for the subprocess.
- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_compact_log.py -q`. Expected: FAIL, `invalid choice: 'compact-log'`.
- [ ] **Step 3:** Implement `cmd_compact_log(args) -> int` and `handoff_state_path`; the whole body inside one `try`, as `cmd_session_index` does. Only the first 1,000,000 characters of the summary are parsed; `chars` is the full length.
- [ ] **Step 4:** Run the command of Step 2. Expected: all pass.
- [ ] **Step 5: Shell tests** in `test_plugin_shell.py`: add `post-compact.sh` to the parametrized list of executable scripts; `test_hooks_json_names_the_scripts` expects a `PostCompact` entry with timeout 5; replace `test_pre_compact_prints_its_line` with a test that the script's output equals `handoff.INSTRUCTION` plus a newline; `test_post_compact_hook_without_uv_is_silent` on the model of `test_session_index_hook_without_uv_is_silent`. Run them: FAIL.
- [ ] **Step 6:** Write `post-compact.sh` on the model of `signal.sh` (pass the options on, `timeout 4` around `mem compact-log --hook`, silent, exit 0); set `pre-compact.sh` to print the instruction with one quoted here-document and no interpreter; add the `PostCompact` group to `hooks.json` and extend its `description`. `git add` the new script with mode `100755`.
- [ ] **Step 7:** Run the whole engine suite. Expected: all pass (1248 passed and 4 skipped before this plan, plus the new tests).
- [ ] **Step 8:** Commit: `feat(memory): handoff instruction before a compaction and a log line after it`.

### Task 4: The mismatch lines open the context after a compaction

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_session_index`)
- Test: `plugins/memory/engine/tests/test_session_index.py`

**Interfaces:**
- Consumes: `handoff_state_path(data, session_id)` and the state file of Task 3.
- Produces: with `--hook`, a hook input whose `source` is `compact` and a state file for its `session_id` not older than 86,400 s, `mem session-index` appends the file's lines (joined, cut to 300 characters) after the index text, deletes the file, and adds `"handoff_lines": <int>` to its log line. Any other source leaves the file alone.

- [ ] **Step 1: Write the failing tests:** `test_compact_source_prints_and_deletes_the_handoff_lines`; `test_startup_source_ignores_the_state_file` (file still there); `test_a_state_file_older_than_a_day_is_deleted_unread`; `test_a_broken_state_file_is_ignored` (invalid JSON, `lines` not a list: the index prints as before, exit 0); `test_the_lines_are_cut_to_300_characters`.
- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_session_index.py -q`. Expected: the five new tests FAIL.
- [ ] **Step 3:** Implement inside `cmd_session_index`, in its own `try` so that a failure leaves the index text intact.
- [ ] **Step 4:** Run the whole engine suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): show handoff mismatches after a compaction`.

### Task 5: Metrics in the usage script, and the docs

**Files:**
- Modify: `docs/studies/scripts/memory_usage.py`, `plugins/memory/README.md` (the hooks it registers), `plugins/memory/CHANGELOG.md`, `docs/superpowers/plans/2026-11-17-memory-plugin.md` (state table: `PostCompact` registered; stage 9 points to the study), `docs/studies/2026-11-21-memory-learning-loop.md` (L1 and L2 status `done`, a link to this plan)

**Interfaces:**
- Consumes: the `post-compact` and `session-index` lines of the hook log; the usage log's `search` lines (`results`) and `show` lines (`paths`).
- Produces: a section `== outcome metrics ==` printed by the script:
  - M2 `sessions with web research before any mem search: N / sessions with web research` (a `WebSearch` or `WebFetch` call, or an `Agent` call whose `subagent_type` ends in `researcher`, earlier than the session's first `mem search`).
  - M3 `searches followed within 30 minutes by mem show of a returned record: N / searches` (usage log; the data folder from `MEM_DATA`, else `$XDG_STATE_HOME/agent-memory`, else `~/.local/state/agent-memory`).
  - M5 `compactions: N; with a handoff block: N; with all six fields: N; unrecorded items: N; mismatch lines shown: N` (hook log, same window).
  - M8 `characters injected by session-index: median N, max N per call`.

- [ ] **Step 1:** Add the four metrics; a missing log prints `no log` for its metric and the script still exits 0.
- [ ] **Step 2:** Run `python3 docs/studies/scripts/memory_usage.py 2026-11-17 2026-11-20`. Expected: the earlier figures unchanged (13 / 16 sessions with a search, 12 summaries with unrecorded items) and the four new lines; M5 reports `compactions: 0` for that window, because no `post-compact` line existed yet.
- [ ] **Step 3:** Update the four documents. The CHANGELOG line, for users: after a compaction the summary ends with a handoff block; the agent is told only when that block is missing or disagrees with the plan file; nothing to migrate.
- [ ] **Step 4:** Run `python3 scripts/validate.py` and `claude plugin validate .`. Expected: both pass.
- [ ] **Step 5:** Commit: `docs(memory): outcome metrics in the usage script; handoff and compaction log documented`.

## Results

Empty until Task 1.
