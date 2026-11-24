# Memory plugin refactor plan

Status: planned, not started (owner, 2026-11-23: postponed for usage limits); extended 2026-11-24 with the [project review](../../studies/2026-11-24-project-review.md) (A2–A5 and A7, owner ruling); runs after the security fixes (branch `fix/memory-security`) · Date: 2026-11-23

Behavior-preserving refactor of `plugins/memory`, from steps 2 and 4 to 7 of the [structure assessment](../../studies/2026-11-23-memory-plugin-structure.md#recommended-sequence), which holds the findings, evidence and each step's extra check. Steps 0, 1 and 3 (the `notes.py`, `index.py` and `check.py` split) shipped with the [research-gaps plan](2026-11-23-memory-research-gaps.md). Each task passes the full suite with no behavior change; one pull request per task, to `dev`.

## Owner rulings that bind it

- Every `bin/` script runs through `uv` (one interpreter policy; fixes the `yaml` pitfall of `mem-research`).
- `mem-capture` gets the same tool restriction as `mem-corroborate` (`--tools Read,Write --strict-mcp-config`).
- Code files at 1,000+ lines get a split review; split by locality (functions used together stay together). Since 2026-11-24 (owner) this is one case of a wider rule: every edit leaves the code it touches compliant or better.
- Rust: not now; this refactor is the precondition the [Rust study](../../studies/2026-11-23-memory-rust-port.md) names.

## Tasks

- [ ] **Config**: a pure `config.py` (environment and arguments in, paths and options out) and one file the shell hooks source; pin each entry point's current precedence with tests first. Check: one table test, every entry point resolves the same way.
- [ ] **One headless launcher and one job lifecycle**: `headless.py` starts `claude -p` from a spec, replacing the seven copies; `mem-capture`, `mem-settle` and `synth_pipeline` get `--strict-mcp-config` as ruled (review A2). `jobs.py` beside it holds the background-job lifecycle copied in four scripts: `data_dir`, budget, status, log, ack, prune, `failure_line` (review A3). Check: golden tests of each caller's current command line and job files, written first.
- [ ] **Import direction (quick)**: import `tokenize` from `records`, get `session_env` without importing `research_pipeline` (review A7). Check: an import-graph test with no cycles (also catches `digest`↔`rules`).
- [ ] **`bin/` holds launchers only**: `mem-corroborate`'s `Journal`, `Applier`, `execute` and its fill, reword and digest jobs into engine modules on a shared job runner (review A4), then `mem-synthesize` logic into the engine; all scripts through `uv`; split `test_mem_corroborate.py` by job with them. Check: each launcher's self-check; `mem-research` runs without a system `pyyaml`; the 6 tests that load bin scripts keep passing through re-exports.
- [ ] **Split `records.py`** (1,323 lines) by locality. Check: suite; no module over 1,000 lines without a recorded reason.
- [ ] **Split the rest of `mem.py`** (5,924 lines) one feature per pull request, each module taking its own `cmd_*` handlers with its logic (review A5: handlers sit about 4,500 lines from their logic, so a split along the section banners would leave them behind): search, memory lifecycle, rename and unify, fetch, synthesis commands, hook commands; `mem.py` stays a facade and the parser. Record the split in ADR 0028. Also move `orphan_notes` and the due queries next to their callers. Check: pure modules import no `subprocess` or `os.environ`; a line ceiling on `mem.py`.
- [ ] **Session-end cost**: measure `find_claude` in `hooks/session-end.sh` and cache or drop it if it costs more than a few milliseconds. Check: hook timing before and after (p50 and p95).
- [ ] **Parked code**: remove or keep the signal command and `hooks/signal.sh` after the kill read (about 2026-12-01). Check: suite.
