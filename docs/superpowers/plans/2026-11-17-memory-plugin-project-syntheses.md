# Project syntheses with freshness stamps: experiment plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find out whether a few long-lived documents in a project's `.memory/`, each part stamped with the commit it was written at, let an agent find its way in a project with fewer reads and without trusting a part whose files changed.

**Architecture:** A new module `plugins/memory/engine/project_syntheses.py` owns the file format, the stamp and the git comparison; `mem.py` only wires commands, `show`, `curate` and the session text to it. Project syntheses live in `<project>/.memory/syntheses/<name>.md` and never in the store. Nothing is created at `mem init`: the first part written creates the file.

**Tech Stack:** Python 3.12+, single-file scripts run with `uv run --script`, pyyaml, pytest; git through `subprocess` with a timeout.

**Spec:** `docs/superpowers/specs/2026-11-17-memory-plugin-design.md` (decisions D21, D24 and the new D25 added by Task 1).

**Status:** stage plan for an experiment; not started. Result goes in `## Results` at the end of this file.

## Decisions already taken (owner, 2026-11-17)

| Decision | Reason |
| --- | --- |
| A fixed list of names: `organization`, `plans`, `pending`, `conventions` | A fixed vocabulary organizes notes as they appear, without a model inventing a structure per project |
| No file is created at init; the curator writes a part when the first memory belongs there | An empty template shows up in searches, says nothing and invites a model to fill it |
| A part names the paths it describes, never a file listing or line numbers | Listings and line numbers go stale with every edit; `git` already lists files |
| A part carries the date and commit of its last update; it is reported as possibly stale when commits or uncommitted changes touch its paths since | The reader must know when to check the code instead of trusting the text |
| No scratch area for messages between agents in `.memory/` | That is not memory; reports and the session's temporary folder already carry it |
| Writing a project synthesis is curation work (D21) | Few simple commands while working |

## Global Constraints

- Requires-python stays `>=3.12,<3.15`; no new dependency.
- Project syntheses hold what is specific to the project: forbidden terms do not apply (they guard the global scope, D23); the secret check does (`_refuse_secret`, exit 4).
- Every git call: `subprocess.run([...], cwd=project_root, capture_output=True, text=True, check=False, timeout=2)`; a failure, a timeout or a missing git gives the state `unknown`, never an error exit.
- `mem show p:…`, `mem project-synthesis list` and `mem curate` are the only commands that run the freshness comparison; the session-start hook runs no extra git command.
- Git runs in the working tree the session is in (`git rev-parse --show-toplevel` from the current directory), not in the main worktree, with `GIT_LITERAL_PATHSPECS=1` in its environment.
- The repository is public: no home paths, private repository names or note titles in code, tests, docs or commits.
- Vocabulary: "project synthesis" (the file), "part" (a `## ` section), "stamp" (the last line of a part), "freshness" (`fresh`, `changed`, `unknown`).
- Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (745 passed, 4 skipped before this plan); `python3 scripts/validate.py` before every commit.

## File format

```markdown
---
title: Organization
created: 2026-11-17
updated: 2026-11-17
---

## Where the engine lives

The command is one script; records and syntheses are separate modules …

Covers: plugins/memory/engine/, plugins/memory/bin/ | updated 2026-11-17 at 9566ce4f8735
```

The stamp is the last non-empty line of every part: `Covers: <path>[, <path>…] | updated <YYYY-MM-DD> at <12 hex digits or "no-commit">`. Paths are relative to the project root, use `/`, may be files or folders, and may not contain `,` or `|` nor point into `.memory/`. The tool writes the stamp; the body a model passes must not contain one.

## Review Focus

- A project that is not a git repository, or git missing: every command works and reports `unknown`.
- A stamp's commit that no longer exists (rebase, shallow clone): `unknown`, not `fresh`.
- A path in `Covers:` that was deleted or renamed: `changed`.
- A path that leaves the project (`../x`, absolute), is empty, holds `,` or `|`, or is inside `.memory/`: refused at writing, exit 2.
- A session in a linked worktree or after a branch switch: the comparison is against the files in front of the agent, so a part written on another branch whose files differ here is `changed`.
- A part covering `.`: writing another part (a change inside `.memory/`) does not make it `changed`.
- A body that contains a `## ` heading or a `Covers:` line: refused at writing, exit 2, because it would split or mis-stamp the part.

---

### Task 1: Format, stamp and freshness (module only)

**Files:**
- Create: `plugins/memory/engine/project_syntheses.py`
- Test: `plugins/memory/engine/tests/test_project_syntheses.py`
- Modify: `docs/superpowers/specs/2026-11-17-memory-plugin-design.md` (add row D25 above D24, wording of "Decisions already taken" in one row)

**Interfaces (produces):**

```python
NAMES: tuple[str, ...] = ("organization", "plans", "pending", "conventions")
class Stamp(NamedTuple): paths: tuple[str, ...]; date: datetime.date; commit: str | None
class Part(NamedTuple): handle: str; heading: str; body: str; stamp: Stamp; line: int
FRESH, CHANGED, UNKNOWN = "fresh", "changed", "unknown"
class ProjectSynthesisError(ValueError): ...

def folder(memory_dir: Path) -> Path                      # memory_dir / "syntheses"
def load(memory_dir: Path) -> dict[str, list[Part]]       # name -> parts, only files that exist; a broken file raises
def head_commit(project_root: Path) -> str | None         # 12 hex digits of HEAD, None without git
def write_part(memory_dir: Path, project_root: Path, name: str, heading: str, body: str,
               paths: Sequence[str], today: datetime.date) -> str   # creates the file or adds/replaces the part; returns its handle
def confirm_part(memory_dir: Path, project_root: Path, name: str, handle: str, today: datetime.date) -> None  # new stamp, same text
def freshness(worktree: Path, stamp: Stamp) -> str          # FRESH | CHANGED | UNKNOWN
def describe(state: str) -> str
```

- A part's handle is its heading lower-cased with runs of non-alphanumerics turned into `-`; `write_part` with a heading whose handle exists replaces that part (keeping its place), else appends.
- Reuse `syntheses._scan` for headings outside code fences and `syntheses._write` for the atomic write; do not change `syntheses.py`.
- `freshness`: `unknown` when `stamp.commit` is None, when `git cat-file -e <commit>^{commit}` fails, or on any git failure or timeout. Else `changed` when `git diff --name-only <commit> -- <paths>` (the commit against the files on disk, so commits, branch switches and uncommitted edits all count) or `git status --porcelain --untracked-files=all -- <paths>` (new files) names any file outside `.memory/`, or when a covered path does not exist; else `fresh`.
- `describe` returns exactly: `fresh: its files are as they were when it was written`; `possibly stale: its files changed since it was written; check them before relying on it`; `unknown: not a git project or its commit is gone; check the files`.
- A part is addressed by its exact handle (as `s:` parts are); there is no prefix matching.

- [ ] **Step 1: Write the failing tests** (a `git_project` fixture: `git init`, one commit of `src/a.py` and `docs/p.md`, with `user.name`/`user.email` set by `-c`):
  - `test_first_part_creates_the_file_with_a_stamp`: after `write_part(..., "organization", "Where the engine lives", "Text.", ["src/"], date(2026, 11, 17))` the file's last line is `Covers: src/ | updated 2026-11-17 at <head_commit>` and `load` returns one part with handle `where-the-engine-lives`.
  - `test_same_heading_replaces_and_keeps_order`, `test_unknown_name_is_refused` (`"notes"` raises), `test_bad_paths_are_refused` (parametrized: `[]`, `["../x"]`, `["/etc"]`, `[""]`, `["a,b"]`, `["a|b"]`, `[".memory/x"]`), `test_body_with_a_heading_or_a_stamp_is_refused`.
  - `test_fresh_then_changed_by_a_commit_then_fresh_after_confirm`: fresh; commit a change to `src/a.py` gives `CHANGED`; a commit touching only `docs/p.md` does not count; `confirm_part` gives `fresh` and leaves the body bytes equal.
  - `test_uncommitted_change_new_file_and_deleted_path_are_changed`, `test_a_branch_whose_files_differ_is_changed` (write on `main`, switch to a branch where `src/a.py` differs), `test_a_part_covering_the_root_stays_fresh_when_another_part_is_written`, `test_no_git_and_missing_commit_are_unknown` (a plain folder; a stamp with commit `0` * 12), `test_git_timeout_is_unknown` (monkeypatch `subprocess.run` to raise `subprocess.TimeoutExpired`), `test_describe_texts` (the three exact strings above).
- [ ] **Step 2: Run them and see them fail** (`pytest plugins/memory/engine/tests/test_project_syntheses.py -q`: import error).
- [ ] **Step 3: Implement the module.**
- [ ] **Step 4: Run the whole suite; all pass.** Add row D25 to the design document.
- [ ] **Step 5: Commit** `feat(memory): project synthesis format with a freshness stamp`.

### Task 2: Commands and reading

**Files:**
- Modify: `plugins/memory/engine/mem.py` (a new `project-synthesis` command, added to `_NO_STORE_NEEDED`; a `p:` branch in `cmd_show` and in `main`'s store check)
- Test: `plugins/memory/engine/tests/test_project_synthesis_commands.py`
- Modify: `plugins/memory/README.md` (one paragraph under the syntheses section)

**Interfaces (consumes Task 1; produces the command surface):**

| Command | Result |
| --- | --- |
| `mem project-synthesis add <name> "<heading>" --paths a,b --body-file F` | writes or replaces the part; prints `p:<name>#<handle>` |
| `mem project-synthesis confirm p:<name>#<handle>` | new stamp, text unchanged; prints `p:<name>#<handle>\tconfirmed at <commit>` |
| `mem project-synthesis list` | one line per part: `p:<name>#<handle>\t<state>\t<heading>`; prints nothing and exits 0 when there is none |
| `mem show p:<name>` | outline: one line per part as in `list` |
| `mem show p:<name>#<handle>` | `== p:<name>#<handle> (<describe text>)`, then the part's heading, body and stamp |

- A separate command, because `mem synthesis add` already takes `s:HANDLE --section` and needs a writable store, and `--project` already means a registered project's name in `show` and `search`.
- The `.memory/` folder comes from the existing `records.project_root` / `records.project_dir`; outside a project the command exits 2 with `mem: not inside a project`.
- Neither the command nor `mem show p:…` needs a store: `main` must not refuse them when none resolves, and they never write to one. `mem show` given both `p:` handles and others still needs the store for the others.
- `add` runs `_refuse_secret` on the body (exit 4); it does not run `_check_terms`.
- An unknown name or part exits 2 and names the parts that exist.

- [ ] **Step 1: Write the failing tests**: one per table row with the exact output; `test_show_marks_a_part_whose_files_changed` (commit after writing, then the header line contains `possibly stale: its files changed`); `test_outside_a_project_exits_2`; `test_a_secret_in_the_body_exits_4_and_writes_nothing`; `test_the_command_and_show_work_without_a_store` (`MEM_STORE` unset, `XDG_*` pointed at an empty folder; `show p:organization` exits 0); `test_the_store_is_untouched` (snapshot of the store before and after `add`).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Whole suite passes; `python3 scripts/validate.py` passes.**
- [ ] **Step 5: Commit** `feat(memory): commands to write, confirm and read project syntheses`.

### Task 3: Curation and the session text

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`cmd_curate` project branch, `session_index`)
- Modify: `plugins/memory/skills/memory-curation/SKILL.md`, `plugins/memory/agents/memory-curator.md`, `plugins/memory/skills/memory/SKILL.md`
- Test: `plugins/memory/engine/tests/test_project_synthesis_curation.py`

**Interfaces:**

- `mem curate` (the form the curator and the skill run) and `mem curate --project` gain two blocks, printed only when they have rows; `--global` and `--notes` do not:
  - `-- project syntheses: possibly stale --` with `p:<name>#<handle>\t<describe text>` for every part not `fresh`.
  - `-- project syntheses: none yet --` with the single line `<N> active memories and no project synthesis: organize them (see the memory-curation skill).` when no file exists and the project has 5 or more active memories.
- `session_index` appends one sentence to its first line (after `This project:` and `Curation due:` when present, and also when the project has no memories), only when at least one project synthesis exists: `Project syntheses: p:organization p:pending (read: mem show p:<name>; each part says whether its files changed since it was written).` with the names that exist, in `NAMES` order. No git call.
- `memory-curation/SKILL.md` gains a section "Project syntheses" (at most 15 lines): which memory kinds go to which name (`state` → `pending` or `plans`; `decision`, `constraint` → `conventions` or `organization`; `pitfall`, `lesson` stay memories unless they describe how the project is organized); read the code a part will describe before writing it; name folders in `--paths` rather than many files; cite memories as `m:<handle>` in the body; for a possibly stale part, check the files, then `add` again with the corrected text or `confirm` when it still holds; never list files or line numbers.
- `agents/memory-curator.md`: one line saying its proposals include project synthesis parts to write, correct or confirm (it still changes nothing).
- `skills/memory/SKILL.md`: one line under reading: a `p:` part marked possibly stale is a hint to check the files, not a fact.

- [ ] **Step 1: Write the failing tests**: the two blocks with exact text (a stale part; five memories and no synthesis; four memories prints nothing); `test_session_index_names_existing_syntheses_only`; `test_session_index_names_them_in_a_project_without_memories`; `test_the_list_stays_within_its_1500_characters`; `test_session_index_runs_no_git` (monkeypatch `subprocess.run` in `project_syntheses` to fail the test if called); `test_session_index_without_syntheses_is_unchanged` (text equal to the current one).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the code and the three prompt edits.**
- [ ] **Step 4: Whole suite and `scripts/validate.py` pass.**
- [ ] **Step 5: Commit** `feat(memory): curation and session text for project syntheses`.

### Task 4: Measure

**Files:**
- Create: `plugins/memory/evals/project_syntheses/run_trials.py` (modeled on `plugins/memory/evals/recall/run_trials.py`: headless sessions, stream-json, temporary folder, cleanup)

**Design, fixed before any run:**

- Project under test: a copy of this repository at the branch's commit, in a temporary folder with its own `git init` and one commit (a real project, because a toy one made an earlier recall trial meaningless). Left out of the copy, because they hold the answers: `CLAUDE.md`, `docs/superpowers/plans/`, `plugins/memory/evals/`.
- Questions: the script holds 8 candidate questions in Spanish whose answer is a path that takes several steps to find (which file a behaviour is decided in, reached through a caller, not a name to grep). A pilot runs each twice without syntheses; the 4 with the highest median tool calls are the orientation cases, and the pilot stops the experiment when fewer than 4 have a median of 4 calls or more (the measure could not show a saving).
- Syntheses: written once by one headless Sonnet session told to load `memory-curation` and organize the project; kept in the temporary folder, part count reported. The script then adds one part of its own that names the two files the staleness cases move, so those cases do not depend on what the writer chose.
- Orientation arms: A, no project synthesis; B, with them. Graded by a substring of the right path.
- Staleness arms, same stale text in both: after the syntheses are written, a commit moves each of the two files (`git mv`). S1 reads the parts as they are (reported `possibly stale`); S2 has every part confirmed after the move (reported `fresh`). Pass: the answer holds the new path and not the old one. S1 against S2 is what the stamp adds.
- Per session, from the stream: correct or not, number of tool calls, input plus cache-read tokens of the final `result` event, and whether the syntheses were used (`mem show p:` or a read of a file under `.memory/syntheses/`).
- Runs: 4 per case and arm on Sonnet: 16 sessions each for A and B, 8 each for S1 and S2, plus 16 pilot sessions and the writer.
- Routing and recall trials are not rerun: without a project synthesis the session text is byte-equal to today's (Task 3 tests it).

**Decision rule, written beforehand; the first row that applies decides:**

| Outcome | Action |
| --- | --- |
| B correct in 2 or more sessions fewer than A, or S1 correct in fewer than 6 of 8 | Do not merge; record the negative result |
| B used the syntheses in fewer than 8 of 16 sessions | The session sentence does not work: reword it once, rerun B once, then apply this table again from the top; a second time, keep the commands and remove the sentence |
| B's median tool calls at least 25% below A's, or B correct in 2 or more sessions more than A | Keep everything; propose merging to the owner |
| Anything else (no measurable gain) | Keep the commands, remove the session sentence |

Reported beside the action, without changing it: tokens per arm, and S1 minus S2. When S1 is not at least 2 sessions above S2, the result says the stamp showed no effect at this sample size.

- [ ] **Step 1: Write the script** with `--claude`, `--model`, `--runs`, `--case`, `--pilot`; print one row per session and the medians per arm.
- [ ] **Step 2: Run the pilot, then the arms**, through `check-runner` in the background; keep only the tables.
- [ ] **Step 3: Write `## Results`** in this file: the tables, the action taken by the rule, and what was not measured.
- [ ] **Step 4: Commit** `test(memory): trials for project syntheses and their result`.

## Pre-mortem of 2026-11-17 and what changed

| Risk found | Change |
| --- | --- |
| The copy held the answers (`CLAUDE.md`, this plan, the trial script) and each question was one grep away, so a 25% saving was noise | Those files left out; questions chosen by a pilot; 4 runs |
| `synthesis add` and `--project` already mean something else; `show p:` met the store refusal | A separate `project-synthesis` command; `p:` handled before the store check |
| The curator runs plain `mem curate`, which had no new block | Blocks in plain `curate` too |
| Comparing with the main worktree's HEAD called a part fresh on another branch | The commit is compared with the files on disk of the session's working tree |
| A part covering the root went stale when any part was written | Changes inside `.memory/` are ignored; paths into it refused |
| The session sentence had no place in a project without memories | Appended to the first line in every case |
| The staleness cases could pass without the stamp | A second arm with the same stale text reported as fresh; the old path fails the answer |
| The decision rule left outcomes uncovered | Ordered rows, the last one catching the rest |
| Commas, bars and git pathspec magic in paths | Refused, and literal pathspecs |

## Not in this experiment

- Undo of a replaced part through `.curation-log` (the previous text is in git when `.memory/` is committed; otherwise it is lost): decide after the result.
- Searching project syntheses with `mem search` (they are read by name; four files need no search).
- Syncing or promoting project syntheses to the global scope.

## Results

Pending.
