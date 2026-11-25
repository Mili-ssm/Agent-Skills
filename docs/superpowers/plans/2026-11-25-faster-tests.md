# Faster test runs, cleaning each touched test file

Status: in progress (2026-11-25) · Branch: `perf/faster-tests` (stacked on `chore/ruff-pyright`, PR #192)

## Goal and rules

The owner wants quicker develop-and-test loops, with every touched Python file cleaned under ADR 0031 (`python3 scripts/lint_touched.py` exits 0) as the work goes.

Baseline (2026-11-25, 20 cores): memory engine suite 2,272 passed, 5 skipped in 287 s serial; time is spread (430 tests ≥ 0.1 s, 47 ≥ 1 s); slowest files `test_mem_corroborate.py` 77 s, `test_capture_auto.py` 38 s, `test_capture_sweep.py` 21 s; fixed lock waits up to 10 s (`store_git.LOCK_WAIT`). `scripts/tests`: 231 tests in about 1 s, out of scope.

## Tasks

- [x] 1 Parallel runs: `pytest-xdist -n auto` in the documented engine command (CLAUDE.md, the memory plan's state table, plugin README); check: two full runs green, wall time recorded (first measure: 51 s and 41 s, no flaky failure)
- [ ] 2 Lock and timer waits: tests that sit out a real wait (10 s, 5 s, 3 s, 2 s) shorten it through the module constant or an option; each touched file passes `lint_touched.py`; check: the same tests pass, their durations fall
- [ ] 3 Next slowest files by measured cost (start: `test_mem_corroborate.py`): find the per-test cost (subprocess spawns, fixture copies), cut it, clean the file; check: durations before/after, full suite green twice in parallel
- [ ] 4 Review, PR to `dev`
