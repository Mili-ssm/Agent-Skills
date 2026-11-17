# Memory plugin, stage 3 (orient) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every session and subagent starts knowing that the memory exists, how to ask it, and where each kind of thing to remember goes, in a few hundred characters.

**Architecture:** one new command, `mem session-index`, builds the text from counts and the project's memories; three hooks deliver text: `SessionStart` runs the command, `SubagentStart` and `PreCompact` print fixed text from shell scripts that start no interpreter. Nothing is cached: the session index is built once per session.

**Tech Stack:** Python 3.12, `uv`, Bash, `pytest`.

**Spec:** [../specs/2026-11-17-memory-plugin-design.md](../specs/2026-11-17-memory-plugin-design.md), sections "Hooks" and "What goes where"; stage 3 of [2026-11-17-memory-plugin.md](2026-11-17-memory-plugin.md). Measured in stage 2: without a text at session start an agent ignored the plugin.

## Global Constraints

- Nothing outside `plugins/memory/` and `docs/` changes; the owner's note repository is never written.
- Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (447 passed, 1 skipped before this stage).
- Every hook script exits 0 whatever happens and prints nothing on failure. `SubagentStart` and `PreCompact` scripts call no program except shell builtins and `cat`/`printf`.
- The session index is at most 1,500 characters; the subagent text at most 300. Both are plain English.
- **Where things go (owner, 2026-11-17), stated in the index in these terms:** personal matters and the owner's preferences go to Claude Code's auto memory; discoveries, facts and assumptions go to the plugin (`mem remember`); the project's current situation or special conditions go to both.
- Note counts come from counting files, never from parsing them: the index must not read the notes.
- Public repository: no home-directory path or private name in any file. Commit after each task on `feat/memory-plugin`; do not push.

## Review Focus

1. No store set and not in a git repository: the index still prints the rules, with no count lines, and exits 0.
2. A project with 40 memories: the index stays under 1,500 characters and says how many are not listed.
3. A broken memory file: skipped silently in the index (search reports it).
4. A claim of 400 characters: cut to 100 with an ellipsis in the index.
5. The hook runs where the store path contains spaces.

---

### Task 1: `mem session-index`

**Files:**
- Modify: `plugins/memory/engine/mem.py`
- Create: `plugins/memory/engine/tests/test_session_index.py`

**Interfaces:**
- `session_index(store: Path | None, project: Path | None, memories: Path | None, today: datetime.date, *, limit: int = 8) -> str` in `mem.py`, and the command `mem session-index`, which resolves the three folders as `remember` does, never fails for a missing store or project, and prints the text.
- The text, in this order (lines 1 to 5 are fixed and always present):

```
memory: notes and memories are searchable with the `mem` command (skill: memory).
- Before researching, re-reading or dispatching a researcher: mem search "<question in English>". Put what applies into a subagent's brief.
- To remember: the owner's preferences and personal matters -> auto memory. Discoveries, facts and assumptions (a decision, a constraint, a pitfall, a finding) -> mem remember, claim in English. The project's situation or special conditions -> both.
- A line marked [memory: ...] is experience, not fact: keep its label and date when you pass it on.
- Open a result with mem show <handle>.
```

  then, when a store is set and is a folder: `store: N notes` (files matching `literature/*/*.md` and `knowledge/*/*.md` except `README.md`, plus `research/*/README.md`); when a memories folder exists: ` · G global memories` appended to that line, or the line `global memories: G` when there is no store; when the project has live memories: `this project: P memories` and, under it, up to `limit` lines `  m:<handle> [<kind>, <created>] <claim cut to 100 characters with … when longer>`, ordered by `observed` descending, then `created` descending, then handle; when more exist, a last line `  … and K more: mem search "<words>" --scope memories`. Only live memories are counted and listed. If the whole text would exceed 1,500 characters, memory lines are dropped from the end and K grows until it fits.

- [ ] **Step 1: Write the failing tests**: the five fixed lines are present verbatim with no store and no project; the count line with the fixture store (count equals the number of such files in the fixture); global and project counts; ordering by `observed` then date; a 400-character claim is cut to 100 characters plus `…`; 40 memories give a text of at most 1,500 characters whose last line starts with `  … and ` and whose K plus the listed lines equals 40; a broken memory file is not listed and nothing is written to stderr; a refuted memory is neither counted nor listed; `mem.main(["session-index"])` returns 0 with `MEM_STORE` unset and outside git.
- [ ] **Step 2:** Run them. Expected: fail, unknown command.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): add the session index`.

### Task 2: The three hooks

**Files:**
- Create: `plugins/memory/hooks/session-index.sh`, `plugins/memory/hooks/subagent-start.sh`, `plugins/memory/hooks/pre-compact.sh`
- Modify: `plugins/memory/hooks/hooks.json`, `plugins/memory/engine/tests/test_plugin_shell.py`

**Interfaces:**
- `hooks.json`: `SessionStart` keeps `session-env.sh` and gains `session-index.sh` (timeout 10); new `SubagentStart` and `PreCompact` entries (timeout 5), all in the shape already used in the file.
- `session-index.sh`: exports `MEM_STORE` from `CLAUDE_PLUGIN_OPTION_STORE` and `MEM_MEMORIES` from `CLAUDE_PLUGIN_OPTION_MEMORIES` when they are non-empty, then runs `"<plugin root>/bin/mem" session-index` with stderr discarded; prints what it prints; exits 0 also when `mem` fails or `uv` is missing (then prints nothing).
- `subagent-start.sh`: prints exactly one JSON object, `{"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": "<text>"}}`, where the text is: `memory: notes and memories are searchable with the mem command. Before researching or re-reading: mem search "<question in English>", then mem show <handle>. A line marked [memory: ...] is experience, not fact. Report what is worth remembering to your caller.` (under 300 characters; the script holds it as a literal).
- `pre-compact.sh`: prints `Keep in the summary: the path of the active plan file, and every decision, constraint, pitfall or finding of this session that was not yet recorded with mem remember, marked "not yet recorded".`

- [ ] **Step 1: Write the failing tests** in `test_plugin_shell.py`: `session-index.sh` with `CLAUDE_PLUGIN_OPTION_STORE` set to a store whose path has a space prints the five fixed lines and the count line, exit 0; with `PATH` lacking `uv` (skip where `uv` is in a system folder) prints nothing, exit 0; `subagent-start.sh` prints valid JSON whose `additionalContext` is under 300 characters and contains `mem search`; `pre-compact.sh` prints the exact line; all three are executable; `hooks.json` parses and names the four scripts.
- [ ] **Step 2:** Run them. Expected: fail, files missing.
- [ ] **Step 3:** Write the scripts and the `hooks.json` entries.
- [ ] **Step 4:** Run the whole suite; `python3 scripts/validate.py`; `claude plugin validate plugins/memory`. Expected: all pass.
- [ ] **Step 5:** `git add` by name; `git ls-files -s plugins/memory/hooks/*.sh` shows mode `100755`. Commit: `feat(memory): add the session, subagent and compaction hooks`.

### Task 3: Skill, design and stage plan follow the owner's routing

Written by the main conversation.

- [ ] **Step 1:** `SKILL.md`: the "what goes where" rule in the owner's three lines; exact duplicates are the only ones blocked, the rest are kept for a later curation pass.
- [ ] **Step 2:** The design's "What goes where" table and decisions table (two new owner decisions: the routing; duplicates are curated in later passes, triggered by time or number of writes, possibly by a small-model subagent); the stage plan's stage 5 gains that trigger.
- [ ] **Step 3:** Commit: `docs(memory): record the owner's routing of what to remember`.

### Task 4: Measurements

Run by the main conversation; "Results" records counts, times and pass or fail only. Each agent trial is one run.

- [ ] **Step 1:** Time `session-index.sh` ten times against the owner's store (read-only) and a project with 10 memories; record the median. Expected: under 1 s. Time `subagent-start.sh` with ten started at once. Expected: under 0.1 s each.
- [ ] **Step 2:** A headless session with the plugin loaded: asked to quote the first line it was given about memory; a subagent asked the same. Expected: both quote their text.
- [ ] **Step 3:** Routing, three requests in Spanish in fresh sessions: a personal preference; a discovery about the project; a current condition of the project. Expected: auto memory only; `mem remember` only; both. Record which tools each used.
- [ ] **Step 4:** Recall unasked: a fresh session given a task that a stored memory bears on. Expected: `mem search` before acting.
- [ ] **Step 5:** Tick stage 3 in the stage plan; remove the trial folders left under the Claude configuration folder.

## Results

Filled as tasks complete.
