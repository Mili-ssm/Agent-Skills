# Memory capture trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An offline command turns one session transcript into at most 5 evidence-anchored memory candidates in a local file, and a trial over 10 past transcripts tells whether the owner would keep them.

**Architecture:** A pure module `capture.py` reduces a transcript to a compact extract and validates the model's candidates against it. `bin/mem-capture run` writes the extract and the already-recorded claims into a work folder, runs one tool-restricted `claude -p` session the way `bin/mem-settle` does, validates the JSON it wrote and saves the result. Nothing is written to the store and no hook is registered (phase A of the design).

**Tech Stack:** Python 3 standard library (the engine under `plugins/memory/engine/`), pytest through `uv`, `claude -p`.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md) (decisions C1 to C9), phase A.

## Global Constraints

- Phase A writes nothing to the store, registers no hook and adds no plugin option.
- The model session gets no Bash and no web; hooks are disabled by its settings file; one session per run; default budget 0.25 USD per run, default model `haiku`.
- A candidate is kept only if its `evidence` occurs in the extract (C2), its `signal` is one of `owner_correction`, `failed_then_passed`, `verified_review_finding`, `plan_changed_by_review`, `delegation_failed`, `rework`, `repeated_tool_error`, `decision_with_reason` (C1), its `kind` is `lesson`, `pitfall` or `decision`, and its `reach` is `project` or `general` (C5, C10). At most 5 are kept.
- The extract and the result file hold transcript text: they are written with mode 0600 in folders of mode 0700, never inside a repository, and never committed. No transcript text, project name or home path enters code, tests, docs or commit messages; test fixtures are invented.
- This repository is public: no home path, private repository name or note title.
- Changes under `plugins/memory/` add a line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`; no version change.
- Engine tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`. Before every commit: `python3 scripts/validate.py` and `claude plugin validate .`.

## Review Focus

- A transcript line that is not JSON, an entry with no `message`, a `content` that is a string, a list or missing: skipped or read, never a crash.
- A transcript of hundreds of megabytes: read line by line, memory bounded by the extract cap, not by the file.
- A meta entry, a compaction summary, harness text with no `origin`: left out. A subagent's or peer's report: kept, but as `REPORT`, never as `OWNER`, and never accepted as the evidence of an owner signal.
- The model writes no file, invalid JSON, an object instead of a list, 50 candidates, or evidence that paraphrases: the run ends with a reason, or the candidates are dropped with a reason each; nothing is kept unvalidated.
- An evidence quote that differs from the extract only in whitespace or line breaks: accepted.

---

### Task 1: `capture.py`: the extract and the validation

**Files:**
- Create: `plugins/memory/engine/capture.py`
- Test: `plugins/memory/engine/tests/test_capture.py`

**Interfaces:**
- Produces:
  - `SIGNALS: tuple[str, ...]` and `KINDS: tuple[str, ...]` with the values of Global Constraints.
  - `EXTRACT_LIMIT = 80_000`, `PART_SIZE = 40_000`, `MAX_CANDIDATES = 5`.
  - `parts(text: str, size: int = PART_SIZE) -> list[str]` — the extract split at line boundaries into pieces of at most `size` characters (a longer single line stays whole), so that the model reads each file in one call; `"\n".join(parts(t)) == t`.
  - `counts(extract_text: str) -> dict[str, int]` — the number of lines per kind (`OWNER`, `OWNER ANSWER`, `REPORT`, `AGENT`, `TOOL`, `TOOL ERROR`, `TOOL OK`).
  - `extract(transcript: Path, since_line: int = 0) -> tuple[str, int]` — the extract text and the number of the last line read (1-based; `since_line` lines are skipped). One extract line per kept event, each starting with `[<transcript line number>] `:

    | Event in the transcript | Extract line |
    |---|---|
    | `type` `user` whose `content` is a string or holds `text` blocks, with `origin.kind` `human`; or with no `origin` at all, unless the text starts with `<` (older transcripts carry no `origin`; a leading tag marks harness text). Never `isMeta` or `isCompactSummary` | `OWNER: <text, cut to 2,000 characters>` |
    | `type` `attachment` whose `attachment.type` is `queued_command` with `commandMode` `prompt` and no `isMeta` (what the owner typed while the agent worked); `prompt` a string or text blocks | `OWNER: <text, cut to 2,000>` |
    | `type` `user` with `origin.kind` `task-notification` or `peer` (a subagent's or another agent's report) | `REPORT: <text, cut to 800>` |
    | `type` `assistant`, a `text` block | `AGENT: <text, cut to 1,500>` |
    | a `tool_use` block | `TOOL <name>: <input's "command", else "file_path", else "description", else "", cut to 200>` |
    | a `tool_result` block with `is_error` true | `TOOL ERROR <name of its tool_use>: <content as text, cut to 400>` |
    | a `tool_result` without error whose tool is `AskUserQuestion` | `OWNER ANSWER: <content as text, cut to 800>` |
    | a `tool_result` without error, when the previous result of the same tool name was an error | `TOOL OK <name>` |

    In every line, runs of whitespace (newlines included) become one space. Measured on 25 real transcripts (counts only, 2026-11-21): 204 user entries with `origin.kind` `human`, 318 `task-notification`, 1,013 `peer`, 199 with no `origin`; 186 queued commands in prompt mode; `isSidechain` never true (subagent turns live in a `subagents/` folder, which this trial does not read).

    When the text exceeds `EXTRACT_LIMIT`, the oldest lines are dropped (the cut falls on a line boundary) and the first line becomes `[...] earlier lines left out`.
  - `validate(candidates: object, extract_text: str, recorded: Sequence[str]) -> tuple[list[dict], list[dict]]` — kept and dropped. A dropped item is `{"candidate": <the item>, "reason": <str>}`. Reasons, checked in this order: `not a list` (one dropped item holding the whole value), `not an object`, `kind`, `signal`, `claim length` (outside 20 to 300 characters), `evidence not in the transcript` (the evidence, at least 15 characters, with runs of whitespace collapsed, must occur inside one line of the extract, after that line's `[n] KIND: ` prefix), `evidence is not the owner's words` (the signal is `owner_correction` or `decision_with_reason` and that line is not an `OWNER` or `OWNER ANSWER` line: a subagent's report quoted as the owner would pass the first check), `already recorded` (the claim equals a recorded claim, ignoring case and whitespace), `over the limit` (beyond `MAX_CANDIDATES` kept). A kept item has exactly the keys `kind`, `signal`, `reach`, `claim`, `context`, `evidence` (`context` defaults to `""`, `reach` to `"project"`; another `reach` value is dropped with the reason `reach`, checked after `signal`). `REACHES: tuple[str, ...] = ("project", "general")`.

- [ ] **Step 1: Write the failing tests** in `test_capture.py`, with a helper that writes invented JSONL entries to `tmp_path`:

```python
import json
from pathlib import Path
import capture

def write(tmp_path, entries):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries) + "\n")
    return p

def user(text, kind="human", **kw): return {"type": "user", "message": {"content": text}, **({"origin": {"kind": kind}} if kind else {}), **kw}
def queued(text, mode="prompt", **kw): return {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": mode, "prompt": text, **kw}}
def agent(*blocks, **kw): return {"type": "assistant", "message": {"content": list(blocks)}, **kw}
def text(t): return {"type": "text", "text": t}
def use(i, name, **inp): return {"type": "tool_use", "id": i, "name": name, "input": inp}
def result(i, content, err=False): return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": content, "is_error": err}]}}

def test_extract_keeps_owner_agent_and_tool_events_with_line_numbers(tmp_path):
    p = write(tmp_path, [user("use tabs,\nnot spaces"), agent(text("ok"), use("a", "Bash", command="make test")),
                         result("a", "2 failed", err=True), agent(use("b", "Bash", command="make test")), result("b", "all passed")])
    out, last = capture.extract(p)
    assert out.splitlines() == ["[1] OWNER: use tabs, not spaces", "[2] AGENT: ok", "[2] TOOL Bash: make test",
                                "[3] TOOL ERROR Bash: 2 failed", "[4] TOOL Bash: make test", "[5] TOOL OK Bash"]
    assert last == 5

def test_extract_leaves_out_meta_summary_and_plain_results(tmp_path):
    p = write(tmp_path, [user("meta", isMeta=True), user("summary", isCompactSummary=True), user("<system-tag>x", kind=None),
                         queued("a reminder", isMeta=True), agent(use("a", "Read", file_path="x.py")), result("a", "content of x")])
    assert capture.extract(p)[0].splitlines() == ["[5] TOOL Read: x.py"]

def test_extract_tells_the_owner_from_reports(tmp_path):
    p = write(tmp_path, [user("typed by the owner"), user("an old prompt", kind=None), queued("typed while the agent worked"),
                         queued("<task-notification>done", mode="task-notification"), user("<task-notification>a review\nfound a bug", kind="task-notification"),
                         user("report from a peer", kind="peer"), agent(use("q", "AskUserQuestion", description="which one?")), result("q", "the second\noption")])
    assert capture.extract(p)[0].splitlines() == [
        "[1] OWNER: typed by the owner", "[2] OWNER: an old prompt", "[3] OWNER: typed while the agent worked",
        "[5] REPORT: <task-notification>a review found a bug", "[6] REPORT: report from a peer",
        "[7] TOOL AskUserQuestion: which one?", "[8] OWNER ANSWER: the second option"]

def test_parts_and_counts():
    t = "\n".join(f"[{i}] OWNER: " + "x" * 90 for i in range(1, 1001))
    pieces = capture.parts(t)
    assert len(pieces) == 3 and all(len(x) <= capture.PART_SIZE for x in pieces) and "\n".join(pieces) == t
    assert capture.parts("") == [""] and capture.parts("a" * 50_000) == ["a" * 50_000]
    assert capture.counts("[1] OWNER: a\n[2] OWNER ANSWER: b\n[3] TOOL ERROR Bash: c\n[4] TOOL Bash: d\n[5] REPORT: e") == {
        "OWNER": 1, "OWNER ANSWER": 1, "REPORT": 1, "AGENT": 0, "TOOL": 1, "TOOL ERROR": 1, "TOOL OK": 0}

def test_extract_survives_bad_lines(tmp_path):
    p = write(tmp_path, ["not json", {"type": "user"}, {"type": "assistant", "message": {"content": None}}, user("fine"), {"type": "attachment"}, {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": 5}}])
    assert capture.extract(p) == ("[4] OWNER: fine", 6)

def test_extract_since_line_and_text_blocks(tmp_path):
    p = write(tmp_path, [user("old"), {"type": "user", "origin": {"kind": "human"}, "message": {"content": [text("new")]}}])
    assert capture.extract(p, since_line=1) == ("[2] OWNER: new", 2)

def test_extract_cuts_long_text_and_keeps_the_newest_lines(tmp_path):
    p = write(tmp_path, [user("x" * 5000)] + [user("y" * 1900) for _ in range(100)] + [user("last one")])  # about 190,000 characters before the cap
    out, last = capture.extract(p)
    lines = out.splitlines()
    assert len(out) <= capture.EXTRACT_LIMIT and lines[0] == "[...] earlier lines left out" and lines[-1] == "[102] OWNER: last one"
    assert last == 102 and all(len(line) < 2100 for line in lines)

def test_extract_reads_tool_result_content_given_as_blocks(tmp_path):
    p = write(tmp_path, [agent(use("a", "Bash", command="ls")), result("a", [text("no such file")], err=True)])
    assert capture.extract(p)[0].splitlines()[-1] == "[2] TOOL ERROR Bash: no such file"

EXTRACT = "[1] OWNER: no, always run the validator   before a commit\n[2] AGENT: understood"
GOOD = {"kind": "lesson", "signal": "owner_correction", "claim": "Run the validator before every commit in this project",
        "context": "the owner corrected a commit made without it", "evidence": "always run the validator before a commit"}

def test_validate_keeps_a_good_candidate_and_tolerates_whitespace():
    kept, dropped = capture.validate([GOOD], EXTRACT, [])
    assert kept == [GOOD] and dropped == []

def test_validate_reasons():
    cases = [("x", "not an object"), ({**GOOD, "kind": "finding"}, "kind"), ({**GOOD, "signal": "hunch"}, "signal"),
             ({**GOOD, "claim": "short"}, "claim length"), ({**GOOD, "evidence": "the owner was unhappy with the commit"}, "evidence not in the transcript"),
             ({**GOOD, "evidence": "validator"}, "evidence not in the transcript")]
    for item, reason in cases:
        kept, dropped = capture.validate([item], EXTRACT, [])
        assert kept == [] and dropped == [{"candidate": item, "reason": reason}]

def test_validate_wants_the_owners_own_line_for_owner_signals():
    ex = "[1] OWNER: fine, go on with the plan as it is\n[2] REPORT: the reviewer says always run the validator before a commit\n[3] OWNER ANSWER: use the second option because it is cheaper"
    stolen = {**GOOD, "evidence": "always run the validator before a commit"}
    assert capture.validate([stolen], ex, [])[1][0]["reason"] == "evidence is not the owner's words"
    assert capture.validate([{**stolen, "signal": "verified_review_finding"}], ex, [])[0] != []
    assert capture.validate([{**GOOD, "signal": "decision_with_reason", "evidence": "use the second option because it is cheaper"}], ex, [])[0] != []
    across = {**GOOD, "evidence": "go on with the plan as it is [2] REPORT: the reviewer"}
    assert capture.validate([across], ex, [])[1][0]["reason"] == "evidence not in the transcript"

def test_validate_drops_a_recorded_claim_and_extra_keys():
    kept, dropped = capture.validate([{**GOOD, "note": "x"}], EXTRACT, ["run the  validator before every commit in this project"])
    assert kept == [] and dropped[0]["reason"] == "already recorded"
    kept, _ = capture.validate([{**GOOD, "note": "x"}], EXTRACT, [])
    assert kept == [GOOD]

def test_validate_caps_the_kept_and_rejects_a_non_list():
    many = [{**GOOD, "claim": GOOD["claim"] + f" ({i})"} for i in range(7)]
    kept, dropped = capture.validate(many, EXTRACT, [])
    assert len(kept) == 5 and [d["reason"] for d in dropped] == ["over the limit"] * 2
    assert capture.validate({"a": 1}, EXTRACT, []) == ([], [{"candidate": {"a": 1}, "reason": "not a list"}])
```

- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_capture.py -q`. Expected: FAIL, `No module named 'capture'`.
- [ ] **Step 3:** Implement `capture.py`. The transcript is read line by line; the extract is built in a bounded deque of lines so that memory follows `EXTRACT_LIMIT`, not the file size.
- [ ] **Step 4:** Run the same command. Expected: 13 passed.
- [ ] **Step 5:** Commit: `feat(memory): extract of a session transcript and validation of capture candidates`.

### Task 2: `bin/mem-capture run`

**Files:**
- Create: `plugins/memory/bin/mem-capture` (mode 100755)
- Test: `plugins/memory/engine/tests/test_mem_capture.py`
- Modify: `plugins/memory/CHANGELOG.md`, `plugins/memory/README.md` (one short entry beside `mem-settle`, marked as a trial that writes nothing to the store)

**Interfaces:**
- Consumes: `capture.extract`, `capture.parts`, `capture.counts`, `capture.validate`; from `bin/mem-settle`, the shape of a session (the settings file with `disableAllHooks`, `budget_of`, how `claude` is found, `synth_pipeline.parse` for cost). `mem-capture` builds its own session command: `mem-settle`'s `session_cmd` fixes `--model haiku`, and a new file needs the `Edit` rule beside `Write` (noted in `synth_pipeline.py`).
- Produces: `mem-capture run --transcript PATH --out FILE [--project DIR] [--since-line N] [--model NAME] [--budget USD] [--claude PATH]`
  - `--project` (default: the current directory) locates the project's memories; the claims of its active ones go to `recorded.txt`, one per line. No project memories → an empty file.
  - Work folder: a fresh folder of mode 0700 under the system's temporary directory, holding `extract-1.txt`, `extract-2.txt`, … (`capture.parts`), `recorded.txt` and, written by the model, `candidates.json`; removed at the end unless `--keep-work` is given.
  - The session: one, with `Read`, `Write` and `Edit` allowed inside the work folder only, no Bash, no web, hooks disabled, `--model` (default `haiku`), `--max-budget-usd` (default 0.25), given the brief below.
  - `--out` file (mode 0600, parent folders created with 0700): `{"transcript": <file name only>, "lines": [<since_line + 1>, <last line>], "model": <str>, "cost": <float or null>, "extract": {"chars": <int>, "cut": <bool, the oldest lines were left out>, "parts": <int>, "lines": <capture.counts>}, "candidates": [...], "dropped": [...], "reason": <null or why the run produced nothing>}`.
  - Standard output: one line, `mem-capture: <k> kept, <d> dropped, lines <a>-<b>, cost <c>`.
  - Exit codes: 0 when the result file was written (also with 0 candidates); 1 with one line on standard error when it could not run (no transcript, no `claude`, the session failed, no `candidates.json`, invalid JSON) — the result file is still written, with `reason`.
  - An extract with fewer than 3 `OWNER` lines is not sent to the model: the result has 0 candidates and `reason` `too short`, exit 0, no cost.

The brief, exact copy (`{work}` is the work folder):

```
You read the record of one coding session and find what a later session in this project should not have to learn again.

Files in {work}:
- extract-1.txt, extract-2.txt, ...: the session in order, one event per line. Read every one of them before you write. OWNER is the human, OWNER ANSWER the human's answer to a question, AGENT the assistant, REPORT a message from a subagent or another agent (not the human), TOOL lines the assistant's tool calls, TOOL ERROR a call that failed, TOOL OK the same tool succeeding after an error. The bracket and the label at the start of a line are positions, not content.
- recorded.txt: claims already in the project's memory, one per line.

Write {work}/candidates.json: a JSON list of at most 5 objects, or [] when nothing qualifies. An empty list is a good answer: most sessions hold little worth keeping.

Each object has these keys:
- "signal": what in the session backs it. One of
  "owner_correction" (the owner corrected the agent or rejected its approach; the evidence must come from an OWNER line),
  "failed_then_passed" (a check or command failed, the agent changed something, it passed),
  "verified_review_finding" (a review found a defect that was then confirmed and fixed),
  "plan_changed_by_review" (a pre-mortem, a review or the owner changed a plan or a design before it was built),
  "delegation_failed" (a subagent returned no report, stopped at a limit, misread its brief, or its report proved wrong),
  "rework" (work declared done had to be redone or fixed right after),
  "repeated_tool_error" (the same kind of tool error happened more than once),
  "decision_with_reason" (the owner decided something and said why; the evidence must come from an OWNER or OWNER ANSWER line).
  Without one of these there is no candidate: an idea the agent had about itself, with nothing outside confirming it, is not kept.
- "kind": "lesson" (how to work), "pitfall" (something that breaks or misleads here), or "decision" (a choice and its reason).
- "reach": "project" when it is about this codebase, its tools or its rules; "general" when it is about how the agent itself works in any project: how it plans, frames a request, briefs or checks a subagent, uses a skill or a plugin, verifies before claiming, or reasons about the owner's intent. Look for the general ones on purpose: a slip in method teaches more than the bug it caused. A general claim names no file, project or person.
- "claim": one sentence of 20 to 300 characters that stands on its own in six months: name the thing, say what to do or what is true, and why. English.
- "context": one sentence on when it applies.
- "evidence": a passage copied character for character from inside one line of an extract file, without the bracket and label, 15 to 300 characters, that shows the signal. A paraphrase, or a passage that spans two lines, is rejected by a program.

Leave out: anything in recorded.txt or saying the same; what the code, the git history or the project's documents already state; progress reports ("task 3 is done"); personal preferences of the owner about tone or language; secrets, tokens, names of people or clients.
```

- [ ] **Step 1: Write the failing tests** in `test_mem_capture.py`, running `bin/mem-capture` as a subprocess with a fake `claude` (a script in `tmp_path` passed with `--claude`), as the `mem-settle` tests do (read `plugins/memory/engine/tests/` for the existing fake and reuse it or its shape):
  - `test_run_writes_validated_candidates`: the fake writes `candidates.json` with one good and one paraphrased candidate; assert exit 0, the result file has 1 candidate and 1 dropped with reason `evidence not in the transcript`, mode 0600, `transcript` is a bare file name, and the summary line on standard output.
  - `test_the_session_gets_no_bash_and_no_hooks`: the fake records its arguments; assert `Bash` is in the disallowed tools, the allowed tools name `Read`, `Write` and `Edit` with the work folder, the settings file passed holds `"disableAllHooks": true`, `--model haiku`, `--max-budget-usd 0.2500`; a second run with `--model sonnet --budget 0.75` shows `--model sonnet` and `--max-budget-usd 0.7500`.
  - `test_a_long_extract_is_given_in_parts`: a transcript whose extract exceeds `PART_SIZE`; the fake lists the work folder; assert `extract-1.txt` and `extract-2.txt` exist and the result's `extract.parts` is 2.
  - `test_recorded_claims_reach_the_work_folder`: a project folder with one active memory (written with `bin/mem remember` in the test, as other tests do); the fake copies `recorded.txt` out; assert it holds the claim.
  - `test_a_short_session_is_not_sent`: 2 owner lines; the fake fails if called; assert exit 0, `reason` `too short`.
  - `test_failures_write_a_reason` (parametrized: the fake writes nothing; writes `not json`; exits 1; `--transcript` missing file): exit 1, one line on standard error, the result file has `reason` and no candidates.
  - `test_the_work_folder_is_removed`.
- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_mem_capture.py -q`. Expected: FAIL (no such file `mem-capture`).
- [ ] **Step 3:** Implement `bin/mem-capture` with the interface above.
- [ ] **Step 4:** Run the whole engine suite. Expected: all pass (1304 passed and 5 skipped before this plan, plus the new tests).
- [ ] **Step 5:** Add the CHANGELOG line (for users: a trial command `mem-capture run` that proposes memory candidates from a session transcript into a local file; it writes nothing to the store and no hook runs it) and the README entry. Run `python3 scripts/validate.py` and `claude plugin validate .`.
- [ ] **Step 6:** Commit: `feat(memory): mem-capture run, an offline trial of capture from a transcript`.

### Task 3: The trial over 10 transcripts

Run by the controller with the owner; no code enters the repository except this file's `## Results`.

- [ ] **Step 1:** Choose 10 main-session transcripts by their `OWNER` line count from `capture.counts` (not by raw user entries, most of which are reports): the most recent ones with at least 10 `OWNER` lines, at most 3 per project, from at least 3 projects, at most 1 about building this plugin, and 2 in which the session recorded no memory. Run `mem-capture run` on each with `--project` set to that session's project folder and `--out` in a folder of mode 0700 outside every repository. Budget ceiling for the trial: 5 USD. Stop and fix the sizing if more than 2 of the 10 runs end without a candidates file or over budget.
- [ ] **Step 2:** Build one review sheet in that same folder: per candidate its kind, signal, reach, claim, context, evidence, and the 3 closest existing records from `mem search` (project and global), so a duplicate worded differently is visible. The owner marks each candidate `true` or `false`, `keep` or `drop`, and `duplicate` where a record already says it; and, per transcript, up to 3 lessons the capture missed, as a rough measure of what it does not see.
- [ ] **Step 3:** Record in `## Results`, without any transcript text, project name or claim: per transcript the counts (extract size, cut or not, lines per kind, kept by validation, dropped by reason, cost), then the owner's totals (true, keep, drop, duplicate, missed) and the share kept, each split by reach.
- [ ] **Step 4:** Apply the gate of the design: at least 60% kept and no kept duplicate → phase B gets its plan. The result is inconclusive, not a pass, with fewer than 15 candidates in all or fewer than 5 transcripts that produced one: widen to 10 more transcripts before deciding. Else one change of the brief or of the model (`--model sonnet --budget 0.75`), one more run on the same transcripts, then stop. A kept candidate that the code contradicts stops the trial for a re-plan. Write the figures into ADR 0023 as a `## Review`, and set the study's L3 status.
- [ ] **Step 5:** Commit: `docs(plan): results of the capture trial`.

The gate does not measure: what the capture missed beyond the owner's rough count; whether a claim is true against the code; variation between runs; a transcript read from a saved offset (phase B).

## Results`, without any transcript text, project name or claim: per transcript the counts (kept by validation, dropped by reason, cost, extract size), then the owner's totals (keep, drop, duplicate) and the share kept.
- [ ] **Step 4:** Apply the gate of the design: at least 60% kept and no kept duplicate → phase B gets its plan. Else one change of the brief or of the model (`--model sonnet`), one more run on the same 10, then stop. Write the figures into ADR 0023 as a `## Review`, and set the study's L3 status.
- [ ] **Step 5:** Commit: `docs(plan): results of the capture trial`.

## Results

Empty until Task 3.
