# Memory engine: Rust port analysis

Status: decided — no port now (owner, 2026-11-23); recorded in ADR 0023 · Date: 2026-11-23

Would porting the `memory` engine to Rust pay off in run time, and how hard is it to reach full parity on a parallel branch? Stage 8 of the [memory plugin plan](../superpowers/plans/2026-11-17-memory-plugin.md) asks for this decision "with measured latencies"; ADR 0023 sets the trigger: a hook still over its budget after the engine keeps a search index on disk. Measurements by the `performance-analyst` agent on 2026-11-23 (20 cores, load 0.2, Python 3.14 under `uv`, libyaml present, store of 1,132 notes and about 390 memories, 20 runs after 2 warm-ups); the loader sites and the trigger were re-checked by the main session.

## Conclusion

Not now. The time goes to Python start-up and to a slow YAML loader, not to the logic Rust would speed up, and two small Python changes bring the over-budget hook from p50 442 ms to 273 ms (outputs byte-identical). The record model changed in 24 commits in six days, the worst moment for a second implementation. ADR 0023's trigger has not fired; the next steps are the two fixes, then a parse cache or on-disk index, and Rust only if a hook is still over budget after that. If a port is chosen later, port the hot path (parsing, search, index, check, about 4,000 to 5,000 lines) as a separate binary behind the same CLI, not the `claude -p` pipelines.

## Measured times

| Command (wall, through `bin/mem`) | p50 ms | p95 ms | Budget |
|---|---|---|---|
| SessionStart hook script | 442 | 539 | 500: **over at p95** |
| `session-index --hook` | 376 | 391 | inside the hook |
| `search` (3 queries) | 432–441 | 459 | none (interactive) |
| `show` one memory | 248 | 260 | none |
| `find --topic llm` | 221 | 344 | none |
| `check` (whole store) | 1,006 | 1,029 | none; 1.5 s if it ran in `SessionEnd` |
| `--help` (start-up floor) | 157 | 164 | — |
| SessionEnd hook (hook log, n = 54) | 18 | 95 | 1,500 |

The hook log under-reports: it times only the work inside `mem` (session-index p50 75 ms logged against 376 ms wall), so start-up (about 260 ms) never shows in it. The logged p50 rose from 45 to 162 ms as the store grew over five days.

## Where the time goes

| Cost | Size | Cause |
|---|---|---|
| YAML parsing | about 0.6 s of 1.26 s for `search` under the profiler; 0.58 of 0.87 s for `session-index` | `records.py`, `syntheses.py` (2 sites) and `project_syntheses.py` call `yaml.safe_load`, the pure-Python loader; only `mem.py` uses `CSafeLoader` |
| Compiling `mem.py` on every run | 70 ms | it runs as `__main__`, so its 7,146 lines are never cached as `.pyc` |
| Imports | about 140 ms in all | `http.client`, `yaml`, `corroborate` and others loaded eagerly |
| `check` | `rule_syntheses` 0.96 s of 2.2 s under the profiler, `rule_links` 0.46 s | re-parsing syntheses and path arithmetic |

## Python-side fixes, measured on a scratch copy

| Command | Before | `CSafeLoader` at the 4 sites | Plus a launcher that imports `mem` (cached `.pyc`) |
|---|---|---|---|
| SessionStart hook | 442 | 270 | 273 |
| `session-index --hook` | 376 | 277 | 201 |
| `search` | 441 | 343 | 277 |
| `show` | 248 | — | 157 |
| `--help` | 157 | 152 | 93 |

Outputs are byte-identical for `search`, `check`, `find`, `memories`, `stats` and `session-index`; the test suite gives the same result with and without the change. The launcher needs a writable plugin folder for its `.pyc` (not verified for installed copies). Not yet tried: a parse cache (would remove most of the remaining YAML cost), lazy imports (about 10 to 20 ms), cheaper `check` rules.

## What a port would involve

| Item | Size |
|---|---|
| Engine | 14,147 lines in 20 files; `mem.py` 7,146 (316 functions, 69 subcommands, 202 options) |
| Hot path worth porting (parsing, tokenizer, BM25, index, check, rules) | about 4,000–5,000 lines (inferred) |
| `claude -p` pipelines (capture, corroborate, settle, research, synthesis) | about 3,700 lines; I/O-bound on the model, nothing to gain |
| Python-specific behavior to reproduce | the custom YAML loader (dates and on/off kept as strings, duplicate keys rejected), Python `re` semantics, the Unicode tokenizer, `argparse` error text, `fcntl` locks, `git` and `pdftotext` calls |
| Tests | 80 files, 23,800 lines, 1,862 test functions: 514 in-process CLI calls (57 files) can run against a binary once routed through an executable runner; about 1,300 direct calls into modules need an FFI or a rewrite |
| Model churn | 24 commits to `records.py` since 2026-11-17 (23 of them on 11-22 and 11-23), about 12 of them new fields |

### Parity on a parallel branch

1. Freeze a schema version of the records and notes first; until then every model change lands twice.
2. Route the CLI-level tests through an executable named by an environment variable, so one suite runs against `bin/mem` and the Rust binary.
3. Byte-diff stdout and the written store files on a copy of the real store, per command, in both directions.
4. Fixtures for the YAML, date and tokenizer edge cases (the parity risk).
5. Ship per command: the Python CLI delegates a command to the binary once its diff is empty; the pipelines stay in Python.

Dependencies on the [structure assessment](2026-11-23-memory-plugin-structure.md): its steps 2 to 4 (one config module, `notes` and `check` out of `mem.py`, one `claude -p` launcher) come first, or the port copies the duplication.

## Options

| Option | For | Against |
|---|---|---|
| (a) Python with targeted fixes | measured: hook 442 → 273 ms, search 441 → 277 ms; no build step; model still moving | `check` stays about 1 s; the store doubled the logged hook time in five days, so growth needs a parse cache or index |
| (b) Hot path in Rust (separate binary or PyO3) | search and index in tens of ms (inferred) | two implementations of a schema that changed 24 times in six days; per-platform builds and no CI for them (ADR 0023) |
| (c) Full port to parity | removes the start-up floor entirely | about 14,000 lines plus a harness for 23,800 lines of tests; 3,700 lines of pipelines gain nothing |

## Revisit when

A hook's p95 stays over its budget after the two fixes and a parse cache or on-disk index (ADR 0023), or the record schema has gone a month without a new field.
