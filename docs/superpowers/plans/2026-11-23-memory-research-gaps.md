# Memory plugin: commit gate, re-read reminder, research-wave skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the start fast enough and the tests trustworthy, then close gaps G1 to G4 of the note-repository parity study: hold notes that fail `mem check` back from history commits, tell the agent when notes are due for re-reading, and give the plugin a research-wave skill with note-writing rules.

**Architecture:** The history commit (`engine/store_git.py`) takes an optional validator from `mem.py`, which runs `check()` and returns the changed paths with problems; those are excluded from staging like oversized files, and the list is kept in `.git/mem-held-back`. Because a full `check` takes about 1.0 s on the real store, the `SessionEnd` hook first moves its commit out of the hook's 1.5 s budget into a detached process. The session index gains two lines, each printed only when its count is above zero. G2 and G3 are Markdown: a new skill and a reference file of writing rules.

**Tech Stack:** Python 3 (stdlib plus `pyyaml`), POSIX shell hooks, Claude Code plugin skills, `claude plugin eval`.

**Spec:** [docs/studies/2026-11-23-note-repository-parity.md](../../studies/2026-11-23-note-repository-parity.md) (rows G1 to G4 and the owner rulings), with the research procedure and rules it ports from the note repository's agent contract and playbook, quoted into the Task 6 and 7 briefs.

## Global Constraints

- Branch `feat/memory-research-gaps` from `dev`; pull request to `dev` only with the owner's word (ADR 0027).
- Engine: stdlib plus `pyyaml` only (ADR 0023). The repository is public: no home paths, private repository names or note titles.
- Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` stays green (2,122 passed, 5 skipped at 0.9.0; one known flaky test in the hour after local midnight).
- Hook budget: each hook under 0.5 s (memory plugin plan, stage 3); Claude's `SessionEnd` budget is 1.5 s shared and a plugin hook's `timeout` does not raise it.
- Every user-visible change adds a line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`; no version bump (releases are separate).
- A new skill `description` is measured before merging (CLAUDE.md § Eval protocol: its `trigger/` case plus every `neg-*`, `--runs 2`, Sonnet) and lands in its own commit.
- English, dense, tables over prose (ADR 0002).

## Review Focus

1. A note held back once and fixed later is committed on the next run and leaves `.git/mem-held-back`. → Task 3, `test_fixed_note_is_committed_next_time`.
2. Deleted or renamed notes are never held back (a deleted file cannot fail `check`). → Task 3, `test_deleted_note_is_not_held_back`.
3. `check()` raising (unreadable `topics.yaml`, a crash) never stops the backup: the commit goes ahead unvalidated and the reason is reported. → Task 3, `test_validator_error_commits_everything`.
4. A store that is not a git repository, or has no `.git/mem-held-back`, prints no history line and raises nothing. → Task 4, `test_index_without_git_has_no_history_line`.
5. The detached `SessionEnd` commit must not die with the hook, and must not run with a Python that lacks `yaml` (known pitfall of `mem-capture`). → Task 2, manual check in Step 4.

---

### Task 0: Trustworthy tests and a faster start (owner order, 2026-11-23)

Before G1 to G4: the suite reads the developer's environment, and the SessionStart hook is already over budget (p95 539 ms against 500), which Task 4 would worsen. Source: [structure assessment](../../studies/2026-11-23-memory-plugin-structure.md) step 0, [Rust study](../../studies/2026-11-23-memory-rust-port.md) § Python-side fixes.

**Files:**
- Modify: `plugins/memory/engine/tests/conftest.py`
- Modify: `plugins/memory/engine/records.py` (`safe_load` near line 258), `syntheses.py` (2 sites, near 134 and 974), `project_syntheses.py` (near 88)
- Create: `plugins/memory/engine/run.py`; Modify: `plugins/memory/bin/mem` (run the launcher instead of `mem.py` as `__main__`)

**Interfaces:**
- Produces: the test suite gives the same result inside a Claude Code session with the plugin's options set as under `env -i`; every YAML frontmatter parse in the engine uses the loader `mem.py` already builds on `CSafeLoader` (falls back to `SafeLoader` when libyaml is missing) with unchanged semantics; `bin/mem` imports `mem` so its `.pyc` is cached, and still works when the plugin folder is read-only.

- [x] **Step 1:** `conftest.py` clears every `MEM_*` and `CLAUDE_PLUGIN_OPTION_*` variable (an autouse fixture). Run `MEM_RULES_LAYOUT=digest uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_rules.py plugins/memory/engine/tests/test_rules_session.py -q`: expect 0 failed (6 failed before: 3 in each file); then run the whole suite once more under `env -i HOME=$HOME PATH=$PATH` and expect the same result as with the session's variables.
- [x] **Step 2: Commit** `test(memory): isolate the engine tests from the session environment`.
- [x] **Step 3:** Swap the four `yaml.safe_load` calls for the shared loader. Check: whole suite green; outputs byte-identical before and after for `search` (3 queries), `check`, `find --topic llm`, `memories`, `stats`, `session-index` on a scratch copy of the real store.
- [x] **Step 4:** Add `run.py` and point `bin/mem` at it. Check: suite green; `bin/mem --help` works with the plugin folder made read-only (`chmod -R a-w` on a copy).
- [x] **Step 5: Measure** 20 runs after 2 warm-ups, before and after, on a scratch copy (set `MEM_DATA` to scratch so the real logs stay clean): the SessionStart hook script, `session-index --hook`, `search`. Expect the hook p95 under 400 ms; report p50/p95/sd.
- [x] **Step 6: Commit** `perf(memory): C YAML loader everywhere and a launcher that caches mem.pyc`, plus a CHANGELOG line.

### Task 1: Move notes and check out of `mem.py` (owner, 2026-11-23)

The owner's rule (2026-11-23): a code file at 1,000+ lines is reviewed for a split as part of the work. `mem.py` is 7,146 lines and Tasks 3 and 4 would add to it, so this task first moves two seams out, behavior unchanged ([structure assessment](../../studies/2026-11-23-memory-plugin-structure.md), step 3).

**Files:**
- Create: `plugins/memory/engine/notes.py` (frontmatter parsing, the YAML loader, `Note`, topics: the block near `mem.py:131-323`)
- Create: `plugins/memory/engine/check.py` (the check rules and `check()`, plus `due_retests`/`due_rereads`: the block near `mem.py:502-1392`)
- Modify: `plugins/memory/engine/mem.py` (re-exports both modules' public names so `mem.X` keeps working); `research_checks.py` and `research_pipeline.py` import `split_frontmatter`/`FrontmatterError` from `notes` instead of `mem`
- Test: a new `plugins/memory/engine/tests/test_import_graph.py`; existing tests whose `monkeypatch.setattr(mem, …)` targets moved code get the new module as target

**Interfaces:**
- Produces: `notes` imports no other engine module except leaf helpers; `check` imports `notes` and never `mem`; `mem` imports both. Tasks 3 and 4 add their new logic to `check.py`, not `mem.py`.

- [x] **Step 1:** Write `test_import_graph.py`: `notes` and `check` import without importing `mem` (`'mem' not in sys.modules` after a fresh import in a subprocess). Run: FAIL (modules do not exist).
- [x] **Step 2:** Move the code (cut and paste, no rewrites), add the re-exports, fix the two research modules' imports and the moved patch targets. Never loosen an assertion; if more than 5 tests need anything other than a new patch target, stop and report.
- [x] **Step 3:** Whole suite green; outputs byte-identical on a scratch copy of the real store for `check`, `search`, `review`, `session-index`; `wc -l` of `mem.py` reported (expect about 6,000).
- [x] **Step 4: Commit** `refactor(memory): move notes and check out of mem.py`.

### Task 2: Detach the `SessionEnd` history commit

**Files:**
- Modify: `plugins/memory/hooks/session-end.sh`
- Test: the hook tests under `plugins/memory/engine/tests/` that run `session-end.sh` (find them with `grep -l session-end plugins/memory/engine/tests/*.py`)

**Interfaces:**
- Produces: `session-end.sh` returns within the hook budget. One detached wrapper (`setsid nohup`, as `mem-auto` is started today) runs, in this order: `mem history commit --hook` (timeout 30 s), then `mem-auto` and `mem-settle` when their options are on, so the commit keeps happening before the automatic runs take their lock (today `history commit --hook` returns 0 without committing when a run lock is held, `mem.py` near the `run_lock_held` call). The wrapper writes a `started` record to the hook log before the commit and a `done` record with its duration after, so a killed run is visible. `bin/mem` runs through `uv`, so the `yaml` pitfall of `mem-capture` does not apply.

- [x] **Step 1: Write the failing test** `test_session_end_returns_before_commit_finishes`: with a stub `mem` whose `history commit` sleeps 3 s, the hook exits in under 1 s and the stub's marker file appears within 5 s; `test_session_end_commits_before_auto_runs` (stub records call order: commit before auto). List the existing session-end tests (`engine/tests/test_plugin_shell.py`, near the session-end hook test) and change their synchronous `git log` assertions to poll for up to 5 s. Do not loosen what they assert.
- [x] **Step 2: Run it; expect FAIL** (the hook waits for the commit).
- [x] **Step 3: Implement** the wrapper in `session-end.sh` (the order above, `timeout 30` on the commit, the two hook-log records).
- [x] **Step 4: Verify**: the tests pass; then by hand, run the hook with the real `mem` against a scratch store copy and confirm a commit appears and the hook log has `started` and `done`.
- [x] **Step 5: Commit** `fix(memory): run the session-end history commit detached from the hook`.

### Task 3: Hold failing notes back from history commits (G1)

**Files:**
- Modify: `plugins/memory/engine/store_git.py` (`_commit`, `commit_if_changed`)
- Modify: `plugins/memory/engine/mem.py` (`_commit_points`; `cmd_history` output)
- Test: `plugins/memory/engine/tests/test_store_git.py` (or the existing history test file)

**Interfaces:**
- Produces: `store_git.commit_if_changed(store, message, *, report=..., warn: Callable[[str], None] = ..., validate: Callable[[list[str]], list[str]] | None = None) -> str | None`. Order inside the commit lock: `add -A` (with the oversized excludes) → changed paths from `git diff --cached --name-only -z --diff-filter=d` (staged, untracked files included, deletions excluded, NUL-separated so quoted paths match) → `validate(paths)` → `git reset -q -- <held paths>` → also hold, and reset, any path whose working tree differs from the index after the check (a writer changed it during the check; writers do not take the commit lock) → write `.git/mem-held-back` (one path per line; removed when empty) **before** the "nothing staged" early return → commit. A validator exception calls `warn` (not `report`: `report` means git failed and makes `mem history commit` exit 1) and commits everything. The gate checks the working tree, not the committed snapshot: a committed note may link to a held-back one (accepted gap, stated in the CHANGELOG).
- Produces: `store_git.held_back(store: Path) -> list[str]` (empty when the file or `.git` is missing).
- Produces: `check.invalid_changed(store: Path) -> Callable[[list[str]], list[str]]` (in `check.py`, from Task 1): runs `check(store)` once and returns the given paths that have a `Problem`.
- `_commit_points` passes `validate=check.invalid_changed(store)` and a `warn` that prints and logs without counting as a failure; `mem history commit` prints `held back: <path>` per path on stderr.

- [x] **Step 1: Write failing tests**: `test_invalid_note_is_held_back` (a note with a missing required heading is not in the commit; a valid note changed at the same time is; `held_back()` lists the invalid one); `test_invalid_note_in_new_folder_is_held_back` (untracked topic folder); `test_fixed_note_is_committed_next_time`; `test_deleted_note_is_not_held_back`; `test_validator_error_commits_everything` (validator raises → everything committed, `warn` called once, `report` not called, `mem history commit` exits 0); `test_note_changed_during_check_is_held_back`; `test_no_validator_keeps_old_behavior`; `test_held_back_file_written_when_nothing_else_staged`; `test_valid_note_linking_held_back_note_is_committed` (documents the accepted gap). Existing tests that write invalid notes on purpose (`engine/tests/test_store_git.py`, the hook test in `test_plugin_shell.py`) get valid notes where they test committing, never looser assertions; if more than 2 tests would need their assertions loosened, stop and report.
- [x] **Step 2: Run them; expect FAIL.**
- [x] **Step 3: Implement** in `store_git.py`, then wire `mem.py`.
- [x] **Step 4: Run the new tests and the whole suite; expect PASS.** Time `mem history commit` on a scratch copy of the real store with one changed note: record the figure in the task report.
- [x] **Step 5: Commit** `feat(memory): hold notes that fail mem check back from history commits`.

### Task 4: Session-index lines for held-back and due notes (G1, G4)

**Files:**
- Modify: `plugins/memory/engine/mem.py` (`session_index`, near the `Curation due` line)
- Test: the session-index test file

**Interfaces:**
- Consumes: `store_git.held_back(store)`; `due_retests(root, today)` and `due_rereads(root, today)` (existing, `mem.py`).
- Produces two lines, each only when its count `n > 0`, exact copy:
  - `History: {n} changed {"note" if n == 1 else "notes"} held back from the last commit: run mem check.`
  - `Re-read due: {n} {"note is" if n == 1 else "notes are"} past {"its" if n == 1 else "their"} review date: mem review.`

- [x] **Step 1: Write failing tests**: `test_index_reports_held_back`, `test_index_reports_due_rereads` (a `kind: web` literature note on an `llm` topic with `added` 200 days before `today`), `test_index_silent_when_nothing_due`, `test_index_without_git_has_no_history_line`.
- [x] **Step 2: Run them; expect FAIL.**
- [x] **Step 3: Implement** `check.due_counts(root, today) -> tuple[int, int]` (retests, rereads; in `check.py`) in one pass that shares one `discover_notes` and one `load_topics` with the existing `due_retests`/`due_rereads` logic (separate scans cost about 143 ms; one pass about 70 ms, measured in-process 2026-11-23), cached per day in the plugin's state folder; the index line counts both.
- [x] **Step 4: Run the suite; time `mem session-index` 20 times before and after on the real store (read-only command): report p50/p95; p95 must stay under 0.5 s, else move the count into the curation pass and report.** Confirm the character-budget test's fixture produces both new lines; if not, add one that does.
- [x] **Step 5: Commit** `feat(memory): session index reports held-back notes and notes due for re-reading`.

### Task 5: CHANGELOG and docs for Tasks 2 to 4

**Files:** `plugins/memory/CHANGELOG.md` (`## [Unreleased]`), `plugins/memory/README.md` (behavior of history commits and the index, if described there), `docs/superpowers/plans/2026-11-17-memory-plugin.md` (state table row "Unreleased work"; the open item on the `SessionEnd` budget marked solved by Task 2).

- [x] **Step 1:** Write the entries, for users: what changes, what to do when the index says notes are held back.
- [x] **Step 2:** `python3 scripts/validate.py` and `claude plugin validate .` pass.
- [x] **Step 3: Commit** `docs(memory): changelog and plan for the commit gate and re-read reminder`.

### Task 6: Note-writing rules reference (G3)

**Files:**
- Create: `plugins/memory/skills/memory/references/research-notes.md`
- Modify: `plugins/memory/skills/memory/SKILL.md` (one line pointing to it where writing notes is mentioned)
- Modify: `plugins/memory/agents/memory-recorder.md`, `memory-synthesizer.md` only if they write literature or knowledge notes (one line each; they have `omitClaudeMd: true`, so the rule must be in their prompt or the reference path)

**Content (from the note repository's agent contract, to be restated, not linked; the controller quotes the source text into the brief):** source ranks 1 to 5 and what each may support; the knowledge confidence rubric (`high` only when a rank 1–2 source states it directly, uncontested and established; a single study stays `medium`; `origin: experience` without a rank 1–2 source stays `medium`; `low` for contested or weak evidence); a note only from a source fetched and read, its `url` the exact page; full text, never a summary; local copy via `mem fetch-sources <store-relative path>`; `Inference:` / "(inference)" labels; filenames and claims as declarative facts; conservative `level`; `mem new … --body-file`, `mem check <paths>`, `mem note edit --shrink` for reworded sentences; no business specifics in global notes.

- [ ] **Step 1:** Write the reference (dense, tables, under 150 lines; `outline.py` headings that name their content).
- [ ] **Step 2:** Add the pointers. `python3 scripts/validate.py` passes.
- [ ] **Step 3: Commit** `docs(memory): rules for writing research notes`.
- [ ] **Step 4: Owner review** of `research-notes.md` (the owner wanted to evaluate these rules, 2026-11-23); `grep` it for home paths and private names first. Task 7 may be drafted meanwhile; the branch does not merge before this review.

### Task 7: `memory-research-wave` skill (G2)

**Files:**
- Create: `plugins/memory/skills/memory-research-wave/SKILL.md`
- Create: the skill's trigger eval case, following the layout of the existing ones under `plugins/memory/evals/trigger/`
- Modify: `plugins/memory/README.md` (skill list), `plugins/memory/CHANGELOG.md`

**Content:** when to use (several sources or several agents; one note or one fact needs only the `memory` skill); the procedure: frame and `mem search` first → one common brief plus one dispatch per area, rules quoted inline (writers cannot be relied on to open documents) and pointing to `references/research-notes.md` of the `memory` skill → writers in parallel, each owning only its notes, full text via a shell, `mem new --body-file`, `mem fetch-sources`, `mem check` → one fresh-context fact-checker per area against the local copies → one fixer applies verified corrections with `mem note edit` (`--shrink` for rewording) → review of the whole (`mem related`, `mem stats --orphans`, links) → record the wave's figures as a lesson with topic `research` (`mem remember --global --kind lesson`). Use the `agent-skills` workers when installed (`implementer` writers, `fact-checker`), else general-purpose subagents with the same briefs. Body under 200 lines.

- [ ] **Step 1:** Write `SKILL.md` and its trigger case (prompts that should fire it: a multi-source study, "research X and record it"; the `neg-*` cases stay as they are).
- [ ] **Step 2:** `python3 scripts/validate.py`, `claude plugin validate plugins/memory`.
- [ ] **Step 3: Commit** the skill alone (`feat(memory): memory-research-wave skill`), so the description can be reverted alone.
- [ ] **Step 4: Measure** per CLAUDE.md § Eval protocol: `claude plugin eval plugins/memory --ablation none --model sonnet -j 4 --runs 2 --max-cost-usd 5 --case '<the new trigger case>'`, then each `neg-*` glob. Record the table in ADR 0023 as `## Review 2026-11-23` (or the run date). A trigger below 2/2 or a `neg-*` that fires reruns at 6 runs; a drop of 2 or more of 6 on a `neg-*` reverts the description.
- [ ] **Step 5: Commit** the ADR review and the CHANGELOG line.

## Kill criteria (pre-mortem 2026-11-23)

- Hook-log `session-end` records over 3,000 ms, or `started` without `done` → raise the timeout or move the check out of the lock.
- Sessions without a commit while the hook log shows the run lock skipped it → restore the order.
- `session-index` p95 over 0.5 s after Task 4 → stop and ask the owner (the ruling puts the line in the index; moving it to the curation pass changes that ruling).
- More than 2 existing tests need looser assertions → stop and re-plan Task 3.
