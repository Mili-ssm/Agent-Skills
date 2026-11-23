# Memory plugin structure assessment

Status: sequence adopted (owner, 2026-11-23): the test-environment fix and the two speed fixes first, then G1 to G4, then steps 1 to 7 in a plan of their own · Date: 2026-11-23

Should the `memory` plugin be refactored or reorganized to make it cleaner and easier to maintain, and in what order relative to the commit gate (G1 to G4, [plan](../superpowers/plans/2026-11-23-memory-research-gaps.md)) and a possible Rust port ([study](2026-11-23-memory-rust-port.md))? Assessment by the `architect` agent; the findings marked **verified** were re-run by the main session.

## Conclusion

Refactor in small, behavior-preserving steps, not a rewrite. The code is not tangled (the largest function outside the argument parser is 124 lines); the problems are one 7,146-line module, settings resolved in about eight places with different precedence, and seven drifting copies of the code that starts `claude -p` sessions. All three sit in the most-changed files and in the way of the ports and of Rust. One defect needs fixing before any other engine work: the test suite reads the developer's environment.

## Findings

| # | Finding | Evidence | Impact | Severity |
|---|---|---|---|---|
| 1 | `mem.py` is a god module | 7,146 lines, half the engine; 316 top-level functions, 69 subcommands; its section banners already mark seams (index, check, search, rename and unify, fetch, CLI, curation, history, syntheses, hook commands). 116 of 324 plugin commits touch it, 51 of them fixes | Maintainability; a Rust port of one blob | high |
| 2 | Settings resolved in many places | store resolution in `mem.py` (reads the config file), `records.py`, `research_pipeline.py` and `bin/mem-synthesize` (both ignore it), plus four shell copies in hooks; the state folder resolved five times; 11 files read `CLAUDE_PLUGIN_OPTION_*`, 17 `MEM_*` variables. **Verified harm:** `conftest.py` clears `MEM_STORE`/`MEM_MEMORIES` but not `MEM_RULES_LAYOUT`, so `test_rules.py` gives 3 failed inside a session with `rules_layout: digest` and 30 passed without it (`test_rules_session.py` 3 more) | Correctness; ports | high |
| 3 | Seven copies of the `claude -p` launcher, drifting | `bin/mem-capture`, `bin/mem-corroborate`, `bin/mem-settle`, `backfill.py`, `synth_pipeline.py`, `research_pipeline.py` (2); only the corroborate copy passes `--tools Read,Write --strict-mcp-config`; the `--claude` default repeated 6 times | Ports (this is the tool-specific seam); safety drift | medium |
| 4 | Dependency direction | `research_checks.py` and `research_pipeline.py` import all of `mem` for three helpers; a `rules`↔`digest` cycle hidden by lazy imports. G1 avoids a new cycle by passing the check as a parameter to `store_git` (already in its plan) | Maintainability | medium |
| 5 | The `yaml` pitfall remains in `mem-research` | **Verified:** `bin/mem-research` runs on the system `python3` and reaches `mem.py`'s unguarded `import yaml` | Fails on machines without a system `pyyaml` | medium |
| 6 | `bin/` holds a second engine | about 3,970 lines of Python; `mem-auto` and `mem-settle` load the `mem-synthesize` script with `SourceFileLoader` | Maintainability; testability | medium |
| 7 | The current state is hard to find | **Verified:** the plan's state table says 0.9.0 released while `plugin.json` is 0.10.0; it says project syntheses' code is not merged while `project_syntheses.py` ships; cells of 1,100 to 1,500 characters; 38 plans and specs for this plugin | Onboarding; decisions on stale facts | medium |
| 8 | Parked code ships | the signal command and `hooks/signal.sh` are not registered in `hooks.json` | Maintainability | low |
| 9 | Two download paths | `mem._download` (docstring: "the only network access", false) and `research_checks.fetch_text` (with host guards); two HTML extractors | Security drift | low |
| 10 | Citations of the note repository's ADRs and requirements | 16 citations in `mem.py` (ADR 0004, 0008; C-10, C-13, C-14) that mean something else in this repository | Misleading | low |

Tests: about 340 to 400 s for the full suite (340 s at the 0.9.0 release, about 400 s estimated from one partial run), spread out (slowest 25 tests about 80 s); 60 test files import `mem`, 514 in-process `mem.main` calls and 32 patches on `mem` names, so every move updates patch targets.

## Recommended sequence

Each step passes the existing suite with no behavior change.

| # | Step | Extra check | Size | Unblocks | When |
|---|---|---|---|---|---|
| 0 | `conftest.py` clears every `MEM_*` and `CLAUDE_PLUGIN_OPTION_*` variable | suite passes inside a session and under `env -i` | S | a trustworthy safety net | first, before any engine change |
| 1 | Cut the plan's "Current state" to a short table of facts; release history to the CHANGELOG; fix the stale rows | `validate.py`, links resolve | S | finding the current state | with G1 to G4 (their plan's docs task updates the state table) |
| 2 | A pure `config.py` (environment and arguments in, paths and options out) and one shared file the shell hooks source; pin each entry point's current precedence with tests first, then merge only the copies that already agree | one table test: every entry point resolves the same way | S | ports, Rust | before ports and Rust |
| 3 | Move `notes.py` (frontmatter, notes, topics) and `check.py` out of `mem.py`; `mem` re-exports them | import-graph test: no cycle, only the CLI imports `mem` | S–M | G3 rules as check rules; Rust | before Rust |
| 4 | One `headless.py` that starts `claude -p` from a spec | golden tests of each caller's current command line, written first | M | Codex and Copilot ports | before ports |
| 5 | Move `mem-synthesize`'s logic into the engine; `bin/` keeps launchers only; one interpreter policy | each launcher's self-check | M | fixes finding 5 | before Rust |
| 6 | Split the rest of `mem.py` one seam per pull request (search, edit, curation, history, hook commands, CLI), `mem.py` staying as a facade | pure modules import no `subprocess` or `os.environ`; a line ceiling on `mem.py` | L | a clean core for Rust | the search, notes and check parts before Rust |
| 7 | Remove or keep the parked code after the kill read (about 2026-12-01) | suite | S | — | any time |

## What not to do

- Split `mem.py` in one pull request: 514 in-process calls and 32 patches would break at once.
- Add a command registry or class hierarchy for the 69 subcommands: the functions are small and the dispatch works.
- Turn the engine into an installable package: it breaks the `uv --script` header (ADR 0023).
- Remove the import guards in `mem-capture` and `mem-corroborate`: they let a failed run record its status.
- Move the 38 plugin docs into new folders: it breaks links; an index is enough.
- Start a Rust port before steps 2 to 4: it would carry the duplication over.

## Decisions for the owner

| Decision | Options |
|---|---|
| Store precedence | every entry point honours the config file, or keep it per entry point (`mem-research` and `mem-synthesize` ignore it today) |
| Capture session tools | **ruled 2026-11-23: restrict like corroborate** (step 4) |
| `bin/` interpreter | **ruled 2026-11-23: `uv` for all** (step 5) |
| Parked code | remove after the kill read, or keep behind an option |

A proposed ADR (engine modules form an acyclic graph around a pure core; `mem.py` is the CLI facade) is drafted in the agent's report and becomes ADR 0028 if the owner adopts the sequence.
