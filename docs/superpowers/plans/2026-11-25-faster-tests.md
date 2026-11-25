# Faster test runs, cleaning each touched test file

Status: in progress (2026-11-25) · Branch: `perf/faster-tests` (stacked on `chore/ruff-pyright`, PR #192)

## Goal and rules

The owner wants quicker develop-and-test loops, with every touched Python file cleaned under ADR 0031 (`python3 scripts/lint_touched.py` exits 0) as the work goes.

Baseline (2026-11-25, 20 cores): memory engine suite 2,272 passed, 5 skipped in 287 s serial; time is spread (430 tests ≥ 0.1 s, 47 ≥ 1 s); slowest files `test_mem_corroborate.py` 77 s, `test_capture_auto.py` 38 s, `test_capture_sweep.py` 21 s; fixed lock waits up to 10 s (`store_git.LOCK_WAIT`). `scripts/tests`: 231 tests in about 1 s, out of scope.

## Tasks

- [x] 1 Parallel runs: `pytest-xdist -n auto` in the documented engine command (CLAUDE.md, the memory plan's state table, plugin README); check: two full runs green, wall time recorded (first measure: 51 s and 41 s, no flaky failure)
- [ ] 2 Lock and timer waits; each touched file passes `lint_touched.py`
  - [x] 2a Test-only waits: `test_store_git` 10.1→0.24 s, `test_capture_sweep` 3.0→0.32 s, `test_plugin_shell` 3.0→1.5 s; parallel suite 38–39 s
  - [x] 2b (5.3→0.8 s; `mem-capture` refactored for lint, review pending) `mem-capture` polls its lock every 5 s (hard-coded): make the poll configurable, shorten `test_capture_auto::test_waits_for_the_lock_then_continues` (5.3 s); cleans `bin/mem-capture` and `test_capture_auto.py`
  - Kept as is: `test_digest` 4.4 s is CPU work (301 `mem.main` calls), `test_settle_run`/`test_auto_curation` 2 s are negative windows longer than the measured 0.8–1.2 s hook latency
- [ ] 3 Spawn cost (measured by `performance-analyst`, 2026-11-25): tests set `HOME`, so every `bin/mem` launch runs `uv` with an empty cache (0.45 s vs 0.1 s, and needs network)
  - [ ] 3a `UV_CACHE_DIR` shared in the autouse `isolated_env` (conftest.py); check: serial corroborate 93→~54 s, full suite twice
  - [ ] 3b Optional, owner to choose: `CSafeLoader` in `records.py`/`notes.py` (9× faster frontmatter parse; `test_digest` long pole ~6→~2–3 s; cleans `records.py`, 40 findings); shorter negative waits in `test_settle_run`/`test_auto_curation` need a real "nothing started" signal
- [ ] 4 Review, PR to `dev`
