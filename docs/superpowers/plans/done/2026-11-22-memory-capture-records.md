# Memory capture records Implementation Plan

Status: done · merged in #150, 2026-11-22 · unticked boxes are not open work

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mem-capture run --write` turns validated candidates into project memories that say where they came from, how far they reach, how much they weigh and whether they are established yet; a lesson the project already holds gains a sighting instead of a copy; and the brief asks for wording that carries a lesson's certainty.

**Architecture:** A memory gains two optional fields, `reach` and `weight`, and the origin `transcript`; its standing (`unconfirmed` or `established`) is derived from its sightings and its weight, never stored. A sighting is a distinct session: the record's `sources` list holds one `session <id>` entry per session that showed it, so the same session read twice, a curation pass or an agent's plain `mem confirm` cannot establish a record. `mem-capture` keeps the model without Bash: code writes each kept candidate through `bin/mem remember`, or `bin/mem confirm` when the candidate names a memory the project already has, so every existing check at writing (secrets, forbidden terms, identical claims) applies unchanged. No hook is registered in this stage.

**Tech Stack:** Python 3 standard library (`plugins/memory/engine/`), pytest through `uv`, `claude -p`.

**Spec:** [the capture design](../../specs/2026-11-21-memory-capture-design.md), stage B1, decisions C5, C6, C10, C11, C13, C15, C16, C20. Stages B2 to B4 are not in this plan.

## Global Constraints

- No hook, no plugin option, no background run, no global write: `mem-capture` writes only in the project scope, and only with `--write`. Without `--write` it behaves as in the trial.
- The model session still gets no Bash and no web; code applies every write through `bin/mem`, so the checks of `mem remember` apply unchanged (exit 3 same claim, 4 a secret). The forbidden-term list is checked only on global writes, by design: a project's memory may name its own business. This stage writes nothing global; the terms are checked when a lesson is promoted (stage B3).
- A memory written before this plan (no `reach`, no `weight`, another origin) reads, lists and curates exactly as before.
- Standing is derived: a memory with origin `transcript` is `established` when the number of distinct `session <id>` entries in its `sources` reaches the threshold of its weight (`light` 1, `medium` 2, `strong` 3; no weight counts as `medium`), else `unconfirmed`. Its `observed` count plays no part: `mem confirm` without a session, a merge or a curation pass raise it. Other origins have no standing.
- A record with origin `transcript` is valid for 30 days while unconfirmed (each new session restarts the 30 days) and has no end date once established. A lapsed unconfirmed one is not noise for curation: it stays out of the "expired" category and out of the count that makes a curation pass due, and a later session that shows the same lesson revives it instead of writing a copy.
- The model may propose the forms `suggestion` and `recommendation` only; `instruction` is dropped by validation (C20).
- A candidate of kind `decision` is a project record: its reach is `project` (C16).
- Extract, result and work files hold session text: 0600 in folders of 0700, never inside a repository. Tests use a fake `claude` and invented text; no real transcript is opened. This repository is public: no home path, private name or transcript text in code, tests or docs.
- Changes under `plugins/memory/` add a line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`; no version change.
- Engine tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (1348 passed, 5 skipped before this plan). Before every commit: `python3 scripts/validate.py` and `claude plugin validate .`.

## Review Focus

- A memory file written by hand with `reach: everywhere`, `weight: 7` or `origin: transcript` and no weight: read without error, the unknown values ignored, standing computed as `medium`.
- The same transcript run twice with `--write`, the model naming on the second run the very records the first run wrote: no count and no source changes, nothing is established. Two candidates of one run naming the same record: one sighting.
- `mem confirm m:<h> --until <date>` (what the curation queue suggests for an expired record) or a merge of two records on an unconfirmed transcript memory: its standing does not change, because no new session is added.
- A candidate whose `same_as` names a memory that is not in the project, or whose claim shares too few words with it: dropped, nothing confirmed; an accepted sighting leaves a trace in the record's body.
- `mem-capture run --write` when `mem remember` refuses a candidate (a secret, an identical claim) or `bin/mem` cannot run: that candidate is reported with its reason, the others are still written.
- `--project` given as a git worktree or a subfolder: the memories read for `recorded.txt` and the folder `bin/mem` writes to are the same one.

---

### Task 1: Records: origin `transcript`, `reach`, `weight`, standing

**Files:**
- Modify: `plugins/memory/engine/records.py`, `plugins/memory/engine/mem.py` (`mem remember` flags, `mem confirm --source/--note`, `_unconfirmed`, the `mem curate` queue, the merge), `plugins/memory/agents/memory-curator.md`, `plugins/memory/skills/memory-curation/SKILL.md`, and any existing test or README text that lists the origins (`grep -rn '"pipeline"\|web, pipeline\|{web,pipeline}' plugins/memory`)
- Test: `plugins/memory/engine/tests/test_transcript_records.py` (new)

**Interfaces:**
- Produces, in `records.py`:
  - `ORIGINS = ("web", "pipeline", "transcript")`; `REACHES = ("project", "general")`; `WEIGHTS = ("light", "medium", "strong")`; `SIGHTINGS_NEEDED = {"light": 1, "medium": 2, "strong": 3}`; `UNCONFIRMED_DAYS = 30`; `SESSION_PREFIX = "session "`.
  - `Memory` gains `reach: str | None = None` and `weight: str | None = None`, read from and written to the frontmatter keys `reach` and `weight` when set; a value outside the tuples reads as `None`.
  - `write_memory(..., reach: str | None = None, weight: str | None = None)`: an unknown value raises `ValueError`; with origin `transcript` and no `valid_until` given, `valid_until = today + 30 days` unless the record is established at once.
  - `sessions(memory: Memory) -> list[str]` — the distinct entries of `sources` that start with `SESSION_PREFIX`, in order.
  - `standing(memory: Memory) -> str | None` — `None` unless origin is `transcript`; else `"established"` when `len(sessions(memory))` reaches `SIGHTINGS_NEEDED` of its weight, else `"unconfirmed"`.
  - `add_sighting(memory: Memory, session: str, today: datetime.date, note: str | None = None) -> tuple[Memory, bool]` — `session` is a full source entry (`"session <id>"`). Already in `sources` → the memory unchanged and `False`. Else: the entry appended to `sources`, `observed` raised and `last_observed` set as `observe` does, `note` appended to the body as one line when given, and for origin `transcript` the validity rule applied (established → no `valid_until`; unconfirmed → `today + 30 days`), which also revives a lapsed record; returns the new memory and `True`.
  - A merge keeps the union of both records' `sources`, so the standing of the result follows from its sessions.
  - `curation_due` does not count unconfirmed transcript memories, lapsed or not.
- Produces, in `mem.py`:
  - `mem remember --origin transcript`, `--reach {project,general}`, `--weight {light,medium,strong}` (both optional, allowed with any origin); the `--origin` help names the three origins.
  - `mem confirm m:<handle> --source "session <id>" [--note TEXT]` — calls `records.add_sighting`; when that session is already a source it changes nothing, prints one line saying so and exits 3. Without `--source` the command is unchanged.
  - The bracket of a memory line shows `, from transcript, unconfirmed` while `records.standing` is `unconfirmed`, and `, from transcript` once established; `web` keeps `, web, unconfirmed`.
  - `mem curate`: one new category after "not confirmed in 90 days", `from a transcript, not confirmed yet`, listing live memories whose standing is `unconfirmed`, each with its weight and its number of sessions, under a line that says: forget it, or leave it; it is confirmed only when another session shows it. Such a memory, live or lapsed, is listed under neither "not confirmed in 90 days" nor "expired".
- Also modify `plugins/memory/agents/memory-curator.md` and `plugins/memory/skills/memory-curation/SKILL.md`: one sentence each, that a record marked `from transcript, unconfirmed` is never confirmed by a curation pass (only forgotten, merged or left), because its confirmation is another session showing it. An agent's text with no eval suite: unmeasured, with the kill criterion in Task 4.

- [x] **Step 1: Write the failing tests** in `test_transcript_records.py` (use the helpers other record tests use to make a project folder and run `bin/mem`):
  - `test_a_medium_transcript_memory_is_unconfirmed_and_valid_30_days`: `write_memory(..., kind="lesson", origin="transcript", reach="general", weight="medium", sources=["session a"], today=D)` → `standing == "unconfirmed"`, `valid_until == D + 30 days`, the frontmatter holds `origin: transcript`, `reach: general`, `weight: medium`; `load_memories` reads the three back.
  - `test_a_light_one_is_established_at_once`: weight `light`, one session → `standing == "established"`, `valid_until is None`.
  - `test_a_second_session_establishes_it_and_the_same_session_does_not`: `add_sighting(m, "session a", D+5)` → `(m, False)`, nothing changed; `add_sighting(m, "session b", D+10, note="seen again")` → `True`, `sessions == ["session a", "session b"]`, `standing == "established"`, `valid_until is None`, the body ends with the note line. A `strong` one after `session b` → `unconfirmed`, `valid_until == D + 40 days`; after `session c` → `established`.
  - `test_observed_alone_never_establishes`: `observe(m, D+1)` three times on a `medium` one → `observed == 4`, `standing == "unconfirmed"`.
  - `test_a_lapsed_one_is_revived_by_a_new_session`: on day D+45 the record is not live; `add_sighting(m, "session b", D+45)` on a `strong` one → live again, `valid_until == D + 75 days`.
  - `test_other_origins_have_no_standing_and_keep_their_dates`: a session memory and a `web` finding → `standing is None`; `observe` and `add_sighting` leave `valid_until` as it was.
  - `test_unknown_values`: `write_memory(reach="everywhere")` and `(weight="heavy")` raise `ValueError`; a file edited by hand to `reach: everywhere`, `weight: 7` loads with both `None` and standing computed as `medium`.
  - `test_a_merge_unions_the_sessions`: two unconfirmed `medium` records, one with `session a` and one with `session b`, merged through `bin/mem merge` → the kept record has both sessions and is established; two that both hold only `session a` → still unconfirmed.
  - `test_remember_confirm_and_the_tag` (through `bin/mem`): `mem remember --kind lesson --claim=<invented> --origin transcript --reach general --weight medium --source "session a"` exits 0 and its line in `mem memories` shows `from transcript, unconfirmed`; `mem confirm m:<h>` and `mem confirm m:<h> --until <date>` leave it unconfirmed; `mem confirm m:<h> --source "session a"` exits 3 and changes nothing; `mem confirm m:<h> --source "session b" --note "x"` exits 0 and the line shows `from transcript` without `unconfirmed`; a memory written without the flags shows neither.
  - `test_curate_lists_unconfirmed_transcript_memories`: the queue prints the category heading, its guidance line and that memory with `medium` and `1 session`; an established one and a session memory are not under it; an unconfirmed one past its end date appears under neither "expired" nor "not confirmed in 90 days"; `curation_due` is the same with and without ten such memories.
- [x] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_transcript_records.py -q`. Expected: FAIL (unknown origin `transcript`).
- [x] **Step 3:** Implement the interfaces above. Keep the frontmatter key order of `_render`, adding `reach` and `weight` after `origin`.
- [x] **Step 4:** Run the whole engine suite. Expected: all pass.
- [x] **Step 5:** Commit: `feat(memory): memories from a transcript carry a reach, a weight and a standing`.

### Task 2: Candidates v2 and the brief v2

**Files:**
- Modify: `plugins/memory/engine/capture.py` (`validate` and its constants), `plugins/memory/bin/mem-capture` (the brief, `recorded.txt`, a new `rules.txt`)
- Test: `plugins/memory/engine/tests/test_capture.py`, `plugins/memory/engine/tests/test_mem_capture.py`

**Interfaces:**
- Consumes: `records.REACHES`, `records.WEIGHTS` (Task 1) — `capture.REACHES` becomes that tuple.
- Produces, in `capture.py`:
  - `FORMS = ("suggestion", "recommendation")`.
  - `validate(candidates, extract_text, recorded, handles: Mapping[str, str] = {}) -> tuple[list[dict], list[dict]]` (`handles` maps `m:<handle>` to that record's claim) — as before, plus, checked after `reach` and in this order: `weight` (missing → `"medium"`; a value outside `records.WEIGHTS` → reason `weight`); `form` (missing → `"recommendation"`; any other value, `instruction` included → reason `form`); `a decision is a project record` (kind `decision` with reach `general`); `same_as` (optional; when present it must be a string that is a key of `handles`, else reason `same_as`; then `same_as mismatch` unless `records.containment` of the candidate's claim in that record's claim is at least `SAME_AS_MIN = 0.3`, a mechanical guard against a wrong match by the model; a second kept candidate naming the same record is dropped with `same_as repeated`; when valid, the `already recorded` check is skipped, because the candidate is a sighting of that record). A kept item has exactly the keys `kind`, `signal`, `reach`, `weight`, `form`, `claim`, `context`, `evidence`, `same_as` (`None` when absent).
- Produces, in `mem-capture`:
  - The project is resolved once: `--project` goes through `records.project_root` (a worktree or a subfolder resolves to the main worktree's root, as `mem` itself does), and that root is used to read the memories and, in Task 3, passed to `bin/mem` as `MEM_PROJECT`.
  - `recorded.txt`: one line per memory. Project scope, live: `m:<handle><TAB><claim>`; project scope, origin `transcript`, unconfirmed and lapsed for at most 60 days: the same line (a new sighting revives it). Global scope, live: `(general)<TAB><claim>`, with no handle, because a sighting may only be added to a memory of this project.
  - `rules.txt`: the owner's always-loaded instruction files, so that a rule the owner already wrote is not proposed again: the project's `CLAUDE.md` and `AGENTS.md` at the project root, then `CLAUDE.md` in the folder named by `CLAUDE_CONFIG_DIR`, else in `.claude` under the home folder; each under a line `## <file name>`; each file cut to 30,000 characters with a last line `[...] cut`, the project's files first; none found → an empty file. `--no-rules` leaves the file empty. The result's `extract` gains `"rules_chars": <int>` and `"rules_cut": <bool>`.
  - `validate` is called with the project handles; the result's candidates carry the new keys.
  - The brief, exact copy (`{work}` is the work folder):

```
You read the record of one coding session and find what a later session should not have to learn again.

Files in {work}:
- extract-1.txt, extract-2.txt, ...: the session in order, one event per line. Read every one of them before you write. OWNER is the human, OWNER ANSWER the human's answer to a question, AGENT the assistant, REPORT a message from a subagent or another agent (not the human), TOOL lines the assistant's tool calls, TOOL ERROR a call that failed, TOOL OK the same tool succeeding after an error. The bracket and the label at the start of a line are positions, not content.
- recorded.txt: what the memory already holds, one per line. A line starting with m: is a memory of this project, with its handle; a line starting with (general) holds in every project.
- rules.txt: the standing instructions the owner already wrote for the agent.

Write {work}/candidates.json: a JSON list of at most 5 objects, or [] when nothing qualifies. Most sessions hold one or two things worth keeping, many hold none; five is a ceiling, not a target. Order what you found by how much a later session would lose without it, and keep only the ones you would defend to the owner.

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
  "decision_with_reason" (the owner decided something and said why; the evidence must come from an OWNER or OWNER ANSWER line),
  "owner_approval" (the owner said that a way of working served them well, or asked for more of it; the evidence must come from an OWNER or OWNER ANSWER line),
  "effective_practice" (a way of planning, briefing, checking or using a tool visibly paid off in this session: it worked the first time where earlier attempts had not, saved a round, or caught something early; the evidence shows the result, not the intention).
  Without one of these there is no candidate: an idea the agent had about itself, with nothing outside confirming it, is not kept.
  Look for what worked as much as for what failed. The aim is not only fewer mistakes but better and cheaper work: a lesson may say "doing it this way tended to give a better result" and what made it work.
- "kind": "lesson" (how to work), "pitfall" (something that breaks or misleads), or "decision".
- "reach": "project" when it is about this codebase, its tools or its rules; "general" when it is about how the agent itself works in any project: how it plans, frames a request, briefs or checks a subagent, uses a skill or a plugin, verifies before claiming, or reads the owner's intent. Look for the general ones on purpose: a slip in method teaches more than the bug it caused. A general claim names no file, project or person. A project claim should name the exact file, command or setting it is about, because that is what makes it usable.
- "weight": how much following it restricts the agent or the owner, and what it costs if it is wrong: "light" (a cheap habit that can hardly hurt), "medium", or "strong" (it forbids something, or a mistake would be costly).
- "form": "suggestion" (worth trying) or "recommendation" (do this unless there is a reason not to). Never an order.
- "claim": 20 to 400 characters, in English, standing on its own in six months. Say what was seen and what it suggests, at the strength the evidence gives it and no more. This session is one sighting: write "in one session ...", "when X, Y happened, so consider ...", not "always" or "never". Say what is not known: whether it holds elsewhere, whether it may be temporary, under which condition it was seen. When the signal is a correction by the owner, report it as what the owner said and did, and weigh the other reading too: the owner may have misread the agent, and then the lesson is to explain more clearly.
- "context": one sentence on when it applies.
- "evidence": a passage copied character for character from inside one line of an extract file, without the bracket and label, 15 to 300 characters, that shows the signal. A paraphrase, or a passage that spans two lines, is rejected by a program.
- "same_as": only when a line of recorded.txt starting with m: already says this: its handle, exactly as written (for example "m:some-handle"). Then this session is one more sighting of it; still give the other keys.

Leave out: what a (general) line of recorded.txt or rules.txt already says; what the code, the git history or the project's documents already state; secrets, tokens, names of people or clients.
```

- [x] **Step 1: Write the failing tests.** In `test_capture.py`: defaults (`weight` `medium`, `form` `recommendation`, `same_as` `None`) and the exact key set of a kept item; reasons `weight` (`"heavy"`), `form` (`"instruction"`, `"order"`), `a decision is a project record`, `same_as` (a handle not in `handles`, a non-string), `same_as mismatch` (a valid handle whose claim is about something else), `same_as repeated` (two candidates naming one record: the first kept, the second dropped); a candidate whose claim equals a recorded claim is kept when its `same_as` is a valid handle and dropped as `already recorded` without it; the order of reasons for an item wrong in several ways (`reach` before `weight` before `form`). The constant `GOOD` gains `"weight": "medium", "form": "recommendation", "same_as": None`; no other existing assertion changes. In `test_mem_capture.py`: `recorded.txt` holds `m:<handle>\t<claim>` for a project memory and `(general)\t<claim>` for a global one; `rules.txt` holds the project's `CLAUDE.md` text under `## CLAUDE.md` and, with `CLAUDE_CONFIG_DIR` set to a temp folder, that folder's `CLAUDE.md`; `--no-rules` gives an empty file; a 100,000-character rules file is cut to 30,000 with the `[...] cut` line and `rules_cut` true; `--project` given as a subfolder of a git project reads that project's memories; a lapsed unconfirmed transcript memory is listed in `recorded.txt` and a retired one is not; the fake writes a candidate with `same_as` set to the project memory's handle and the result keeps it with that value; the fake receives a brief that contains `rules.txt` and `"same_as"` (the test reads the prompt argument).
- [x] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_capture.py plugins/memory/engine/tests/test_mem_capture.py -q`. Expected: the new tests FAIL.
- [x] **Step 3:** Implement. In tests the home folder and `CLAUDE_CONFIG_DIR` point to temp folders, so no real instruction file is read.
- [x] **Step 4:** Run the whole engine suite. Expected: all pass.
- [x] **Step 5:** Commit: `feat(memory): capture candidates carry a weight, a form and a sighting; the brief asks for calibrated wording`.

### Task 3: `mem-capture run --write`

**Files:**
- Modify: `plugins/memory/bin/mem-capture`, `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md`, `plugins/memory/skills/memory/SKILL.md` (one sentence beside `web, unconfirmed`: what `from transcript, unconfirmed` means and that `mem confirm` records one more sighting)
- Test: `plugins/memory/engine/tests/test_mem_capture.py`

**Interfaces:**
- Consumes: Task 1's `mem remember` flags and `mem confirm`; Task 2's kept items.
- Produces: `mem-capture run ... --write`
  - For each kept item, in order, `bin/mem` is run with `MEM_PROJECT` set to the resolved project root, the environment of the run, and the session source `session <transcript file name without extension>`:
    - `same_as` set → `mem confirm <same_as> --source "<session source>" --note "Seen again (<signal>): “<evidence>”"`; exit 0 → outcome `sighting`; exit 3 → outcome `skipped`, reason `this session already counted`.
    - else → `mem remember --kind=<kind> --claim=<claim> --context=<context> --origin transcript --reach <reach> --weight <weight> --source "<session source>" --body-file -` (the `=` form, so that a text starting with `-` is not read as an option), the body on standard input being three lines: `Signal: <signal>`, `Form: <form>`, `Evidence: “<evidence>”`; outcome `remembered` with the handle `mem` printed.
    - Exit 3 of `mem remember` means the claim already exists. Its standard output then says what happened (decided in the fix rounds of Task 1): a line `m:<handle><TAB>sighting` → outcome `sighting` with that handle (this session was added to a transcript record, live or lapsed, that says the same); `m:<handle><TAB>already counted` → outcome `skipped`, reason `this session already counted`; nothing on standard output → outcome `skipped`, reason `same claim already recorded` (the existing record is not from a transcript).
    - Any other non-zero exit of `mem remember` → outcome `skipped` with a reason: 4 `refused: a secret`, any other `mem failed (<code>)`; `bin/mem` missing or a timeout of 60 s → `mem could not run`. The next items are still applied.
  - The result file gains `"written": [{"claim": <first 80 characters>, "outcome": ..., "handle": <str or null>, "reason": <str or null>}]`; without `--write` the key is absent.
  - Standard output: the one line gains `, written <r> new, <s> sightings, <k> skipped`.
  - Exit code: unchanged (0 when a valid run wrote its result file), whatever the outcomes.
  - `--write` with a project folder that has no memory folder yet is not an error: `mem remember` creates it.

- [x] **Step 1: Write the failing tests** (fake `claude`, a temp project, `MEM_MEMORIES` set as the fixture does): one new lesson is written — `mem memories` in the project shows its claim with `from transcript, unconfirmed`, its file holds `reach`, `weight` and the three body lines, and the result's `written` has outcome `remembered` with that handle; a candidate with `same_as` naming a record that another session wrote adds this session to its sources, establishes a `medium` one, appends the `Seen again` line to its body and writes no new file; the fake of a SECOND run on the same transcript names the records the first run wrote → every outcome is `skipped` with `this session already counted`, and each record's sources, `observed` and standing are unchanged; two candidates with the same claim in one run → the second is `skipped` with `this session already counted`; a candidate whose claim equals a memory the owner's agent wrote by hand (no origin) → `skipped` with `same claim already recorded`; a candidate whose claim equals a transcript record of another session, without `same_as` → outcome `sighting`, and that record gains this session; a candidate whose evidence holds a token-shaped secret (use the shape the existing secret tests use) → `skipped` with the refusal reason and nothing written; a claim that starts with `-` is written; `--project` given as a subfolder writes into the project root's memory folder; running the same input twice → the second run's `written` has no `remembered`; without `--write` no memory file appears and `written` is absent; the summary line.
- [x] **Step 2:** Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_mem_capture.py -q`. Expected: the new tests FAIL.
- [x] **Step 3:** Implement.
- [x] **Step 4:** Run the whole engine suite. Expected: all pass.
- [x] **Step 5:** Update the README entry (what `--write` does, that it writes in the project scope only, that records start unconfirmed and how they become established), the CHANGELOG (for users: memories can now come from a session transcript; they are marked `from transcript, unconfirmed` until seen again; `mem-capture run --write`; nothing runs by itself yet) and the sentence in the `memory` skill. Run `python3 scripts/validate.py`, `python3 scripts/port.py --check` and `claude plugin validate .`.
- [x] **Step 6:** Commit: `feat(memory): mem-capture run --write records what a session taught as project memories`.

### Task 4: Check on real transcripts

Run by the controller; nothing but this file's `## Results` enters the repository.

- [x] **Step 1:** Run the new brief without `--write` on the 10 transcripts of the trial, each with its own `--project`. Record per transcript the counts kept and dropped by reason, and in total: how many runs returned the ceiling of 5 (8 of 10 before), the split by reach, weight and form, how many `same_as`, the size and cut of the rules file, the cost.
- [x] **Step 2:** Show the owner, in conversation, the claims of 2 transcripts beside the claims the first brief gave for the same transcripts, for a judgment on the wording (C11, C13, C15, C16), and every `same_as` with both claims, to be marked right or wrong. No claim text enters the repository.
- [x] **Step 3:** With the owner's word, run `--write` on two sessions of this repository's project, one after the other; list the written memories with `mem memories` and `mem curate`; note each record's sessions and standing. Then run the first one again and confirm that no record's sources, `observed` or standing changed.
- [x] **Step 4:** Record the figures in `## Results` and in ADR 0023 as a `## Review`; set the design's stage B1 as done.
- [x] **Step 5:** Commit: `docs(plan): results of the capture records stage`.

Kill criteria, read in Task 4 and at the kill read of the plugin:

| Observation | Action |
|---|---|
| A record's sources or `observed` change when a transcript already written is run again | Stop; the sighting rule is broken |
| The owner marks any `same_as` wrong | No `--write` until the guard of `validate` is tightened |
| A record is established with one session in its sources and a weight other than `light` | Re-plan the standing rule |
| More than half of the runs still return 5, or the owner judges the wording no better | One more revision of the brief, then keep the first brief's claim rules and carry only the new keys |
| A curation pass confirmed an unconfirmed transcript record | Revert the two sentences of the curator's text and block the confirm in code |

Not shown by this stage: a real second sighting weeks apart; a wrong match the guard lets through; what the 30 days do to the queue over a month.

## Results` and in ADR 0023 as a `## Review`; set the design's stage B1 as done. Kill criteria for the brief (a prompt change with no eval suite): more than half of the runs still return 5, or the owner judges the wording no better → one more revision of the brief, then keep the first brief's claim rules and carry only the new keys.
- [ ] **Step 5:** Commit: `docs(plan): results of the capture records stage`.

## Results

### The new brief on the trial's 10 transcripts, no write (2026-11-22)

| | First brief | New brief |
|---|---|---|
| Kept by validation | 47 | 40 |
| Dropped by validation | 0 | 5, all `claim length` (over 300 characters) |
| Runs that returned the ceiling of 5 | 8 of 10 | 6 of 10 |
| Reach `general` / `project` | 26 / 21 | 29 / 11 |
| Weight | — | `light` 21, `medium` 17, `strong` 2 |
| Form | — | `suggestion` 35, `recommendation` 5 |
| `same_as` | — | 0 (few of these projects hold memories) |
| Rules file | — | 24,063 to 38,974 characters, never cut |
| Cost | 0.196 USD | 0.350 USD |

The owner read the claims of two transcripts beside the first brief's claims and judged the new wording better (2026-11-22). Three changes followed, agreed with the owner: a claim may run to 400 characters; a project claim names its file or command (the first run had blurred them); and, because 6 of 10 runs still returned 5, the one revision the kill criterion allows: the brief asks to order what was found and keep only what it would defend. The owner also asked for positive lessons: signals `owner_approval` and `effective_practice` (design C21). The 10 transcripts were not run again with this last text.

### The first real write (2026-11-22, with the owner's word)

Two sessions of this repository's project, one after the other, into its project memory (a copy of the memory folder was kept first), run with the code and the brief of the commit that added the two positive signals.

| Run | Kept | Written | Sightings | Skipped | Cost (USD) |
|---|---|---|---|---|---|
| Session A | 5 | 5 new | 0 | 0 | 0.050 |
| Session B | 5 | 5 new | 0 | 0 | 0.040 |
| Session A again | 4 (1 dropped) | 1 new | 0 | 3, `this session already counted` | 0.054 |

- The sighting rule held: on the second run of session A the model named three of the records the first run had written (`same_as`), all three were refused as already counted, and no existing memory file changed (compared by content before and after). The owner marked the three pairs as correct matches (2026-11-22).
- A second run of the same session is not idempotent in what it adds: the model chose one lesson the first run had not, and it was written as a new record. Stage B2 reads each part of a session once, from an offset, so this does not arise there; a manual rerun can add to a session's records.
- Of the 11 records, both positive signals appeared (`effective_practice`, `owner_approval`).
- Session B's records about the owner's rulings say again, in other words, what the agent had already recorded in the global scope during that session: the "already recorded" list did not stop them. A duplicate worded differently is still not caught.
- Weight `light` establishes a record at its first session, by C20: 7 of the 11 are established at once, including lessons drawn from one comment of the owner. The owner confirmed this on 2026-11-22: a correction of theirs may be `light`.

Engine suite at the end of the stage: `1409 passed, 5 skipped`; `python3 scripts/validate.py` and `claude plugin validate .` pass.

Kill criteria read: no record changed on a rerun (holds); no `same_as` marked wrong (3 of 3 marked right by the owner); no record established with one session and a weight other than `light` (holds by construction, checked on the written files); the ceiling: 6 of 10 before the revision, not measured after it; the curator's text: no curation pass has run since.
