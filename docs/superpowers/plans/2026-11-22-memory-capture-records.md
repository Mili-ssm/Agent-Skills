# Memory capture records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mem-capture run --write` turns validated candidates into project memories that say where they came from, how far they reach, how much they weigh and whether they are established yet; a lesson the project already holds gains a sighting instead of a copy; and the brief asks for wording that carries a lesson's certainty.

**Architecture:** A memory gains two optional fields, `reach` and `weight`, and the origin `transcript`; its standing (`unconfirmed` or `established`) is derived from its sightings and its weight, never stored. `mem-capture` keeps the model without Bash: code writes each kept candidate through `bin/mem remember`, or `bin/mem confirm` when the candidate names a memory the project already has, so every existing check at writing (secrets, forbidden terms, identical claims) applies unchanged. No hook is registered in this stage.

**Tech Stack:** Python 3 standard library (`plugins/memory/engine/`), pytest through `uv`, `claude -p`.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md), stage B1, decisions C5, C6, C10, C11, C13, C15, C16, C20. Stages B2 to B4 are not in this plan.

## Global Constraints

- No hook, no plugin option, no background run, no global write: `mem-capture` writes only in the project scope, and only with `--write`. Without `--write` it behaves as in the trial.
- The model session still gets no Bash and no web; code applies every write through `bin/mem`, so the checks of `mem remember` stay the only gate (exit 3 same claim, 4 secret or forbidden term, 5 a term that needs the owner).
- A memory written before this plan (no `reach`, no `weight`, another origin) reads, lists and curates exactly as before.
- Standing is derived: a memory with origin `transcript` is `established` when its `observed` count reaches the threshold of its weight (`light` 1, `medium` 2, `strong` 3; no weight counts as `medium`), else `unconfirmed`. Other origins have no standing.
- A record with origin `transcript` is valid for 30 days while unconfirmed (each sighting restarts the 30 days) and has no end date once established.
- The model may propose the forms `suggestion` and `recommendation` only; `instruction` is dropped by validation (C20).
- A candidate of kind `decision` is a project record: its reach is `project` (C16).
- Extract, result and work files hold session text: 0600 in folders of 0700, never inside a repository. Tests use a fake `claude` and invented text; no real transcript is opened. This repository is public: no home path, private name or transcript text in code, tests or docs.
- Changes under `plugins/memory/` add a line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`; no version change.
- Engine tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (1348 passed, 5 skipped before this plan). Before every commit: `python3 scripts/validate.py` and `claude plugin validate .`.

## Review Focus

- A memory file written by hand with `reach: everywhere`, `weight: 7` or `origin: transcript` and no weight: read without error, the unknown values ignored, standing computed as `medium`.
- `mem confirm` on a transcript memory that crosses its threshold: its end date disappears; on one that does not: the end date moves to 30 days from today.
- `mem-capture run --write` when `mem remember` refuses a candidate (secret, forbidden term, identical claim) or `bin/mem` cannot run: that candidate is reported with its reason, the others are still written, the exit code says a result file was written.
- A candidate whose `same_as` names a memory that is not in the project (a global one, a retired one, an invented handle): dropped, nothing confirmed.
- The same transcript run twice with `--write`: the second run writes nothing new (identical claims are refused by `mem remember`), and adds no sighting on its own writes.

---

### Task 1: Records: origin `transcript`, `reach`, `weight`, standing

**Files:**
- Modify: `plugins/memory/engine/records.py`, `plugins/memory/engine/mem.py` (`mem remember` flags, `_unconfirmed`, the `mem curate` queue, `cmd_confirm` only if `records.observe` cannot carry the validity rule)
- Test: `plugins/memory/engine/tests/test_transcript_records.py` (new)

**Interfaces:**
- Produces, in `records.py`:
  - `ORIGINS = ("web", "pipeline", "transcript")`; `REACHES = ("project", "general")`; `WEIGHTS = ("light", "medium", "strong")`; `SIGHTINGS_NEEDED = {"light": 1, "medium": 2, "strong": 3}`; `UNCONFIRMED_DAYS = 30`.
  - `Memory` gains `reach: str | None = None` and `weight: str | None = None`, read from and written to the frontmatter keys `reach` and `weight` when set; a value outside the tuples reads as `None`.
  - `write_memory(..., reach: str | None = None, weight: str | None = None)`: an unknown value raises `ValueError`; with origin `transcript` and no `valid_until` given, `valid_until = today + 30 days` unless the record is established at once (weight `light`).
  - `standing(memory: Memory) -> str | None` — `None` unless origin is `transcript`; else `"established"` or `"unconfirmed"` by the rule in Global Constraints.
  - `observe(memory, today)` — unchanged for other origins; for origin `transcript`, after the count rises: established → `valid_until` removed; still unconfirmed → `valid_until = today + 30 days`.
- Produces, in `mem.py`:
  - `mem remember --origin transcript`, `--reach {project,general}`, `--weight {light,medium,strong}` (both optional, allowed with any origin).
  - The bracket of a memory line shows `, from transcript, unconfirmed` while `records.standing` is `unconfirmed`, and `, from transcript` once established; `web` keeps `, web, unconfirmed`.
  - `mem curate` gains one category after "not confirmed in 90 days": `from a transcript, not confirmed yet`, listing live memories whose standing is `unconfirmed`, each with its weight and `observed` count; such a memory is not also listed under "not confirmed in 90 days".

- [ ] **Step 1: Write the failing tests** in `test_transcript_records.py` (use the helpers other record tests use to make a project folder and run `bin/mem`):
  - `test_a_medium_transcript_memory_is_unconfirmed_and_valid_30_days`: `write_memory(..., kind="lesson", origin="transcript", reach="general", weight="medium", today=D)` → `standing == "unconfirmed"`, `valid_until == D + 30 days`, and the file's frontmatter holds `origin: transcript`, `reach: general`, `weight: medium`; `load_memories` reads the three back.
  - `test_a_light_one_is_established_at_once`: weight `light` → `standing == "established"`, `valid_until is None`.
  - `test_sightings_establish_it`: a `medium` one observed once more on day D+10 → `observed == 2`, `standing == "established"`, `valid_until is None`; a `strong` one observed once on D+10 → `unconfirmed`, `valid_until == D + 40 days`; observed again → `established`.
  - `test_other_origins_have_no_standing_and_keep_their_dates`: a session memory and a `web` finding → `standing is None`; `observe` leaves `valid_until` as it was.
  - `test_unknown_values`: `write_memory(reach="everywhere")` and `(weight="heavy")` raise `ValueError`; a file edited by hand to `reach: everywhere`, `weight: 7` loads with both `None` and, with origin `transcript`, standing `unconfirmed` at `observed` 1 and `established` at 2.
  - `test_remember_flags_and_the_tag` (through `bin/mem`): `mem remember --kind lesson --claim "<invented>" --origin transcript --reach general --weight medium` exits 0; `mem memories` shows `from transcript, unconfirmed` on its line; after `mem confirm m:<handle>` the line shows `from transcript` without `unconfirmed`; a memory written without the flags shows neither.
  - `test_curate_lists_unconfirmed_transcript_memories`: the queue prints the category heading and that memory with `medium` and `observed 1`; an established one and a session memory are not under it; the unconfirmed one is not under "not confirmed in 90 days" even when its dates say so.
- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_transcript_records.py -q`. Expected: FAIL (unknown origin `transcript`).
- [ ] **Step 3:** Implement the interfaces above. Keep the frontmatter key order of `_render`, adding `reach` and `weight` after `origin`.
- [ ] **Step 4:** Run the whole engine suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): memories from a transcript carry a reach, a weight and a standing`.

### Task 2: Candidates v2 and the brief v2

**Files:**
- Modify: `plugins/memory/engine/capture.py` (`validate` and its constants), `plugins/memory/bin/mem-capture` (the brief, `recorded.txt`, a new `rules.txt`)
- Test: `plugins/memory/engine/tests/test_capture.py`, `plugins/memory/engine/tests/test_mem_capture.py`

**Interfaces:**
- Consumes: `records.REACHES`, `records.WEIGHTS` (Task 1) — `capture.REACHES` becomes that tuple.
- Produces, in `capture.py`:
  - `FORMS = ("suggestion", "recommendation")`.
  - `validate(candidates, extract_text, recorded, handles=()) -> tuple[list[dict], list[dict]]` — as before, plus, checked after `reach` and in this order: `weight` (missing → `"medium"`; a value outside `records.WEIGHTS` → reason `weight`); `form` (missing → `"recommendation"`; any other value, `instruction` included → reason `form`); `a decision is a project record` (kind `decision` with reach `general`); `same_as` (optional; when present it must be a string in `handles`, else reason `same_as`; when valid, the `already recorded` check is skipped, because the candidate is a sighting of that record). A kept item has exactly the keys `kind`, `signal`, `reach`, `weight`, `form`, `claim`, `context`, `evidence`, `same_as` (`None` when absent).
- Produces, in `mem-capture`:
  - `recorded.txt`: one line per live memory. Project scope: `m:<handle><TAB><claim>`. Global scope: `(general)<TAB><claim>`, with no handle, because a sighting may only be added to a memory of this project.
  - `rules.txt`: the owner's always-loaded instruction files, so that a rule the owner already wrote is not proposed again: the project's `CLAUDE.md` and `AGENTS.md` at the project root, then `CLAUDE.md` in the folder named by `CLAUDE_CONFIG_DIR`, else in `.claude` under the home folder; each under a line `## <file name>`; the whole cut to 30,000 characters; none found → an empty file. `--no-rules` leaves the file empty.
  - `validate` is called with the project handles; the result's candidates carry the new keys.
  - The brief, exact copy (`{work}` is the work folder):

```
You read the record of one coding session and find what a later session should not have to learn again.

Files in {work}:
- extract-1.txt, extract-2.txt, ...: the session in order, one event per line. Read every one of them before you write. OWNER is the human, OWNER ANSWER the human's answer to a question, AGENT the assistant, REPORT a message from a subagent or another agent (not the human), TOOL lines the assistant's tool calls, TOOL ERROR a call that failed, TOOL OK the same tool succeeding after an error. The bracket and the label at the start of a line are positions, not content.
- recorded.txt: what the memory already holds, one per line. A line starting with m: is a memory of this project, with its handle; a line starting with (general) holds in every project.
- rules.txt: the standing instructions the owner already wrote for the agent.

Write {work}/candidates.json: a JSON list of at most 5 objects, or [] when nothing qualifies. Most sessions hold one or two things worth keeping, many hold none; five is a ceiling, not a target.

Two kinds of thing qualify, and they are not the same:
- A lesson or a pitfall: something that generalises beyond this session and can be said as advice.
- A decision of this project with its reason. That is a record of the project, not a lesson: give it "kind": "decision" and "reach": "project".
A technical detail of one component, a progress report, or a request the owner made once is neither: leave it out.

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
- "kind": "lesson" (how to work), "pitfall" (something that breaks or misleads), or "decision".
- "reach": "project" when it is about this codebase, its tools or its rules; "general" when it is about how the agent itself works in any project: how it plans, frames a request, briefs or checks a subagent, uses a skill or a plugin, verifies before claiming, or reads the owner's intent. Look for the general ones on purpose: a slip in method teaches more than the bug it caused. A general claim names no file, project or person.
- "weight": how much following it restricts the agent or the owner, and what it costs if it is wrong: "light" (a cheap habit that can hardly hurt), "medium", or "strong" (it forbids something, or a mistake would be costly).
- "form": "suggestion" (worth trying) or "recommendation" (do this unless there is a reason not to). Never an order.
- "claim": 20 to 300 characters, in English, standing on its own in six months. Say what was seen and what it suggests, at the strength the evidence gives it and no more. This session is one sighting: write "in one session ...", "when X, Y happened, so consider ...", not "always" or "never". Say what is not known: whether it holds elsewhere, whether it may be temporary, under which condition it was seen. When the signal is a correction by the owner, report it as what the owner said and did, and weigh the other reading too: the owner may have misread the agent, and then the lesson is to explain more clearly.
- "context": one sentence on when it applies.
- "evidence": a passage copied character for character from inside one line of an extract file, without the bracket and label, 15 to 300 characters, that shows the signal. A paraphrase, or a passage that spans two lines, is rejected by a program.
- "same_as": only when a line of recorded.txt starting with m: already says this: its handle, exactly as written (for example "m:some-handle"). Then this session is one more sighting of it; still give the other keys.

Leave out: what a (general) line of recorded.txt or rules.txt already says; what the code, the git history or the project's documents already state; secrets, tokens, names of people or clients.
```

- [ ] **Step 1: Write the failing tests.** In `test_capture.py`: defaults (`weight` `medium`, `form` `recommendation`, `same_as` `None`) and the exact key set of a kept item; reasons `weight` (`"heavy"`), `form` (`"instruction"`, `"order"`), `a decision is a project record`, `same_as` (a handle not in `handles`, a non-string); a candidate whose claim equals a recorded claim is kept when its `same_as` is a valid handle and dropped as `already recorded` without it; the order of reasons for an item wrong in several ways (`reach` before `weight` before `form`). The constant `GOOD` gains `"weight": "medium", "form": "recommendation", "same_as": None`; no other existing assertion changes. In `test_mem_capture.py`: `recorded.txt` holds `m:<handle>\t<claim>` for a project memory and `(general)\t<claim>` for a global one; `rules.txt` holds the project's `CLAUDE.md` text under `## CLAUDE.md` and, with `CLAUDE_CONFIG_DIR` set to a temp folder, that folder's `CLAUDE.md`; `--no-rules` gives an empty file; a 100,000-character rules file is cut to 30,000; the fake writes a candidate with `same_as` set to the project memory's handle and the result keeps it with that value; the fake receives a brief that contains `rules.txt` and `"same_as"` (the test reads the prompt argument).
- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_capture.py plugins/memory/engine/tests/test_mem_capture.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement. In tests the home folder and `CLAUDE_CONFIG_DIR` point to temp folders, so no real instruction file is read.
- [ ] **Step 4:** Run the whole engine suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): capture candidates carry a weight, a form and a sighting; the brief asks for calibrated wording`.

### Task 3: `mem-capture run --write`

**Files:**
- Modify: `plugins/memory/bin/mem-capture`, `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md`, `plugins/memory/skills/memory/SKILL.md` (one sentence beside `web, unconfirmed`: what `from transcript, unconfirmed` means and that `mem confirm` records one more sighting)
- Test: `plugins/memory/engine/tests/test_mem_capture.py`

**Interfaces:**
- Consumes: Task 1's `mem remember` flags and `mem confirm`; Task 2's kept items.
- Produces: `mem-capture run ... --write`
  - For each kept item, in order, `bin/mem` is run with the project folder as working directory and the environment of the run:
    - `same_as` set → `mem confirm <same_as>`; outcome `sighting`.
    - else → `mem remember --kind <kind> --claim <claim> --context <context> --origin transcript --reach <reach> --weight <weight> --source "session <transcript file name without extension>" --body-file -`, the body on standard input being three lines: `Signal: <signal>`, `Form: <form>`, `Evidence: “<evidence>”`; outcome `remembered` with the handle `mem` printed.
    - A non-zero exit → outcome `skipped` with a reason: exit 3 `same claim already recorded`, 4 `refused: secret or forbidden term`, 5 `needs the owner: a term on the ask list`, any other `mem failed (<code>)`; `bin/mem` missing or a timeout of 60 s → `mem could not run`. The next items are still applied.
  - The result file gains `"written": [{"claim": <first 80 characters>, "outcome": ..., "handle": <str or null>, "reason": <str or null>}]`; without `--write` the key is absent.
  - Standard output: the one line gains `, written <r> new, <s> sightings, <k> skipped`.
  - Exit code: unchanged (0 when a valid run wrote its result file), whatever the outcomes.
  - `--write` with a project folder that has no memory folder yet is not an error: `mem remember` creates it.

- [ ] **Step 1: Write the failing tests** (fake `claude`, a temp project, `MEM_MEMORIES` set as the fixture does): one new lesson is written — `mem memories` in the project shows its claim with `from transcript, unconfirmed`, its file holds `reach`, `weight` and the three body lines, and the result's `written` has outcome `remembered` with that handle; a candidate with `same_as` raises that memory's `observed` to 2 and writes no new file; two candidates with the same claim → the second is `skipped` with `same claim already recorded`; a candidate whose evidence holds a token-shaped secret (use the shape the existing secret tests use) → `skipped` with the refusal reason and nothing written; running the same input twice → the second run's `written` has no `remembered`; without `--write` no memory file appears and `written` is absent; the summary line.
- [ ] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_mem_capture.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole engine suite. Expected: all pass.
- [ ] **Step 5:** Update the README entry (what `--write` does, that it writes in the project scope only, that records start unconfirmed and how they become established), the CHANGELOG (for users: memories can now come from a session transcript; they are marked `from transcript, unconfirmed` until seen again; `mem-capture run --write`; nothing runs by itself yet) and the sentence in the `memory` skill. Run `python3 scripts/validate.py`, `python3 scripts/port.py --check` and `claude plugin validate .`.
- [ ] **Step 6:** Commit: `feat(memory): mem-capture run --write records what a session taught as project memories`.

### Task 4: Check on real transcripts

Run by the controller; nothing but this file's `## Results` enters the repository.

- [ ] **Step 1:** Run the new brief without `--write` on the 10 transcripts of the trial. Record per transcript the counts kept and dropped by reason, and in total: how many runs returned the ceiling of 5 (8 of 10 before), the split by reach, weight and form, how many `same_as`, the cost.
- [ ] **Step 2:** Show the owner, in conversation, the claims of 2 transcripts beside the claims the first brief gave for the same transcripts, for a judgment on the wording (C11, C13, C15, C16). No claim text enters the repository.
- [ ] **Step 3:** With the owner's word, run `--write` on one transcript of this repository's project; list the written memories with `mem memories` and `mem curate`; run it a second time and confirm nothing new is written.
- [ ] **Step 4:** Record the figures in `## Results` and in ADR 0023 as a `## Review`; set the design's stage B1 as done. Kill criteria for the brief (a prompt change with no eval suite): more than half of the runs still return 5, or the owner judges the wording no better → one more revision of the brief, then keep the first brief's claim rules and carry only the new keys.
- [ ] **Step 5:** Commit: `docs(plan): results of the capture records stage`.

## Results

Empty until Task 4.
