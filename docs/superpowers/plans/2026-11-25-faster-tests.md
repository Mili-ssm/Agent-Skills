# Faster test runs, cleaning each touched test file

Status: done (2026-11-25), PR #193 · Branch: `perf/faster-tests` (was stacked on #192, merged)

## Goal and rules

The owner wants quicker develop-and-test loops, with every touched Python file cleaned under ADR 0031 (`python3 scripts/lint_touched.py` exits 0) as the work goes. (Written when the check was `scripts/lint_touched.py`; pre-commit replaced it the same day, ADR 0031: the equivalent is `pre-commit run --from-ref origin/dev --to-ref HEAD`.)

Baseline (2026-11-25, 20 cores): memory engine suite 2,272 passed, 5 skipped in 287 s serial; time is spread (430 tests ≥ 0.1 s, 47 ≥ 1 s); slowest files `test_mem_corroborate.py` 77 s, `test_capture_auto.py` 38 s, `test_capture_sweep.py` 21 s; fixed lock waits up to 10 s (`store_git.LOCK_WAIT`). `scripts/tests`: 231 tests in about 1 s, out of scope.

## Tasks

- [x] 1 Parallel runs: `pytest-xdist -n auto` in the documented engine command (CLAUDE.md, the memory plan's state table, plugin README); check: two full runs green, wall time recorded (first measure, before the shared uv cache of 3a: 51 s and 41 s, no flaky failure)
- [x] 2 Lock and timer waits; each touched file passes `lint_touched.py`
  - [x] 2a Test-only waits: `test_store_git` 10.1→0.24 s, `test_capture_sweep` 3.0→0.32 s, `test_plugin_shell` 3.0→1.5 s; parallel suite 38–39 s
  - [x] 2b (5.3→0.8 s; `mem-capture` refactored for lint, review pending) `mem-capture` polls its lock every 5 s (hard-coded): make the poll configurable, shorten `test_capture_auto::test_waits_for_the_lock_then_continues` (5.3 s); cleans `bin/mem-capture` and `test_capture_auto.py`
  - Kept as is: `test_digest` 4.4 s is CPU work (301 `mem.main` calls), `test_settle_run`/`test_auto_curation` 2 s are negative windows longer than the measured 0.8–1.2 s hook latency
- [x] 3 Spawn cost (measured by `performance-analyst`, 2026-11-25): tests set `HOME`, so every `bin/mem` launch runs `uv` with an empty cache (0.45 s vs 0.1 s, and needs network)
  - [x] 3a (suite 30–32 s parallel, twice) `UV_CACHE_DIR` shared in the autouse `isolated_env` (conftest.py); check: serial corroborate 93→~54 s, full suite twice
  - [x] 3b Owner chose two: `CSafeLoader` was already in use (`notes._BaseLoader`), nothing to gain; negative windows re-measured with the warm cache (settle max 0.45 s under load, warm cache; kept at 1.5 s as `NEGATIVE_WINDOW` because a cold cache adds ~0.35 s; auto-curation max 1.31 s, kept at 1.5–2 s), both files lint clean
- [x] 4 Review, PR to `dev`

## Result

Memory engine suite: 287 s serial → 29–36 s parallel (2,272 passed, 5 skipped, several runs). Files cleaned under ADR 0031: `test_store_git`, `test_capture_sweep`, `test_plugin_shell`, `test_capture_auto`, `test_settle_run`, `test_auto_curation`, `conftest`, `bin/mem-capture` (refactored for complexity, reviewed for equivalence).
