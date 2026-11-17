# Memory plugin, stage 5 (curation) Implementation Plan

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

## Results

Filled as tasks complete.
