# Memory engine import direction (A7): Implementation Plan

Status: done · merged in #198, 2026-11-26

§ Deferred findings stays open · Branch: `refactor/memory-a7-a1-a3` · Base: `65e901a` · Date: 2026-11-26

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the memory engine has no import cycle, and every Python file this change touches passes the ADR 0031 gate with no finding; behavior unchanged.

**Architecture:** two cycles exist among `plugins/memory/engine/*.py` (AST scan of every `import`, 2026-11-26; no `importlib` or `__import__` in the engine): `research_checks`→`mem`→`research_checks`, and `digest`↔`rules` (two function-level imports in `rules`). Task 1 cuts the first by importing `tokenize` from `records`, where it is defined; Task 2 finishes that file's cleanup. Task 3 cuts the second by moving the digest's pure fingerprint and fresh-text lookups into a new module both import. Task 4 pins the result with an import-graph test.

**Tech Stack:** Python 3.12, Ruff 0.17.6 (`ruff.toml`, preview on, complexity 6), basedpyright 1.40.2 (`standard`), pytest with xdist, pre-commit.

**Spec:** review item A7 in [the project review](../../studies/2026-11-24-project-review.md) and the "Import direction" task of [the refactor plan](2026-11-23-memory-refactor.md); [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md). Owner decisions 2026-11-26: backlog order (quick fixes, then refactor tasks A1–A3); lint cleanup only for the files each change touches; the owner approved this plan, including moving session_env to A2, on 2026-11-26.

## Out of scope, with reasons

- `session_env` without importing `research_pipeline` (the other half of A7): it moves into `headless.py` with A2, which touches `bin/mem-corroborate` anyway. Cleaning `mem-corroborate` (117 Ruff, 128 basedpyright findings, 102 from its guarded engine import) needs the launcher split of A4, so this plan never touches it.
- `test_digest.py`, `test_mem_corroborate.py`: callers of `digest.heading`, `digest.line`, `digest.heading_print`, `digest.line_print` keep working through re-exports, and nothing monkeypatches those names (only `digest.topics_of`, which stays), so neither file changes.

## Measured start (2026-11-26, pinned tools)

| File | Lines | Ruff | basedpyright |
|---|---|---|---|
| `engine/research_checks.py` | 685 | 45 | 5 |
| `engine/digest.py` | 355 | 14 | 2 |
| `engine/rules.py` | 212 | 9 | 2 |
| `engine/tests/test_research_checks.py` | 550 | 13 | 4 |
| `engine/tests/test_synth_session.py` | 96 | 12 | 1 |
| `engine/mem.py` | 10,532 | 0 | 0 |

Suite at start: 2,284 passed, 5 skipped.

## Global Constraints

- Behavior unchanged: same return values, output text, exceptions caught by the same handlers, same network checks in the same order. No change to a test's assertions; renaming a referenced name is not an assertion change. A failing test means the step changed behavior: revert the step and take a smaller one.
- Clean means: `uvx ruff@0.17.6 check --no-fix <files>` and `uvx ruff@0.17.6 format --check <files>` report nothing, and `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings <files>` reports 0 errors and 0 warnings. Plain `ruff check` applies fixes (`fix = true`).
- No `# noqa`, `# ruff: ignore`, `# type: ignore`, `# pyright: ignore`; no edit to `ruff.toml`, `pyrightconfig.json` or `.pre-commit-config.yaml` (ADR 0031).
- Touch only the files a task lists. A task that seems to need another Python file stops and reports. `engine/mem.py` may be edited only at a call site of a changed signature and must stay clean. Never touch `bin/mem-corroborate`.
- Must pass unchanged (they pin current signatures): `engine/research_pipeline.py` (calls `rc.apply(…, mem_cmd=, root=, env=)` and `functools.partial(rc.fetch_text, allow_hosts=)`), `engine/tests/test_fetch_sources.py` (monkeypatches `research_checks.fetch_raw` with `lambda url, limit_for, **kw` and asserts `kw["timeout"]`, `kw["headers"]`).
- Recipes for behavior-sensitive rules (as in [the `mem.py` cleanup](2026-11-26-mem-py-ruff-clean.md)):
  - `BLE001`, `S110`: keep the broad handler, log with `logger.debug("<what failed>", exc_info=True)` through one module-level `logger = logging.getLogger(__name__)`; never narrow the exception type.
  - `PLW0717`: never move a statement out of a `try`; extract the whole body into a helper called as the only statement inside.
  - `TRY004`: raise a new module-level `class <Name>Error(ValueError)` with the same message (`mem-corroborate` catches `ValueError` around `digest.validate`).
  - `PLW1510`: pass `check=False` explicitly.
  - `RUF001`: write the character as a `\uXXXX` escape with its Unicode name in a trailing comment; the string's value must not change.
  - `PLR0913`, `PLR0917` (keyword-only parameters still count): the parameters callers pass by keyword become `**options: Unpack[<Name>Options]`, a `TypedDict` with `total=False` holding the same names and types, defaults applied inside with the old default values, so no call site changes (PEP 692). Applies to `fetch_raw(url, limit_for, **options: Unpack[FetchOptions])` and `apply(verdicts, entries, pages, sent, **options: Unpack[ApplyOptions])`.
  - Structural (`C901`, `PLR0912`, `PLR0914`, `PLR0915`): extract helpers along real seams (one decision, one phase), private, next to their function, named for what they do; never numbered parts.
- Network code in `fetch_raw`: every `_connection(...)` and `socket.getaddrinfo` call stays a module-global lookup at call time (no default argument or bound copy), so test patches still reach it.
- Commits: `refactor(memory): …`, one per task. Task 1 commits with `SKIP=ruff-check,basedpyright git commit …` (pre-commit's own switch, the precedent of the `mem.py` cleanup; never `--no-verify`), because the structural findings it leaves are Task 2's. Every other task commits with all hooks on.
- Pure refactor: no CHANGELOG line.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto`.

## Review Focus

1. `fetch_raw` decomposition: every redirect hop must still resolve and refuse a non-public address before connecting, and the size and time limits must still apply per hop. Review the moved code with `git diff --color-moved=zebra -w`; `test_fetch_sources.py` and `test_research_checks.py` pass unchanged.
2. Defaults moved into a `TypedDict`: an omitted key must behave exactly like the old default (`over`, `deadline`, `max_redirects`, `timeout`, `headers`, `mem_cmd=MEM_ENTRY`, `root`, `env`). Task 2 adds a test per function comparing omitted with default-passed calls.
3. Early `return` or `raise` inside an extracted block: the caller must return or propagate the helper's result, not continue.
4. Exception classes renamed for `N818`: every `except` that caught the old class catches the new one.
5. Strings rewritten for `RUF001`: each literal's `repr` is identical before and after.

---

### Task 1: `research_checks` imports `tokenize` from `records`; format, renames, small rules

**Files:**
- Modify: `plugins/memory/engine/research_checks.py`
- Modify (renames, then fully clean): `plugins/memory/engine/tests/test_research_checks.py`, `plugins/memory/engine/tests/test_synth_session.py`

**Interfaces:**
- Produces: `research_checks` no longer imports `mem`. Exceptions renamed for `N818`: `FetchRefused` → `FetchRefusedError`, `FetchFailed` → `FetchFailedError`, `NotChecked` → `NotCheckedError`, no alias for the old names (callers verified: only the two test files). `FetchError` keeps its name (`mem.py` catches it).

- [x] **Step 1:** Replace the six `mem.tokenize(` calls (lines 469, 478, 575 twice, 577, 578 at the base) with `records.tokenize(` and delete `import mem`. Run the suite. Expected: 2,284 passed.
- [x] **Step 2:** `uvx ruff@0.17.6 format` the three files and apply the safe fixes; run the suite.
- [x] **Step 3:** Rename the three exception classes and every use; run the suite.
- [x] **Step 4:** Fix every non-structural finding in `research_checks.py` (all but `C901`, `PLR0912`–`PLR0917`, `PLW0717`) with the recipes; make both test files fully clean. Run the suite.
- [x] **Step 5:** Gate: both test files clean; `research_checks.py` shows only structural findings; `ruff format --check` passes on all three; full suite passes; `cd plugins/memory/engine && python3 -c "import research_checks, mem"` works. Commit with `SKIP=ruff-check,basedpyright`.

### Task 2: `research_checks` structural findings, file clean

**Files:**
- Modify: `plugins/memory/engine/research_checks.py`, `plugins/memory/engine/tests/test_research_checks.py` (new default tests only)

**Interfaces:**
- Consumes: Task 1's file.
- Produces: `FetchOptions` and `ApplyOptions` (`TypedDict`, `total=False`); signatures `fetch_raw(url, limit_for, **options: Unpack[FetchOptions])` and `apply(verdicts, entries, pages, sent, **options: Unpack[ApplyOptions])`; every call site unchanged.

- [x] **Step 1:** Write `test_fetch_raw_omitted_options_match_defaults` and `test_apply_omitted_options_match_defaults`: with the network and the `mem` command stubbed as the existing tests do, a call with no keyword options and a call passing each old default explicitly give equal results and equal recorded calls. Run them on Task 1's code. Expected: PASS (they pin current behavior).
- [x] **Step 2:** Apply the `Unpack` recipe to `fetch_raw` and `apply`; run the two new tests, `test_fetch_sources.py` and the suite.
- [x] **Step 3:** Decompose the structural findings one function at a time (`fetch_raw`, `plan_commands`, `check_rows`, `web_input`, `fetch_text`, `select_passages`), running `pytest plugins/memory/engine/tests/test_research_checks.py plugins/memory/engine/tests/test_fetch_sources.py -q` after each.
- [x] **Step 4:** Gate: `research_checks.py` and `test_research_checks.py` clean; full suite passes; `git diff --color-moved=zebra -w` of `fetch_raw` shows its address checks in the old order. Commit with all hooks on.

### Task 3: digest lookups in their own module; `rules` imports at the top

**Files:**
- Create: `plugins/memory/engine/digest_text.py`
- Modify: `plugins/memory/engine/digest.py`, `plugins/memory/engine/rules.py`

**Interfaces:**
- Produces: `digest_text.py`, depending only on `hashlib`, `collections.abc.Sequence` and `records` (for the `Memory` type; type-only imports go under `TYPE_CHECKING` as Ruff's `TC` rules ask), holding the functions moved unchanged from `digest.py`: `_print(*parts: str) -> str`, `line_print(m: Memory) -> str`, `heading_print(lessons: Sequence[Memory]) -> str`, `heading(digest: dict, topic: str, lessons: Sequence[Memory]) -> str | None`, `line(digest: dict, topic: str, m: Memory, lessons: Sequence[Memory]) -> str | None`. Its docstring says what it holds and that both `digest` and `rules` import it, so neither imports the other back.
- `digest.py` re-exports the four public names with `from digest_text import heading, heading_print, line, line_print` plus an `__all__` listing them with `digest.py`'s other public names (never `import x as x`: Ruff 0.17.6 flags it as `PLC0414` outside `__init__.py`). `digest.py` still imports `rules` for `topics_of`.
- `rules.py` imports `digest_text` at the top and drops both function-level `import digest as store`; `store.heading`/`store.line` become `digest_text.heading`/`digest_text.line`. `rules` imports neither `digest` nor anything that imports it.

- [x] **Step 1:** Create `digest_text.py` with the moved functions; add the re-export and `__all__` to `digest.py`; update `rules.py`. Run the suite. Expected: 2,284 passed plus Task 2's new tests; `test_digest.py` unchanged.
- [x] **Step 2:** Identity: `cd plugins/memory/engine && python3 -c "import digest, digest_text; assert all(getattr(digest, n) is getattr(digest_text, n) for n in ('heading','line','heading_print','line_print'))"`.
- [x] **Step 3:** Format and fix every finding in the three files with the recipes; run the suite after each function.
- [x] **Step 4:** Gate: the three files clean; full suite passes, including `test_mem_corroborate.py`'s digest tests. Commit.

### Task 4: Import-graph test, plan and backlog updated

**Files:**
- Create: `plugins/memory/engine/tests/test_import_graph.py`
- Modify: `docs/superpowers/plans/2026-11-23-memory-refactor.md` (the "Import direction" task), `docs/backlog.md` (A7 row, `Updated`/`Expires` dates), this plan's Status line

- [x] **Step 1:** Write `test_engine_modules_import_no_cycle`: parse every `plugins/memory/engine/*.py` with `ast`; collect each `import x` and `from x import …` (level 0, at any depth, including inside functions and `TYPE_CHECKING` blocks) whose first name part is another engine module; assert no cycle, the failure message listing each cycle as `a -> b -> a`. Write `test_engine_modules_use_no_dynamic_import`: no engine module imports `importlib` or calls `import_module`/`__import__`, whatever the argument, so a cycle cannot hide behind a dynamic import (broadened after the final review).
- [x] **Step 2:** Prove it bites: `git worktree add` the base commit `65e901a` in the scratch directory, copy the test file in, run it there. Expected: the cycle test FAILS naming both cycles. Remove the worktree.
- [x] **Step 3:** Run it on the branch. Expected: PASS; the test file clean.
- [x] **Step 4:** Docs: the refactor plan's "Import direction" task becomes done for `tokenize` and both cycles, with `session_env` moved into the headless task (A2); the backlog A7 row says the same; bump the backlog dates; this plan's Status says implemented, with § Deferred findings open (the backlog's rule ties a done Status to no open work). Run `python3 scripts/validate.py`. Commit.

## Deferred findings

- The TLS branch of `_connection` (`PinnedHTTPS`) has no test (pre-existing). Fixed in the [fixes plan](2026-11-26-memory-fixes.md).
- `plan_commands` raises `TypeError` on a non-string `quote` from verdicts JSON (pre-existing, unhashable key). Fixed in the [fixes plan](2026-11-26-memory-fixes.md): refused as not on the page.
- `fetch_raw` and `apply` options are only type-checked: an unknown key is ignored at runtime (PEP 692 trade-off, ruled).
- Naming and comment-placement nits in `research_checks.py` and `digest.py`: `_shaped`, `_call`, `_RowCheck`, the `Work` docstring still names `given_up`, `DigestFormatError` placement.
- `apply` and `fetch_raw` options are now keyword-only (a positional 5th argument to `apply` raises TypeError; every caller passes keywords).
- No CHANGELOG line: pure refactor, the renamed exception classes are engine-internal (no caller outside plugins/memory/engine).

## Kill criteria

- A recipe needs `research_pipeline.py`, `test_fetch_sources.py`, `bin/*` or another unlisted Python file to change: stop and report.
- `test_fetch_sources.py` or `test_research_checks.py` fails after a `fetch_raw` step: revert that step; a second failure on the same function stops Task 2, and the owner decides between re-planning `fetch_raw` and dropping Task 2 (Task 1's commit then waits on the branch, because it is not fully clean alone).
- The identity check of Task 3 fails or `mem-corroborate`'s digest tests fail: stop Task 3.
