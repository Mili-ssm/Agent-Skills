# Memory plugin, stage 5 (curation) Implementation Plan

Status: done · merged in #117, 2026-11-17 · boxes left unticked during execution are not open work (checked 2026-11-19).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** memories stop piling up: a pass, due after a number of writes or a period, lists what needs a decision (probable duplicates and contradictions, expired memories, memories seen often), and one command per decision carries it out.

**Architecture:** the queue is computed on demand by `mem curate` from the memory files, with the containment score of stage 6 between claims; nothing runs in the background and nothing is rewritten without a command. Each action changes one or two files and keeps what it replaces: a memory is marked, never deleted. A subagent on a small model can run the pass and propose actions; the main agent or the owner applies them.

**Tech Stack:** Python 3.12, `uv`, `pytest`.

**Spec:** [../specs/2026-11-17-memory-plugin-design.md](../specs/2026-11-17-memory-plugin-design.md), section "Curation"; owner decision D14 (only a perfect duplicate is refused at writing; the rest is curated in later passes, started by time or by a number of writes, possibly by a small-model subagent); stage 5 of [2026-11-17-memory-plugin.md](2026-11-17-memory-plugin.md).

## Global Constraints

- Nothing outside `plugins/memory/` and `docs/` changes. Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (510 passed, 3 skipped before this stage).
- No action deletes a file. A memory leaves search by its `status` (`refuted`, `superseded`, or the new `forgotten`), and `mem search --all-memories` still shows it.
- Every action works on project memories and on global ones; the guards of stage 2 apply unchanged (a store without its marker, a memories folder inside it, the forbidden-terms list for anything written to the global scope).
- Every action rewrites a file as `observe` does: unknown keys kept, a temporary file and `os.replace`.
- The queue never calls a model and never reads the notes.
- Public repository: no home-directory path or private name. Commit after each task on `feat/memory-plugin`; do not push.

## Review Focus

1. A pair listed as probable duplicates that is in fact a claim and its negation: the queue must present it as "same or opposite", never as "duplicate".
2. Merging a memory into itself, or into a memory of the other scope: refused.
3. An action on a handle that exists in both scopes: the project one, as elsewhere; `--global` reaches the other.
4. A memory superseded by one that is later forgotten: both stay hidden; nothing loops.
5. `curate` with no memories, no store and outside git: prints nothing and returns 0.

---

### Task 1: List, queue and actions

**Files:**
- Modify: `plugins/memory/engine/records.py`, `plugins/memory/engine/mem.py`
- Create: `plugins/memory/engine/tests/test_curation.py`

**Interfaces:**
- `records.STATUSES` gains `forgotten`. `records.update(memory: Memory, today: datetime.date, **changes) -> Memory`: rewrites the file with the given frontmatter keys changed or added (a value of `None` removes the key), keeping the body and unknown keys; `observe` is reimplemented on it.
- `records.pairs(memories: Sequence[Memory], today: datetime.date, *, tokenize) -> list[tuple[Memory, Memory, float]]`: every pair of live memories whose claims contain each other with a score of at least `records.STRONG` in either direction (the larger of the two directions is the score), ordered by score descending then handles.
- `mem memories [--global | --all] [--kind K] [--dead]`: one line per memory, `m:<handle>\t[<kind>, observed N, <created>]\t<claim>`, project scope by default, `state` first then newest first; `--dead` adds the ones that are not live, with their status in the bracket.
- `mem curate [--global | --all]`: prints the queue in four blocks, each only when it has items, and nothing at all when the queue is empty:

  ```
  same or opposite? (decide: mem merge <keep> <drop>, or keep both and say so in the body)
    m:<a>  <claim>
    m:<b>  <claim>
  expired (decide: mem forget <h>, or mem remember again with a new date)
    m:<h>  valid until <date>  <claim>
  seen 3 times or more: general enough for a note? (mem promote <h>)
    m:<h>  observed N  <claim>
  not confirmed in 90 days (decide: mem confirm <h> or mem forget <h>)
    m:<h>  <created>  <claim>
  ```

  `mem curate --done` records the pass: it writes today's date to a file `.curated` in each memory folder it covers.
- Actions, each printing one line `m:<handle>\t<what changed>` and returning 0, or a `mem:` message and 2 for an unknown handle or a refused case:
  - `mem confirm <h>`: `observed` plus 1 and `last_observed` (the same as `observe`, which stays as an alias).
  - `mem refute <h> [--because TEXT]`: `status: refuted`, `refuted` date, and the text appended to the body under a line `Refuted <date>:`.
  - `mem supersede <old> <new>`: `<old>` gets `status: superseded` and `superseded_by: <new>`; both must exist in the same scope.
  - `mem merge <keep> <drop>`: `<keep>.observed` becomes the sum of both, `<drop>` is superseded by `<keep>`, and `<drop>`'s body is appended to `<keep>`'s under a line `Merged from m:<drop> on <date>:` when it is not empty. Refused for the same handle or different scopes.
  - `mem forget <h> [--because TEXT]`: `status: forgotten`, `forgotten` date, the reason appended to the body.
  - `mem promote <h>...`: writes nothing; prints a draft for a global memory: a line `Draft for: mem remember --global --kind lesson --claim "…"`, then each source memory's claim and context, then `Rewrite the claim in general terms, with no name of a project, system, client or person, before you run it.`

- [ ] **Step 1: Write the failing tests** in `test_curation.py`: `update` keeps unknown keys and the body, removes a key given as `None`; `pairs` lists a claim with its near-copy and with its negation, not two unrelated claims, and no pair with a dead memory; `memories` order, `--kind`, `--dead`, `--global`; `curate` prints each block with the exact header for a seeded case and prints nothing for an empty queue; `curate --done` writes the date file; each action's effect on the files and its printed line; the refused cases of Review Focus 2 and 3; a refuted, a superseded and a forgotten memory are absent from `mem search` and present with `--all-memories`; actions on a store without its marker are refused with the stage 2 message.
- [ ] **Step 2:** Run them. Expected: fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): list, queue and curate memories`.

### Task 2: When a pass is due

**Files:**
- Modify: `plugins/memory/engine/mem.py`, `plugins/memory/engine/tests/test_session_index.py`

- `records.curation_due(memories: Sequence[Memory], last_pass: datetime.date | None, today: datetime.date) -> int`: the number of live memories created after `last_pass` (all of them when it is `None`), returned only when it is at least 10, or at least 1 and `last_pass` is 14 days old or older (or `None` and the oldest live memory is 14 days old); otherwise 0.
- The session index's first line gains, after the counts, ` Curation due: N new memories (mem curate).` when the number for the project or for the global scope is above 0 (N is their sum).

- [ ] **Steps:** failing tests for the four cases of the rule and for the index line; implement; whole suite; commit `feat(memory): say in the session index when a curation pass is due`.

### Task 3: The curation skill and a curator subagent

Written by the main conversation (prompt text).

- `plugins/memory/skills/memory-curation/SKILL.md` (N1, N2): when to run a pass (the index says it is due, or the owner asks); the procedure (`mem curate`, read each pair with `mem show`, decide, apply one action per item, `mem curate --done`); the rules (a claim and its negation are not duplicates: keep both or refute one with a reason; never merge across scopes; promote only what would hold in any project, rewritten without names; when in doubt leave it and say so).
- `plugins/memory/agents/memory-curator.md`: a read-and-propose subagent on a small model that runs the queue and returns a table of proposed actions with one line of reason each; it applies nothing. The main agent applies what it agrees with.
- One trigger eval case for the skill at 2 runs; `README.md` gains the commands.

### Task 4: Measurements

- [ ] **Step 1:** On a scratch project seeded with 12 memories (2 near-copies, 1 pair of opposites, 2 expired, 1 observed four times, 6 unrelated): `mem curate` lists exactly the seeded items.
- [ ] **Step 2:** A headless session told that a pass is due: it runs the queue, handles the pair of opposites without merging them, and ends with `mem curate --done`. Two runs.
- [ ] **Step 3:** The curator subagent on the same project: its proposals name the right action for each seeded item. Two runs.
- [ ] **Step 4:** The routing and recall trials still pass. Record the figures; tick stage 5.

## Amendments after the pre-mortem (2026-11-17)

These override the tasks above. Task 1 is already committed (`0d645ae`); the items below change it.

### A. Nothing a pass does is final
- Every action that changes a memory first appends one JSON line to `.curation-log` in that memory's folder: `{"t": <UTC timestamp>, "action": <name>, "handle": <h>, "before": <the file's whole previous text>}`.
- `mem restore <h>` puts back the `before` text of the newest log line for that handle (and logs that too); it prints `m:<h>\trestored to before <action> of <date>`; with no line for the handle it exits 2.
- `mem merge` refuses, unless `--force`, when the two claims differ by a negation word (`not`, `no`, `never`, `cannot`, `without`, or a word ending in `n't`) or by any token that is only digits or digits with dots: `mem: these claims differ in <words>: they may be opposites or different versions; use --force to merge anyway.`, exit 2.
- In the "same or opposite?" block each memory's line is `  m:<h>  [<kind>, <created>]  <claim>`, and after the pair a line `  differ in: <the tokens that occur in only one of the two claims, digits included>`.

### B. The queue remembers what was decided
- `mem distinct <a> <b>`: records in both memories the frontmatter key `distinct_from` (a list of handles); that pair no longer appears. Prints `m:<a>\tkept apart from m:<b>`.
- `mem promote --no <h>`: records `promote: "no"`; the memory leaves the "seen 3 times or more" block.
- A new block, before the others: `written again after being refuted (decide: mem refute <h>, or mem distinct <a> <b> if it is a different claim)`, for a live memory paired with a refuted one.

### C. Rules that do not forget what is still true
- The "not confirmed in 90 days" block counts from the later of `created` and `last_observed`, and leaves out the kinds `constraint`, `decision` and `state`. `Memory` parses `last_observed`.
- A `state` memory written without `--valid-until` expires 30 days after `created`.

### D. When a pass is due, and what a pass covers
- `mem curate` covers both scopes by default (`--project` or `--global` restricts it), and `--done` records exactly the scopes it covered. The date of the last pass is kept outside the memory folders, in `data_dir(env)/curated.json` (`{<resolved folder>: <ISO date>}`), so a synced folder gets no file that conflicts.
- `records.curation_due` as in Task 2; in addition a pass is due when a live memory is past `valid_until` (those are counted in N). A memory created on the day of the last pass does not count as new.
- The session index line is ` Curation due: N items (run mem curate after the current task).`

### E. Use
- The skill tells an agent to run `mem confirm m:<handle>` when a memory it used proved right, and `mem refute` with a reason when it proved wrong: that is what keeps the 90-day rule honest.
- Handles are accepted with or without the `m:` prefix in every command.

## Results

Measured on 2026-11-17; counts and pass or fail only. Agent trials are one run each unless a count is given.

| Item | Result |
|---|---|
| Tasks 1 and 2 with the amendments | Done; one review round and two fix rounds. Suite: 564 passed, 3 skipped |
| The queue on a seeded project (a pair of opposites, a near-copy, two versions, an expired finding, a memory seen four times, a constraint and a decision) | Lists the first five with their `differ in:` lines; leaves the constraint and the decision alone |
| `merge` | Refuses the opposites (`never`; `works` against `fails`) and the versions (`0.4`/`0.5`, `v2`/`v3`); merges the near-copy |
| Undo | Three actions on one memory, then three `restore`: the file equals the original byte for byte; a fourth exits 2 |
| A store without its marker | Six curation commands run from inside a real one changed nothing (`git status --ignored` identical) |
| A full pass by the main agent (Sonnet), told a pass is due | Refuted the false one of the opposites with a reason, merged the near-copy, kept the two versions apart, forgot the expired finding; touched neither the constraint nor the decision |
| The curator subagent (Haiku) | Proposed `leave` for the opposites (nothing in the project says which is right), `merge` for the near-copy, `distinct` for the versions; applied nothing |
| Trigger cases | `memory` 6 of 6; `memory-curation` 5 of 6 with its first description, 6 of 6 after rewriting it to open with the verb and the owner's words |
| Routing and recall trials after this stage | 9 of 9 and 8 of 8 |

Review round 1 found, and the fix rounds closed: undo that toggled between the last two states instead of walking back; a `merge` that combined `v2` with `v3` and `works` with `fails`; a log line cut by a Unicode line separator; an expired memory, a promoted one and a pair already told apart that came back in every pass; a "Curation due" line that never went away.

Not measured: a pass on real memories (none exist yet); what the main agent does with the curator's table when it has many rows; opposites said in other words, which `merge` cannot catch and the skill tells the agent to read for.
