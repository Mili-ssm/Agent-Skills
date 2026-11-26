# Memory plugin fixes before the rest of the refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with the owner's Plan loop (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax.

Status: implemented, PR to dev pending · Branch: `fix/memory-fixes` (from `dev` b62e41b) · Date: 2026-11-26

**Goal:** the memory engine's suite passes on Python 3.12 as on 3.15, and the open deferred findings of the 2026-11-26 sub-plans that are defects (not A4 restructuring) are fixed.

**Architecture:** test-loader fixes plus small, test-first defect fixes in `engine/`; no module moves. Findings tied to the shared corroborate job runner (`_finish`, `_digest_sheet`/`_reword_sheet`, `_Filler._log`, underscore names) stay with the rest of A4.

**Tech Stack:** Python 3.12 engine (3.11 for `bin/` and what it imports, ADR 0033); Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist.

**Spec:** owner order 2026-11-26 ("fixes first, then the refactors"); § Deferred findings of [config](2026-11-26-memory-config.md), [import-direction](2026-11-26-memory-import-direction.md), [corroborate-split](2026-11-26-memory-corroborate-split.md), [headless](2026-11-26-memory-headless.md), [jobs](2026-11-26-memory-jobs.md); 3.12 run of 2026-11-26 on CPython 3.12.0 (2484 passed, 14 failed, 27 errors).

## Global Constraints

- ADR 0031: every touched Python file passes `uvx ruff@0.17.6 check --no-fix`, `uvx ruff@0.17.6 format --check`, `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings`; no noqa, no `type: ignore`, no config edits. Measured at base: `test_backfill.py` 33 Ruff (incl. 3 noqa), unformatted, 1 basedpyright; `test_synthesize_references.py` unformatted; `test_mem_capture.py` 66 Ruff, unformatted, 16 basedpyright; `test_capture.py` 22 Ruff, unformatted, 3 basedpyright; `handoff.py` 5 Ruff, unformatted. Clean a file in its own commit before the fix that touches it.
- Suite: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2525 passed, 5 skipped at base) stays green.
- Version matrix (`mem.py` declares `>=3.12,<3.15`; `--python 3.12` alone now resolves to 3.12.12): run the suite with `uv run -q --no-project --python <V> --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto -p no:cacheprovider` for V in `3.12.0`, `3.13.5`, `3.14.4` (the supported range) and the default (3.15). `bin/` self-checks also on `3.11.15` (ADR 0033).
- A test-side loader registers the module before executing it (pitfall: `@dataclass` before 3.15, measured on 3.12.0, 3.13.5, 3.14.4): at import time `sys.modules[name] = module`; in a function-scoped fixture `monkeypatch.setitem(sys.modules, name, module)` so it is removed on teardown.
- Re-exported pytest fixtures keep their imports through `__all__ = [...]` with the comment `# re-exported: pytest finds the fixture in this module by its name` (the noqa replacement used in A1-A3); no `conftest.py` move.
- User-visible fixes get a `plugins/memory/CHANGELOG.md` `[Unreleased]` line; test-only fixes do not.
- Commits pass every hook; no `SKIP`.

## Review Focus

1. A loader fix that registers under a name another test also registers (stale module across tests in one xdist worker).
2. A fix that changes 3.15 behavior while making 3.12 pass.
3. A diagnosis that blames the test when the engine is wrong on 3.12 (users run `mem` on whatever 3.12+ `uv` finds).

---

### Task 1: 3.12 test parity of the loaders

Unregistered loaders (pre-mortem 2026-11-26): `test_capture.py` (`mem_capture_brief`), `test_mem_capture.py` (`mem_capture_bin`, `mem_capture_module`, `mem_capture_module2`), `test_backfill.py` (`mem_synthesize_bin`; `test_synthesize_references.py` imports its `ms`).

- [x] 1a `test_backfill.py`: clean commit, then loader commit. 1b `test_synthesize_references.py`: clean commit. 1c `test_capture.py`: clean, then loader. 1d `test_mem_capture.py` (66 Ruff, 16 basedpyright): clean, then loader. Parallel worktrees, cherry-picked.
- [x] 1e Extend `test_bin_python_floor.py`'s registration guard from `bin/` to `engine/tests/` and `evals/`, accepting `monkeypatch.setitem(sys.modules, ...)`.
- [x] Check: no `'NoneType' object has no attribute '__dict__'` on 3.12.0; suite green on every matrix version except Tasks 2-3's known tests.

### Task 2: `handoff.mismatches` on an over-long plan name under 3.12

- [x] `test_handoff.py::test_lines_are_short` fails on 3.12 and 3.13 (0 lines instead of 1 for a 404-character name): `Path.is_file` raises `OSError` errno 36 up to 3.13 and returns False from 3.14 (pre-mortem, measured), and `handoff.py`'s `except` returns `[]`. Fix: `os.path.isfile(target)` (the 3.14 behavior on every version; verified on a scratch copy). Check: `test_handoff.py` passes on 3.12.0, 3.13.5, 3.14.4, 3.15.

### Task 3: unclosed `<script>`/`<style>` text extraction on 3.12

- [x] Two `test_research_checks.py` tests fail on 3.12.0 and pass on 3.12.12 and 3.13.5: 3.12.0's `HTMLParser.close()` leaves the text after an unclosed `<script>`/`<style>` in `rawdata` instead of calling `handle_data`. Make `html_text` independent of the patch level (candidate: fall back to `parser.rawdata` when nothing was collected after close; output unchanged on patched versions). Check: both tests on every matrix version; no patch floor.

### Task 4: timed-out session cut inside a multibyte character

- [x] Headless finding: `headless.run_raw` strict-decodes timed-out partial output (`partial.decode()` when `errors is None`), so bytes cut inside a UTF-8 character raise `UnicodeDecodeError`; callers without `errors=`: `backfill`, `bin/mem-settle`, `bin/mem-capture`, `research_pipeline`, `synth_pipeline`. Test first; on timeout only, drop just the incomplete trailing sequence (incremental decoder, `final=False`); the normal path and invalid bytes elsewhere keep their behavior. Check: new test, `test_headless_golden.py` unchanged.

### Task 5: the same-second fill test proves what it names

- [x] Corroborate-split finding (Q9): the test of two fill runs in the same second passes without its `time.strftime` patch. Make it fail when the collision guard is removed (mutation check by hand). Test-only.

### Task 6: research checks: TLS branch test and non-string `quote`

- [x] Import-direction findings: add a test for the `PinnedHTTPS` branch of `_connection`; `plan_commands` treats a non-string `quote` in verdicts JSON as a bad row instead of raising `TypeError`. Check: new tests; suite green.

### Task 7: `mem-synthesize --self-check` last assertion

- [x] Config finding: the self-check fails its last assertion. Cause (pre-mortem, replayed): the self-check's fake `claude` writes an empty note with `touch`, which fails `mem check`, so the commit gate (`0a56b2c`, 2026-11-23) holds it back by design. Fix the fixture (the fake writes a note that passes `mem check`) and add a pytest that runs `--self-check`. Check: self-check passes on 3.12.0 and default Python; the gate code (`store_git.py`, commit gate) is untouched.

### Task 8: Gate and docs

- [x] `pre-commit run --from-ref dev --to-ref HEAD`; `python3 scripts/validate.py`; `claude plugin validate .`; the full version matrix green; `bin/` self-checks on 3.11.15. Update each sub-plan's deferred rows (ruling "Fixed here (fix/memory-fixes)"), the jobs plan row on 3.12, `docs/backlog.md` (stale "A1 is done on branch" text; fixes done), resume state in `2026-11-17-memory-plugin.md`, CHANGELOG lines for user-visible fixes.

## Deferred findings

| Finding | Ruling |
|---|---|
| On every Python, text inside a `hidden` element can reach `html_text`'s output after an unclosed `<script>`/`<style>` (the resume parser starts without the `hidden` state); 3.12.0 now behaves like later patches | Open, low: pre-existing on patched versions; a quote check could match hidden text |
| A non-string `quote` is refused with the "not on the fetched page" text, as `None` already was | Accepted: a type-specific reason would add a branch for malformed JSON only |
| The registration guard looks 5 lines back and does not check that the registered name is the loaded module | Accepted: every current loader passes; a stricter scope check costs more than the risk |
| `test_auto_curation.py` and `test_store_precedence.py` register with `sys.modules[...] =` and never remove the entry | Open, low: pre-existing, no failure seen |
| The `mem-synthesize` self-check cannot assert a store-wide `mem check` exit 0 (fixture findings); it asserts no finding names the fake note | Accepted |
| The self-check pytest needs `uv` (it runs `bin/mem`) | Accepted: the suite already needs `uv` |
| Review round 2, low, deferred: the TLS spy forwards attribute writes no code path makes; the multibyte timeout test is still timing-based (2.0 s margin, about 2 s per run); the guard skips its own file wholesale; the self-check reads the note from `HEAD`, so a later trailing commit in `run()` would break it | Deferred: no failure seen; revisit if one flakes or `run()` changes |
| Process review: trailing unfinished markup (`x<p`, an open comment) is kept as text on CPython 3.12.0 and 3.13.5 and dropped on 3.12.12, 3.14 and 3.15 | Open, low: stdlib behavior, same on `dev`; the script/style handoff was narrowed to `raw_tag` so it cannot add to it |
| `test_curation.py::test_session_index_near_the_budget_is_fast` failed once under `-n auto` on 3.12.0 (wall-clock assert), passed alone | Open, low: pre-existing timing test (backlog Q5 class) |
| Review round 1 findings rejected: `math.isclose` for a float constant (Ruff RUF069 forbids `==`); the `__all__` re-export comment (the repo's recipe) | Ruling |

## Kill criteria

- A fix needs a module move or a signature change beyond the fixed function: park it for A4.
- Task 3 still fails on 3.12.0 after the fallback: stop and ask the owner about a patch floor.
- A Task 7 diff touches `store_git.py` or the commit-gate logic: stop and ask the owner.
- After Task 1, a `__dict__` error remains on 3.12.0: find the other loader before moving on.
- Any test fails on 3.13.5 or 3.14.4 that passes on 3.15: stop and report.
- The 3.15 suite count drops.
