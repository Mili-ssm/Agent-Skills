# `mem.py` fully clean under Ruff and basedpyright: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

Status: done 2026-11-26, review pending · Branch: `fix/prompt-review-2026-11-26` · Date: 2026-11-26

**Goal:** `plugins/memory/engine/mem.py` and `plugins/memory/engine/tests/test_curation.py` pass the commit gate of ADR 0031 with no finding, behavior unchanged, so the one-sentence change to the session start text can be committed.

**Architecture:** A refactoring with behavior unchanged. First the changes that touch the whole file (format, imports, re-exports, small rules, types), in sequence. Then the 66 functions with structural findings are decomposed into helpers, in six groups of neighbouring functions that run in parallel, each in its own git worktree, and merge back one by one. `mem.py` stays one module and keeps every name tests and scripts use.

**Tech Stack:** Python 3.12, Ruff 0.17.6 (`ruff.toml`, preview on, complexity 6), basedpyright 1.40.2 (`standard`), pytest with xdist, pre-commit.

**Spec:** [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md) (a touched file is fully clean, every rule; owner, 2026-11-25) and task 4b of [the prompt review plan](2026-11-26-prompt-review-fixes.md). Owner decision 2026-11-26: clean `mem.py` now, on this branch.

## Measured start (2026-11-26, pinned tools)

| File | Lines | Ruff findings | basedpyright errors |
|---|---|---|---|
| `engine/mem.py` | 6,102 | 333 after safe fixes (361 at `dev`): 69 private-name imports, 94 small-rule findings, 170 structural findings in 66 functions | 62 |
| `engine/tests/test_curation.py` | 1,211 | 50 (26 magic values) | 3 |

Complexity of the 64 functions over the limit of 6: 12 above 20 (`cmd_curate` 36, `cmd_synthesis` 35, `session_index`, `cmd_remember`, `cmd_memory` 34), 15 from 13 to 20, 16 from 9 to 12, 21 at 7 or 8. The working tree already holds Ruff's safe fixes and the new session start sentence in both files, uncommitted.

## Global Constraints

- Behavior unchanged: same output text, exit codes, files written and their content, for every `mem` subcommand. The one intended change is the session start sentence, already in the tree: `(after the current task: dispatch memory:memory-curator).`
- No `# noqa`, no `# ruff: ignore`, no `# type: ignore`, no `# pyright: ignore`, no edit to `ruff.toml`, `pyrightconfig.json` or `.pre-commit-config.yaml` (ADR 0031: every rule). The existing `# ruff: ignore[unused-import]` on the `check` import goes away with Task 1.
- Touch only `engine/mem.py`, and `engine/tests/test_curation.py` in Task 4. Any other Python file touched must then be fully clean too, so a task that seems to need one stops and reports.
- Every top-level name of `mem.py` that exists at `dev` keeps its name and return value, and every existing call keeps working unchanged: tests and `bin/` scripts call them as `mem.<name>`. Nine functions have more than 5 parameters (`PLR0913`, `PLR0917`) and one has a parameter named `type` (`A002`); § Signatures says how each is fixed. New helpers are private (`_name`), sit next to the function they came from, take explicit parameters (no new module state) and carry the prefix of their area (`_curate_…`, `_search_…`), so two tasks never create the same name.
- Names re-exported into `mem` from other modules and patched by tests (`mem.orphan_notes`, `mem.apply_index`, `mem.invalid_changed`) stay imported by name and are called bare, so `monkeypatch.setattr(mem, …)` still reaches them.
- A helper is extracted along a real seam (one decision, one phase, one output block) and named for what it does. A dispatch table replaces a long `if`/`elif` chain over a subcommand or kind. A function is never split into numbered parts.
- No change to a test's assertions. A failing test means the step changed behavior: revert the step and take a smaller one.
- Gate commands, from the repository root:
  - Recipes for behavior-sensitive rules, the same in every task:
  - `BLE001`, `S110` (broad `except Exception`, some on the session start path, which must print its text whatever a record holds): keep the broad handler and log the exception, `logger.debug("<what failed>", exc_info=True)`, with one module-level `logger = logging.getLogger(__name__)`. Nothing is printed, because no handler is configured below WARNING. Never narrow the exception type. Confirmed by the owner, 2026-11-26.
  - `PLW0717` (too many statements in a `try`): never move a statement out of the `try`; extract the whole body into a helper and call it as the only statement inside.
  - `TRY004`: raise `NoteFormatError`, a new `class NoteFormatError(ValueError)`, with the same message, so the handlers that catch `ValueError` still catch it.
  - `B905`: always `strict=False`.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2,272 passed, 5 skipped at the start).
  - Lint: `uvx ruff@0.17.6 check --no-fix plugins/memory/engine/mem.py` and `uvx ruff@0.17.6 format --check plugins/memory/engine/mem.py`. Plain `ruff check` applies fixes (`fix = true`); use `--no-fix` to measure.
  - Types: `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings plugins/memory/engine/mem.py`.
- Commits: `refactor(memory): …`, one per task, made by the implementer once the task's own gate holds. Until Task 11 the commit hook fails on the findings other tasks still own, so task commits skip only those two hooks, by name: `SKIP=ruff-check,ruff-format,basedpyright git commit …` (pre-commit's own switch; never `--no-verify`). Task 11 commits with every hook on.

## Signatures

| Function | Callers outside `mem.py` | Fix |
|---|---|---|
| `session_index` (4 positional, 6 keyword-only) | 18 files, all pass the six by keyword | The six become `**options: Unpack[SessionIndexOptions]`, a `TypedDict` with `total=False` holding the same names and types; defaults applied inside. No call site changes and keyword names stay type-checked (PEP 692) |
| `_matching_notes` (8 parameters, one named `type`) | 2 files, plus `**filters` calls inside `mem.py` | The filters become `**filters: Unpack[NoteFilters]`, a `TypedDict` with a `type` key, which also clears `A002` |
| `_decisions` (7), `new_note` (6), `show` | 4, 2 and 2 files | Same technique for the parameters callers pass by keyword; if a caller passes more than 5 positionally, stop and report that call |
| `format_hit`, `unify_notes`, `_edited_note_text`, `_add_with_note`, `_commit_note_edit` | none | Free to change: a frozen dataclass for the grouped values, call sites inside `mem.py` updated |

## Review Focus

1. Output text that changes by one space, newline or plural when a formatting block moves into a helper: the golden comparison of Task 0 and the string-asserting tests catch it; a reviewer diffs the moved block against the original.
2. Early `return <code>` inside an extracted block: the caller must return the helper's code, not continue. Check each extraction of a block that held a `return`.
3. Variables assigned in a block and read after it: an extracted helper must return them. Check `nonlocal`-style rebinding lost in extraction.
4. Exception scope: narrowing `except Exception` (BLE001) or shrinking a `try` body (PLW0717) must keep catching what the old code caught at that point. Each narrowed handler names the exceptions the guarded calls raise.
5. `zip(..., strict=…)` (B905): `strict=True` raises where the old code truncated. Use `strict=False` unless the two sequences are built with equal length a few lines above.

---

### Task 0: Golden outputs from `dev`

**Files:**
- Create (scratch, not in the repository): a script and its output folder under the session scratch directory.

**Interfaces:**
- Produces: `golden.sh <engine-dir> <out-dir>`, which copies a fixture store to a fresh temp directory, runs a fixed list of `mem` subcommands against it with the engine at `<engine-dir>`, and writes one file per command holding stdout, stderr and the exit code; and `<out-dir>/dev/`, the outputs of the engine at `dev`.

- [x] **Step 1:** Read `plugins/memory/bin/mem` and `plugins/memory/engine/tests/conftest.py` to learn how the store and the project root are passed (`MEM_STORE`, `MEM_MEMORIES`, working directory) and how tests build a store.
- [x] **Step 2:** Build the fixture: a copy of the owner's real store and of this repository's `.memory/` folder (read-only use of the originals). Every command runs on fresh copies with `MEM_STORE`, `MEM_MEMORIES`, `MEM_DATA`, `XDG_STATE_HOME`, `XDG_CONFIG_HOME` and `XDG_DATA_HOME` pointing into the copy, `COLUMNS=100` and the same interpreter on both sides, because `log_usage` and the due cache otherwise write to the owner's real data folder and change the next run.
- [x] **Step 3:** Write `golden.sh` with this command list, each run from a copy of the repository's `.memory/` parent: `search` (three queries, one with `--deep`, one with `--handles`), `show` (two memory handles, one note), `memories`, `rules`, `rules --unread`, `curate`, `curate --notes`, `stats`, `check`, `history list`, `projects`, `terms`, `related` (one note), `session-index`, `synthesis list`, `note --help`, `--help`. Then write scenarios, each on its own copy, comparing stdout and `diff -r` of the store and data copies afterwards: `remember`, `memory edit` (`--claim` with `--short`), `confirm`, `curate --done`, `curate apply --safe`, `note edit`, `import` (one file), `synthesis add`, a note rename and a unify. Mask only temp paths and timestamps through `sed`; never mask a count. Also run `session-index --hook` on a copy with one record truncated mid-frontmatter: it must print its text and no traceback.
- [x] **Step 4:** Run it twice against a worktree of `dev` and diff the two output folders. Expected: no difference; a difference is run-dependent text, so add its mask and repeat.
- [x] **Step 5:** Run it against the working tree. Expected: one difference, the session start sentence.

### Task 1: Format, imports and re-exported names

**Files:**
- Modify: `plugins/memory/engine/mem.py`

**Interfaces:**
- Produces: a formatted `mem.py` whose import block no later task edits; `mem.<name>` still resolves for the 69 names that moved to `check`, `notes` and `index`.

- [x] **Step 1:** `uvx ruff@0.17.6 format plugins/memory/engine/mem.py`; run the tests. Expected: pass.
- [x] **Step 2:** Replace the three `from check|notes|index import (_NAME, …)` re-export blocks. Import the three modules under aliases no local name shadows, `import check as check_rules`, `import notes as note_files`, `import index as index_files` (never `import check`: `mem.check` is a function tests call, and `notes` is a local variable in 15 functions). Inside `mem.py`, a use of a moved private name becomes `check_rules._NAME` and so on; public names keep their `from … import`. For `mem._NAME` from outside, add a module `__getattr__(name: str) -> object` (PEP 562) that looks the name up in a tuple of the three modules, in the order `check`, `notes`, `index`, only for names in a frozenset `_MOVED` listing exactly the 69 names, and raises `AttributeError` otherwise. One comment line says why: the names moved out and callers still use `mem.<name>`.
- [x] **Step 3:** Test first: add nothing to the repository; run `grep -rhow 'mem\._[A-Za-z_0-9]*' plugins/memory/engine/tests plugins/memory/bin plugins/memory/evals | sort -u` and check each name resolves with `python3 -c` from `plugins/memory/engine`. Expected: every name resolves.
- [x] **Step 4:** Fix the import findings: `TC003`, `TC002` (move to an `if TYPE_CHECKING:` block), `PLC0415` (`digest`: move to the top, its own imports are already loaded; `research_checks`: it imports `mem` back, so move it to the top only if `python3 -c "import research_checks"` and `python3 -c "import mem"` both still work from `plugins/memory/engine`, else keep it deferred through `importlib.import_module`), `EXE001` (the file mode or the shebang, whichever `git ls-files -s` shows is wrong).
- [x] **Step 5:** Gate: tests pass; `ruff check --no-fix --select PLC2701,TC,PLC0415,EXE,I,F401` reports nothing for `mem.py`; `ruff format --check` passes. Commit.

### Task 2: Small-rule findings in `mem.py`

**Files:**
- Modify: `plugins/memory/engine/mem.py`

**Interfaces:**
- Consumes: Task 1's formatted file.
- Produces: `mem.py` with only structural findings left (`C901`, `PLR0911`–`PLR0917`, `PLW0717`).

- [x] **Step 1:** Fix by rule, running the tests after each rule: `PLR6201` (tuple to set literal in `in` tests of hashable constants), `PLR2004` (a named module constant per magic value, named for its meaning, reused where the same meaning recurs), `B905` (Review Focus 5), `B023` (bind the loop variable as a default argument or move the closure out), `SIM105` (`contextlib.suppress`), `S110` and `BLE001` (Review Focus 4), `ISC004`, `RUF005`, `TRY004`, `A002` (rename the parameter only if no caller passes it by keyword; else stop and report), `SIM102`, `PERF401`, `PLR1714`, `F841`.
- [x] **Step 2:** Gate: tests pass; `ruff check --no-fix` on `mem.py` lists only the structural rules named above; `ruff format --check` passes; golden comparison shows only the session start sentence. Commit.

### Task 3: Type errors in `mem.py`

**Files:**
- Modify: `plugins/memory/engine/mem.py`

**Interfaces:**
- Consumes: Task 2's file.
- Produces: `mem.py` with 0 basedpyright errors and warnings.

- [x] **Step 1:** Run the type gate and group the 62 errors by kind. Fix each with a real narrowing (`if x is None: return …` where the old code would have raised anyway is a behavior change: keep the old failure by raising the same exception type explicitly), an annotation, or a `typing.cast` only where the value's type is fixed by a file format the checker cannot see.
- [x] **Step 2:** Gate: type gate reports `0 errors, 0 warnings`; tests pass; Ruff shows no new finding outside the structural rules; golden comparison unchanged. Commit.

### Task 4: `test_curation.py` clean

**Files:**
- Modify: `plugins/memory/engine/tests/test_curation.py`

**Interfaces:**
- Consumes: Task 3's `mem.py` (its types feed this file's type check), so it runs after Task 3, in the same tree.

- [x] **Step 1:** Fix the 50 findings: `PLR2004` (26: a named constant at the top of the file or of the test, named for what the number means in that test), `PLC0415` (imports to the top), `PLC1901`, `PLR0913`/`PLR0917` (the helper `put`, 9 parameters and about 158 calls: `put(folder, handle, claim, **fields: Unpack[PutFields])`, so no call changes), `RUF059`, `SIM118`, `FURB113`, `F841`, `RUF005`, `PIE810`. No assertion changes its expected value.
- [x] **Step 2:** Fix its 3 type errors (`None` narrowing before `.read_text`/`.write_text`).
- [x] **Step 3:** Gate: `ruff check --no-fix`, `ruff format --check` and the type gate report nothing for the file; `pytest plugins/memory/engine/tests/test_curation.py -q` passes with the same test count as before. Commit with every hook on: the file is clean on its own.

### Tasks 5–10: Structural findings, one group of functions each

Task 8 runs first, alone, as the pilot: it holds `cmd_curate`, the most complex function. After its review the controller applies the helper-quality kill criterion; only then do the other five start. Each task runs in its own git worktree created from the commit of Task 4, in parallel, and owns only the functions it lists plus the helpers it extracts from them, placed directly above the function they came from. A task that needs to change a function of another group stops and reports.

**Files (each task):**
- Modify: `plugins/memory/engine/mem.py`, only inside its functions.

**Interfaces (each task):**
- Consumes: Task 3's file.
- Produces: its functions with no finding of `C901`, `PLR0911`, `PLR0912`, `PLR0913`, `PLR0914`, `PLR0915`, `PLR0916`, `PLR0917`, `PLW0717`; every listed function keeps its name, parameters and return value.

| Task | Functions (file order) |
|---|---|
| 5 | `_matching_notes`, `format_hit`, `show`, `new_note`, `_link_edits`, `rename_note`, `unify_notes`, `_write_text_copy`, `build_missing_texts`, `fetch_sources`, `log_usage`, `_memory_block`, `_synthesis_block`, `cmd_project_synthesis` |
| 6 | `cmd_show`, `session_index`, `_log_hook`, `cmd_session_index`, `cmd_compact_log`, `cmd_signal`, `cmd_remember`, `_memory_of`, `cmd_confirm` |
| 7 | `_linked_project_records`, `cmd_triage`, `_reword_failed`, `cmd_memory`, `_merge_pair`, `_distinct_notes`, `_restore_synthesis`, `_restore_group`, `cmd_restore`, `cmd_promote`, `_rules_unread`, `cmd_rules`, `_decisions`, `_grouped_pairs`, `_curate_notes` |
| 8 | `_safe_merge`, `_safe_attach`, `_curate_apply`, `cmd_curate`, `cmd_settle`, `cmd_history`, `_init_store`, `cmd_projects`, `cmd_terms`, `_read_body`, `_write_logged_changes`, `_structure`, `_refs` |
| 9 | `_add_with_note`, `cmd_synthesis`, `cmd_new`, `_edited_note_text`, `_commit_note_edit`, `cmd_note`, `cmd_note_mark`, `_import_files`, `_flag_import`, `cmd_import` |
| 10 | `cmd_stats`, `cmd_search`, `cmd_related`, `build_parser`, `_dispatch` |

Steps, the same for each task:

- [x] **Step 1:** List the task's findings: `uvx ruff@0.17.6 check --no-fix --output-format concise plugins/memory/engine/mem.py`, kept to the lines inside its functions.
- [x] **Step 2:** One function at a time, smallest first: extract helpers along seams until the function and its helpers have no structural finding. A `cmd_*` function with a subcommand chain becomes a dispatch through a dict of handlers, each handler `(args: argparse.Namespace) -> int`. Too many arguments (`PLR0913`, `PLR0917`) on a function whose signature must stay: stop and report it, unless the extra arguments are internal to helpers you created, which take a small frozen dataclass instead. Run the tests of the area after each function (`pytest plugins/memory/engine/tests -q -n auto -k <name>` when a narrower selection exists, else the full suite).
- [x] **Step 3:** Gate: full tests pass; no structural finding inside the task's functions and helpers; no new finding of any other rule; `ruff format --check` passes; the type gate still reports 0; golden comparison shows only the session start sentence. Commit in the worktree.
- [x] **Step 4:** Report: per function, complexity before and after and the helpers created; any function left with a finding and why.

Before the fan-out the controller adds to `mem.py` any helper two groups would both write (a plural helper for the `'' if n == 1 else 's'` pattern, and others the pilot reveals) and names them in each brief; a task that needs a new import reports it instead of adding it. Merge, by the controller, after each task's review: `git merge` the branches one by one, in file order, and after each merge run full Ruff (a duplicate helper shows as `F811`), the type gate, the tests and the golden comparison. A conflict outside the two blank lines between neighbouring groups, or an `F811`, stops the merges: rebase the remaining branches one at a time.

### Task 11: Whole-file gate, docs, hook

**Files:**
- Modify: `plugins/memory/CHANGELOG.md`, `plugins/memory/README.md` (the sentence that quotes the old session start text), `docs/backlog.md`, `docs/superpowers/plans/2026-11-26-prompt-review-fixes.md` (tick 4b), `docs/adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md` (`## Review 2026-11-26`: `mem.py` clean, counts before and after, what the cleanup cost).

- [x] **Step 1:** `pre-commit run --files plugins/memory/engine/mem.py plugins/memory/engine/tests/test_curation.py`. Expected: every hook passes and changes nothing.
- [x] **Step 2:** Full tests; golden comparison (only the session start sentence differs); `python3 scripts/validate.py`; `claude plugin validate .`.
- [x] **Step 3:** One line under `## [Unreleased]` of the memory changelog: the session start text names `memory:memory-curator` when curation is due. The refactor itself needs no line (pure refactor).
- [x] **Step 4:** Update the README sentence, the backlog row left open by the prompt review, the 4b tick and the ADR 0031 review. Commit with every hook on.

## Decisions taken, with reasons

| Decision | Reason | Alternative rejected |
|---|---|---|
| Module `__getattr__` for the 69 moved names | Keeps `mem.<name>` working and touches only `mem.py` | Renaming the names public in `check`, `notes`, `index`: touches those files plus `syntheses.py`, `records.py`, `store_git.py`, `shortcheck.py` and two tests, each of which must then be fully clean (about 190 more findings) |
| `mem.py` stays one module | Tests bind to `mem.<name>` for 23 private names; a split is cheaper once functions are small and is a separate decision | Splitting by command area now: every moved function needs a re-export or a test edit |
| Six parallel worktrees for the structural work | The groups are disjoint spans of the file; in sequence the work is six times longer on the clock | One task at a time: no merge risk, slower |
| Broad handlers stay broad and log at debug level (owner to confirm) | The session start path catches everything on purpose; narrowing risks a traceback in every session. Debug logging makes the swallowed error findable and satisfies `BLE001` | Narrowing each handler to named exceptions: 15 behavior-sensitive sites no test covers |
| Typed `**options` (`TypedDict` with `Unpack`) for functions over 5 parameters that outside callers use | No call site changes, keyword names stay type-checked | Editing the 18 calling files: each must then be fully clean |
| Golden comparison on a copy of the real store | Tests pin behavior on fixtures; an earlier stage found defects only on real data (project memory, 2026-11-22) | Tests alone |

## Kill criteria

- A task cannot reach its gate without a suppression comment, a config edit or a signature change: stop, report the function, and the owner decides (a rule exception for that case would amend ADR 0031).
- The golden comparison differs beyond the session start sentence and the cause is not found in one fix round: revert that task's commit.
- After the pilot (Task 8) is reviewed, judge the helpers' quality: if decomposition to complexity 6 produced helpers that only pass state through (5 or more parameters, or names that describe position, not purpose) in more than a third of its functions, stop and take that evidence to the owner before the other five tasks start.
- The golden comparison of `dev` against `dev` differs after the data folders are isolated: fix the isolation; never add a mask for it.
- `session-index --hook` on the truncated record prints a traceback: revert that task.
