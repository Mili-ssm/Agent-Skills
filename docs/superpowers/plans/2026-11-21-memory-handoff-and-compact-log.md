# Memory handoff block and compaction log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a compaction the agent resumes from a handoff block it wrote itself, a hook checks that block against the files and speaks only on a mismatch, and every compaction leaves one log line that the usage script turns into outcome metrics.

**Architecture:** `PreCompact` prints the instruction that makes the summary carry a fixed handoff block. A new `PostCompact` hook runs `mem compact-log --hook`, which parses `compact_summary` with a new pure module `handoff.py`, appends one line to the hook log and, on a mismatch, prints the lines, which reach the agent as the hook's output (Results, Task 1). No model runs in any hook.

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
- A `session_id` with characters outside `[A-Za-z0-9_-]`: logged as `null`.

---

### Task 1: Spike: order of the compaction events

No code enters the repository; the result is written into this plan's `## Results`.

**Files:**
- Create (throwaway, git-ignored): `target/compact-spike/` with a plugin whose `PreCompact`, `PostCompact` and `SessionStart` hooks append a timestamped line, their input's top-level keys and their own name to one file, and whose `PostCompact` and `SessionStart` each print a distinct marker word.
- Modify: this file, `## Results`.

- [x] **Step 1:** Build the throwaway plugin, whose `PreCompact` prints the `INSTRUCTION` of Task 2, and run sessions with `claude --plugin-dir target/compact-spike` until three compactions happened: `/compact` (try print mode first, an interactive session if print mode cannot compact) and, if feasible, one automatic compaction. Save each `compact_summary` to the scratchpad, outside the repository.
- [x] **Step 2:** Record in `## Results`: the order of the three events; the keys `PostCompact` receives (expected: `session_id`, `cwd`, `trigger`, `compact_summary`); whether the model can quote the marker printed by `PostCompact`, and the one printed by `SessionStart` with source `compact`; for each summary, whether the block is there and how its marker and fields are written (bare, bold, list items, under a heading, in a code fence); whether the "not yet recorded:" lines are there.
- [x] **Step 3:** Apply the decision rule and record the choice: `PostCompact` before `SessionStart` → Task 4 as written. `SessionStart` first, and `PostCompact`'s marker reaches the model → Task 4 changes to "`post-compact.sh` prints the lines itself", no state file. Neither → Task 4 is dropped, Tasks 2, 3 and 5 still ship (the log and the metrics need no delivery), and the owner is told. If a summary writes the block in a shape Task 2's `parse` rules do not cover, add that shape to Task 2 as a test, with the summary's text replaced by invented text.
- [x] **Step 4:** Delete `target/compact-spike/`. Commit this file: `docs(plan): compaction event order (spike)`.

### Task 2: `handoff.py`: parse the block and find mismatches

**Files:**
- Create: `plugins/memory/engine/handoff.py`
- Test: `plugins/memory/engine/tests/test_handoff.py`

**Interfaces:**
- Produces:
  - `FIELDS: tuple[str, ...] = ("task", "state", "next", "verified", "unverified", "plan")`
  - `INSTRUCTION: str` — the `PreCompact` text (Task 3 copies it into the shell script; a test keeps them equal).
  - `parse(summary: str) -> dict[str, str]` — the fields found after the last marker line: a line that is the word `handoff` in any case once leading and trailing `#`, `*`, `-`, `>`, `` ` ``, `:` and spaces are removed. Each field is a line `name: value` where the name, in any case, may be preceded by `-`, `*`, `>` and spaces and wrapped in `**`; names are returned in lower case; a code fence line is skipped; a missing field is absent from the result; no marker → `{}`. Reason: a strict parser would report "no handoff block" for a model that complied in Markdown, and the kill criteria would then fire for the wrong cause.
  - `has_marker(summary: str) -> bool` — the text contains `handoff` in any case, anywhere.
  - `unrecorded(summary: str) -> int` — the number of unrecorded items, in both shapes seen in real summaries: a line that starts with `not yet recorded:` (case-insensitive, after leading `-`, `*` and spaces) and has text after the colon counts 1; such a line with nothing after the colon is a header, and each following line that starts with `-` or `*` counts 1, until the first line that does not.
  - `mismatches(found: dict[str, str], cwd: Path) -> list[str]` — the lines to show the agent, each under 150 characters, at most one today.

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
| `plan` holds a token that ends in `.md` (the first one, after stripping quotes, backticks and brackets), and that path is not a file under the project root | `The handoff names a plan file that does not exist: <token, cut to 60 characters>. Find the plan before you continue.` |

The project root is the nearest ancestor of `cwd`, `cwd` included, that holds an entry named `.git` (file or folder; `git` is never run, and `records.project_root` is not used because it runs `git`), else `cwd`. A `plan` value with no `.md` token (`no plan`, `none`, prose) names nothing: no mismatch. A token that resolves outside the project root (absolute path elsewhere, `..`) is never looked up: no mismatch.

Dropped after the pre-mortem: a rule for "every task of the plan is ticked but the handoff has a next step". The plan template's own header holds a literal `- [x]`, and a finished plan's next step is usually "open the pull request", so the rule would be silent or wrong. It returns only if the compaction log shows a need.

- [x] **Step 1: Write the failing tests** in `test_handoff.py`:

```python
import handoff
from pathlib import Path

BLOCK = "Earlier text\nnot yet recorded: the cache key ignores the locale\nHANDOFF\ntask: add the retry\nstate: tests written\nnext: implement backoff\nverified: unit tests pass\nunverified: staging\nplan: docs/plans/p.md\n"

def test_parse_reads_the_six_fields():
    assert handoff.parse(BLOCK) == {"task": "add the retry", "state": "tests written", "next": "implement backoff",
                                    "verified": "unit tests pass", "unverified": "staging", "plan": "docs/plans/p.md"}

def test_parse_tolerates_markdown_around_the_marker_and_takes_the_last_block():
    assert handoff.parse("HANDOFF\ntask: old\n\n## **HANDOFF**:\ntask: new\n") == {"task": "new"}

def test_parse_tolerates_markdown_fields():
    text = "## Handoff\n```\n- **Task:** add the retry\n* state: tests written\n> Next: implement backoff\n**Plan**: `docs/p.md`\n```\n"
    assert handoff.parse(text) == {"task": "add the retry", "state": "tests written", "next": "implement backoff", "plan": "`docs/p.md`"}

def test_has_marker():
    assert handoff.has_marker("the Handoff follows") and not handoff.has_marker("nothing here")

def test_parse_without_a_block_is_empty():
    assert handoff.parse("a summary that mentions handoff in prose") == {}
    assert handoff.parse("") == {}

def test_unrecorded_counts_lines():
    assert handoff.unrecorded(BLOCK) == 1
    assert handoff.unrecorded("Not Yet Recorded: a\nx\n- not yet recorded: b") == 2

def test_unrecorded_counts_a_list_under_a_header():
    assert handoff.unrecorded("not yet recorded:\n- a\n- b\n* c\n\nHANDOFF\ntask: t\n- not an item\n") == 3
    assert handoff.unrecorded("nothing was not yet recorded here") == 0

def test_no_block_gives_one_line(tmp_path):
    assert handoff.mismatches({}, tmp_path) == [
        "The summary has no handoff block: state the task, its state and the next step before you continue."]

def test_a_plan_that_exists_with_open_tasks_gives_nothing(tmp_path):
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "p.md").write_text("- [x] a\n- [x] b\n")
    assert handoff.mismatches({"plan": "`docs/p.md`", "next": "b"}, tmp_path) == []

def test_a_missing_plan_is_named(tmp_path):
    lines = handoff.mismatches({"plan": "docs/gone.md", "next": "b"}, tmp_path)
    assert len(lines) == 1 and "does not exist: docs/gone.md" in lines[0]

def test_no_plan_gives_nothing(tmp_path):
    for value in ("no plan", "None", '"no plan"', "", "the plan we agreed on"):
        assert handoff.mismatches({"plan": value, "next": "b"}, tmp_path) == []

def test_a_path_inside_prose_is_found_from_a_subdirectory_of_the_project(tmp_path):
    (tmp_path / ".git").mkdir(); (tmp_path / "docs").mkdir(); (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "p.md").write_text("- [x] a\n")
    assert handoff.mismatches({"plan": "docs/p.md (Task 3 of 5)"}, tmp_path / "src") == []
    lines = handoff.mismatches({"plan": "see docs/gone.md, Task 3"}, tmp_path / "src")
    assert len(lines) == 1 and "does not exist: docs/gone.md" in lines[0]

def test_a_plan_outside_the_project_is_never_read(tmp_path):
    assert handoff.mismatches({"plan": "../../etc/passwd", "next": "b"}, tmp_path) == []
    assert handoff.mismatches({"plan": "/etc/hostname", "next": "b"}, tmp_path) == []

def test_lines_are_short(tmp_path):
    lines = handoff.mismatches({"plan": "x" * 500 + ".md", "next": "b"}, tmp_path)
    assert all(len(line) < 150 for line in lines)
```

- [x] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_handoff.py -q`. Expected: FAIL, `No module named 'handoff'`.
- [x] **Step 3:** Implement `handoff.py` with the interface above. Reading a plan file: at most 1 MB, errors ignored, any `OSError` → no mismatch.
- [x] **Step 4:** Run the same command. Expected: 14 passed.
- [x] **Step 5:** Commit: `feat(memory): parse the handoff block of a compaction summary`.

### Task 3: `mem compact-log` and the two hooks

**Files:**
- Modify: `plugins/memory/engine/mem.py` (a `cmd_compact_log` beside `cmd_session_index`, its parser beside `session-index`, the command name in the list near the top of the file)
- Create: `plugins/memory/hooks/post-compact.sh`
- Modify: `plugins/memory/hooks/pre-compact.sh`, `plugins/memory/hooks/hooks.json`
- Test: `plugins/memory/engine/tests/test_compact_log.py`, `plugins/memory/engine/tests/test_plugin_shell.py`

**Interfaces:**
- Consumes: `handoff.parse`, `handoff.has_marker`, `handoff.unrecorded`, `handoff.mismatches`, `handoff.FIELDS`, `handoff.INSTRUCTION`; `_hook_input()`, `_log_hook()`, `data_dir()` of `mem.py`.
- Produces:
  - `mem compact-log --hook`: reads the hook's JSON from standard input, prints the mismatch lines (joined by newlines, cut to 300 characters) or nothing, returns 0.
  - Log line: `{"hook": "post-compact", "trigger": <str or null>, "session": <the session id when it matches the pattern below, else null>, "chars": <int>, "marker": <bool, `handoff.has_marker`>, "handoff": [<names of the fields present, in FIELDS order>], "plan_named": <bool, a `.md` token was found>, "unrecorded": <int>, "mismatches": <int>, "ms": <int>}`. `session` joins this line to the transcript and to the next compaction of the same session; `marker` true with an empty `handoff` means the parser missed a block the model wrote.

- [x] **Step 1: Write the failing tests** in `test_compact_log.py`, running `bin/mem compact-log --hook` as a subprocess with `MEM_DATA` set to a temporary folder, the way `test_plugin_shell.py` runs `session-index`:
  - `test_logs_one_line_without_text`: input with the `BLOCK` summary of Task 2, `cwd` a folder where `docs/plans/p.md` holds `- [x] a`. Assert exit 0, empty stdout, and the last hook-log line equals, ignoring `t` and `ms`: `{"hook": "post-compact", "trigger": "auto", "session": "abc-123", "chars": len(BLOCK), "marker": True, "handoff": ["task", "state", "next", "verified", "unverified", "plan"], "plan_named": True, "unrecorded": 1, "mismatches": 0}`; the raw log line contains neither `retry` nor `docs/plans`. The input's `session_id` is `abc-123`.
  - `test_a_mismatch_is_printed`: the same with no plan file. Assert stdout is one line that contains `does not exist`, under 300 characters, and the log line has `"mismatches": 1`.
  - `test_bad_input_is_silent` (parametrized: empty stdin, `not json`, `{}`, `{"compact_summary": 5}`): exit 0, empty stdout and stderr, no file outside `hooks/` in the data folder. `test_an_unsafe_session_id_is_logged_as_null`: a `session_id` of `../x` gives `"session": null`.
  - `test_a_large_summary_stays_fast`: a 5 MB summary, under 2 s wall time for the subprocess.
- [x] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_compact_log.py -q`. Expected: FAIL, `invalid choice: 'compact-log'`.
- [x] **Step 3:** Implement `cmd_compact_log(args) -> int`; the whole body inside one `try`, as `cmd_session_index` does. Only the first 1,000,000 characters of the summary are parsed; `chars` is the full length.
- [x] **Step 4:** Run the command of Step 2. Expected: all pass.
- [x] **Step 5: Shell tests** in `test_plugin_shell.py`: add `post-compact.sh` to the parametrized list of executable scripts; `test_hooks_json_names_the_scripts` expects a `PostCompact` entry with timeout 5; remove the `PRE_COMPACT` constant and replace `test_pre_compact_prints_its_line` with a test that the script's output equals `handoff.INSTRUCTION` plus a newline; `test_post_compact_hook_without_uv_is_silent` on the model of `test_session_index_hook_without_uv_is_silent`. Run them: FAIL.
- [x] **Step 6:** Write `post-compact.sh` on the model of `signal.sh` (pass the options on, `timeout 4` around `mem compact-log --hook`, its standard output passed through, standard error dropped, exit 0); set `pre-compact.sh` to print the instruction with one quoted here-document and no interpreter; add the `PostCompact` group to `hooks.json` and extend its `description`. `git add` the new script with mode `100755`.
- [x] **Step 7:** Run the whole engine suite. Expected: all pass (1248 passed and 4 skipped before this plan, plus the new tests).
- [x] **Step 8:** Commit: `feat(memory): handoff instruction before a compaction and a log line after it`.

### Task 4: dropped

Dropped by the spike (Results, Task 1): `mem compact-log` prints the mismatch lines itself, so `cmd_session_index` does not change.

### Task 5: Metrics in the usage script, and the docs

**Files:**
- Modify: `docs/studies/scripts/memory_usage.py`, `plugins/memory/README.md` (the hooks it registers), `plugins/memory/CHANGELOG.md`, `docs/superpowers/plans/2026-11-17-memory-plugin.md` (state table: `PostCompact` registered; stage 9 points to the study), `docs/studies/2026-11-21-memory-learning-loop.md` (L1 and L2 status `done`, a link to this plan)

**Interfaces:**
- Consumes: the `post-compact` and `session-index` lines of the hook log; the usage log's `search` lines (`results`) and `show` lines (`paths`).
- Produces: a section `== outcome metrics ==` printed by the script:
  - M2 `sessions with web research before any mem search: N / sessions with web research` (a `WebSearch` or `WebFetch` call, or an `Agent` call whose `subagent_type` ends in `researcher`, earlier than the session's first `mem search`).
  - M3 `searches followed within 30 minutes by mem show of a returned record: N / searches` (usage log; the data folder from `MEM_DATA`, else `$XDG_STATE_HOME/agent-memory`, else `~/.local/state/agent-memory`).
  - M5 `compactions: N; with a handoff block: N; marker without a parsed block: N; with all six fields: N; unrecorded items: N; mismatch lines shown: N; post-compact ms p90: N` (hook log, same window). The script's existing transcript line `summaries with 'not yet recorded'` stays: it is the baseline (12 of 13) that the new instruction must not lower.
  - M8 `characters injected by session-index: median N, max N per call`.

- [x] **Step 1:** Add the four metrics; a missing log prints `no log` for its metric and the script still exits 0.
- [x] **Step 2:** Run `python3 docs/studies/scripts/memory_usage.py 2026-11-17 2026-11-20`. Expected: the earlier figures unchanged (13 / 16 sessions with a search, 12 summaries with unrecorded items) and the four new lines; M5 reports `compactions: 0` for that window, because no `post-compact` line existed yet.
- [x] **Step 3:** Update the four documents. The CHANGELOG line, for users: after a compaction the summary ends with a handoff block; the agent is told only when that block is missing or disagrees with the plan file; nothing to migrate.
- [x] **Step 4:** Run `python3 scripts/validate.py` and `claude plugin validate .`. Expected: both pass.
- [x] **Step 5:** Commit: `docs(memory): outcome metrics in the usage script; handoff and compaction log documented`.

## Results

### Task 1, the spike (2026-11-21)

Three manual compactions (`/compact` in print mode, which can compact) of one Haiku session, in a folder outside any repository, with the throwaway plugin alone.

| Question | Observed |
|---|---|
| Order of the events | `PreCompact`, then `SessionStart` with source `compact`, then `PostCompact`, 3 of 3; the last two 30 to 36 ms apart |
| Keys of `PostCompact` | `compact_summary`, `cwd`, `hook_event_name`, `prompt_id`, `scratchpad_dir`, `session_id`, `transcript_path`, `trigger` |
| Does `PostCompact` output reach the model | Yes: the model quoted it as a line `PostCompact [<command>] completed successfully: <text>` |
| The block | 3 of 3 summaries end with a bare `HANDOFF` line and six bare `name: value` lines; `plan: no plan` where there was none |
| The unrecorded items | 3 of 3 summaries list them, as one line `not yet recorded:` followed by `- ` items, not with the prefix on every line |

Choice, by the rule of Step 3: `SessionStart` runs first and `PostCompact`'s output reaches the model, so `mem compact-log` prints the mismatch lines itself; there is no state file, and Task 4 is dropped. `handoff.unrecorded` counts the list form too (Task 2).

Not observed: an automatic compaction; a model other than Haiku; whether the `SessionStart` marker was quoted (the first reply was cut and no longer matters).
