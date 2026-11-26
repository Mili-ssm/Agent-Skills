# One headless launcher (`headless.py`, review A2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with the Plan loop of the owner's routing rules (`agent-skills:implementer` per task, `agent-skills:skeptical-reviewer` after each task commit). Steps use checkbox (`- [ ]`) syntax for tracking.

Status: planned · Branch: `refactor/memory-headless` (stacked on `refactor/memory-corroborate-split`, PR #200) · Date: 2026-11-26

**Goal:** the seven builders of `claude -p` sessions in the memory plugin build their command through one spec in `engine/headless.py`, and the three that lack it get `--strict-mcp-config` (owner ruling 2026-11-23); everything else about each session stays as it is.

**Architecture:** `headless.py` (stdlib only, Python 3.10-safe) holds a frozen `Session` spec, `command(Session) -> list[str]` that emits flags in one canonical order, `run_raw(cmd, *, cwd, env, timeout) -> str` (stdout, or the partial stdout of a timed-out session), and `session_env()` with `SESSION_VARS` and `has_mem` moved from `research_pipeline.py`. Each caller keeps its own function name and signature (tests patch them), its own environment builder and its own result parsing (`synth_pipeline.parse`); only the command list and the subprocess call move. `headless` imports nothing from the plugin, so `synth_pipeline`, `research_pipeline`, `backfill`, `corroborate_run`, `bin/mem-capture` and `bin/mem-settle` can all import it without a cycle.

**Tech Stack:** Python 3.12 engine, 3.10 for `bin/` and what it imports; Ruff 0.17.6, basedpyright 1.40.2, pytest with xdist, pre-commit.

**Spec:** [refactor plan](2026-11-23-memory-refactor.md) task "One headless launcher and one job lifecycle" (the `headless.py` half; `jobs.py` is A3, a later plan) and its owner rulings: A2 after the corroborate split; each launcher keeps its own session environment builder; `mem-capture` gets the same tool restriction as `mem-corroborate` (`--tools Read,Write --strict-mcp-config`); `mem-settle` and `synth_pipeline` get `--strict-mcp-config`. [Project review](../../studies/2026-11-24-project-review.md) A2, A7 (`session_env` without importing `research_pipeline`). [ADR 0031](../../adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md).

## Builders in scope (inventory 2026-11-26)

| # | Builder | Runner | Env builder (kept) | Flag change |
|---|---|---|---|---|
| 1 | `engine/corroborate_run.py` `session_cmd` | `run_session` | `session_env` (now from `headless`) | none |
| 2 | `bin/mem-capture` `session_cmd` | `run_session` | inline: drops its `SESSION_VARS` | + `--tools Read,Write`, + `--strict-mcp-config` |
| 3 | `bin/mem-settle` `session_cmd` | `session` | `run_env` → `mem-synthesize` `session_env` | + `--strict-mcp-config` |
| 4 | `engine/synth_pipeline.py` `run_session` (builds and runs) | same | caller's env + `MEM_SANDBOX*` | + `--strict-mcp-config` |
| 5, 6 | `engine/research_pipeline.py` `file_cmd`, `web_cmd` | `session` | `session_env` (now from `headless`) | none |
| 7 | `engine/backfill.py` `session_cmd` | `run_session` | caller's env | none |

Out of scope: the eval harnesses' own `claude -p` calls (`evals/*/run_trial*.py`), the `settings.json` writers (nine copies with different file modes), `SESSION_VARS` copies in other env builders (owner: no env unification in A2), `jobs.py` (A3).

## Global Constraints

- Behavior unchanged except the four flag additions in the table. A session's flags, their values, its environment, cwd, timeout, stdin and how its output is parsed stay as they are.
- Flag order: the Claude CLI reads flags by name, so the canonical order of `command` may differ from a builder's old order. Golden tests compare `argv[0:3]` (`claude`, `-p`, prompt) exactly and the rest as a map flag → tuple of values in their order. A value list (`--allowedTools a b c`) keeps its order.
- Canonical order of `command`: `claude -p <prompt>`, `--model`, `--effort`?, `--plugin-dir`?, `--settings`, `--setting-sources project`, `--tools`?, `--strict-mcp-config`, `--allowedTools`?, `--disallowedTools`?, `--output-format stream-json`, `--verbose`, `--no-session-persistence`, `--max-budget-usd`? (formatted `f"{x:.4f}"`), `--agent`? (`?` = only when set). `--strict-mcp-config` is always emitted: after A2 every builder has it.
- `headless.py`: stdlib only; no `datetime.UTC`, `typing.Self`/`Required`/`NotRequired`/`Unpack`, `tomllib`, `StrEnum`, `except*` (`bin/` runs on the system `python3`, Ruff targets `bin/*` at py310); add `"plugins/memory/engine/headless.py" = "py310"` to `[per-file-target-version]` in `ruff.toml` (a stricter target, not a suppression) and a test that parses it with `ast.parse(..., feature_version=(3, 10))` and greps the names above.
- Names and signatures tests patch or call stay: `corroborate_run.session_cmd(claude, work, brief, settings, limits)`, `corroborate_run.run_session(cmd, work)`, `research_pipeline.file_cmd`, `web_cmd`, `session_env` (re-exported through `__all__` while anything imports it there), `backfill.session_cmd`, `synth_pipeline.run_session(...)`, `mem-capture` `session_cmd`/`run_session`, `mem-settle` `session_cmd`/`session`. Cross-module calls go through the module attribute (`headless.command(...)`), so patches keep reaching them.
- Clean (ADR 0031): every touched Python file passes `uvx ruff@0.17.6 check --no-fix`, `uvx ruff@0.17.6 format --check`, `uvx --with pyyaml --with pytest basedpyright@1.40.2 --warnings` with no suppression. Debt at plan base: `bin/mem-settle` 24 Ruff / 4 basedpyright / unformatted; `engine/synth_pipeline.py` 38 / 15 / unformatted; `engine/backfill.py` 9 / 0 / unformatted; the other touched files are clean. A file is cleaned in its own commit before its migration commit, so the migration diff stays readable.
- Recipes as in [the A1 plan](2026-11-26-memory-config.md) Global Constraints, except that `Unpack`/`Required` are not available to code that runs on 3.10 (`bin/*`, `headless.py`): use a `NamedTuple` or a frozen dataclass there. Grep every caller (engine, `bin/` extensionless scripts, `evals/`) before changing a signature, and pin an untested caller with a test.
- Tests: `uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto` (2,452 passed, 5 skipped at plan base); self-checks of `mem-capture`, `mem-settle`, `mem-synthesize` (its last assertion already fails at 65e901a: recorded pitfall), `mem-corroborate` keep their base result.
- Commits pass every hook; no `SKIP` (the split plan's exception has ended).

## Review Focus

1. A golden test that passes for the wrong reason (compares the spec to itself, not the builder's output): each golden test calls the real builder with fixed inputs and compares to a literal written at plan base.
2. A session that gains or loses an env variable (`MEM_*`, `CLAUDE_PLUGIN_*`, `PATH` folders holding `mem`, `MEM_SANDBOX*`): pinned by Task 1's env tests.
3. A timed-out session: `run_raw` returns the partial stdout (bytes decoded, or `""`), as each runner did; `OSError` still reaches the callers that catch it.
4. `bin/mem-capture` and `bin/mem-settle` under the system `python3`: they import `headless` unguarded; nothing 3.11+ in it.
5. The memory plugin defines no MCP server (checked 2026-11-26: no `.mcp.json`, no `mcpServers` in `plugin.json`), so `--strict-mcp-config` on synthesis sessions, which load the plugin with `--plugin-dir`, removes no tool they use.

---

### Task 1: Golden tests of the seven command lines and their environments, at base

**Files:** Create `plugins/memory/engine/tests/test_headless_golden.py`.

- [ ] **Step 1:** For each builder in the table, a test that calls it with fixed inputs (paths under `tmp_path`, fixed prompt, model, budget `0.25`) and asserts `argv[0:3]` and the flag map against literals copied from the current output. Builders 2 and 3 load their `bin/` script the way their existing tests do (`test_mem_capture.py`, `test_settle_run.py`); builder 4 records the `cmd` passed to a stubbed `subprocess.run`.
- [ ] **Step 2:** Env tests: `research_pipeline.session_env()` with a crafted `os.environ` (a `MEM_X`, a `CLAUDE_PLUGIN_ROOT`, each `SESSION_VARS` name, a PATH folder holding an executable `mem`) returns the expected dict; same for `mem-capture`'s inline env (through its `run_session` with `subprocess.run` stubbed), `mem-synthesize`'s `session_env`, and `synth_pipeline.run_session`'s `MEM_SANDBOX`/`MEM_SANDBOX_ROOTS` additions.
- [ ] **Step 3:** A helper `flag_map(argv) -> dict[str, tuple[str, ...]]` in the test file (a flag is a token starting with `--`; its values are the tokens up to the next flag).
- [ ] **Step 4:** Run the file at base: all pass. Commit `test(memory): golden command lines and environments of the seven headless sessions`.

### Task 2: `engine/headless.py`

**Files:** Create `plugins/memory/engine/headless.py`, `plugins/memory/engine/tests/test_headless.py`. Modify `ruff.toml` (`[per-file-target-version]`).

**Interfaces (produced):**
- `class Session` (frozen dataclass): `claude: str`, `prompt: str`, `model: str`, `settings: Path`, `effort: str | None = None`, `plugin_dir: Path | None = None`, `tools: tuple[str, ...] | None = None`, `allowed: tuple[str, ...] = ()`, `disallowed: tuple[str, ...] = ()`, `max_budget: float | None = None`, `agent: str | None = None`.
- `command(session: Session) -> list[str]` in the canonical order of Global Constraints; `tools` joined with `,`; empty `allowed`/`disallowed` emit no flag.
- `run_raw(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> str`: `subprocess.run(..., check=False, stdin=DEVNULL, capture_output=True, text=True)`; on `TimeoutExpired` returns the partial stdout decoded; `OSError` propagates.
- `SESSION_VARS`, `has_mem(folder: str) -> bool`, `session_env() -> dict[str, str]` moved verbatim from `research_pipeline.py`.

- [ ] **Step 1:** Tests: `command` for a minimal and a full `Session` (exact lists); `run_raw` with a fake executable script that prints, one that sleeps past a 0.2 s timeout after printing (partial output returned), and a missing binary (`OSError`); `session_env` as in Task 1 Step 2; the 3.10 guard test (`ast.parse(feature_version=(3, 10))`, banned names). Run: fail (no module).
- [ ] **Step 2:** Implement; move the three env names out of `research_pipeline.py`, which imports them from `headless` and re-exports `session_env`, `SESSION_VARS`, `has_mem` through `__all__` (no `import x as x`).
- [ ] **Step 3:** File tests, Task 1 goldens, full suite pass; lint clean on `headless.py`, `research_pipeline.py`, the tests. Commit `refactor(memory): headless.py, the spec and runner of claude -p sessions`.

### Task 3: Engine builders on `headless`: corroborate, research, backfill

**Files:** Modify `engine/corroborate_run.py`, `engine/research_pipeline.py`, `engine/backfill.py` (clean it first, own commit).

- [ ] **Step 1:** `backfill.py` clean, behavior unchanged; commit `refactor(memory): backfill clean`.
- [ ] **Step 2:** `corroborate_run.session_cmd`, `research_pipeline.file_cmd`/`web_cmd` (and `work_tools`), `backfill.session_cmd` return `headless.command(headless.Session(...))`; their runners call `headless.run_raw` and keep their own parsing and `OSError` handling. `corroborate_run` uses `headless.session_env()` and no longer imports `research_pipeline` (A7 leftover; add the edge check to `test_import_graph.py` if it lists forbidden edges).
- [ ] **Step 3:** Goldens unchanged and passing; suite; `mem-corroborate --self-check`; lint clean. Commit `refactor(memory): corroborate, research and backfill sessions through headless`.

### Task 4: `synth_pipeline.run_session` on `headless`, with `--strict-mcp-config`

**Files:** Modify `engine/synth_pipeline.py` (clean first, own commit), `engine/tests/test_headless_golden.py`.

- [ ] **Step 1:** `synth_pipeline.py` clean, behavior unchanged; `run_session` keeps its signature (callers: `bin/mem-synthesize`, `evals/synthesis/run_trials.py`, tests: grep). Commit `refactor(memory): synth_pipeline clean`.
- [ ] **Step 2:** In the golden test, add `--strict-mcp-config` to builder 4's expected map; run: fails.
- [ ] **Step 3:** `run_session` builds through `headless.command` and runs through `headless.run_raw`; its log, timing and `MEM_SANDBOX*` env stay. Golden, suite, lint pass. Commit `fix(memory): synthesis sessions load no MCP server (--strict-mcp-config)`.

### Task 5: `bin/mem-capture` and `bin/mem-settle` on `headless`, with their flags

**Files:** Modify `bin/mem-capture`, `bin/mem-settle` (clean first, own commit), `engine/tests/test_headless_golden.py`.

- [ ] **Step 1:** `bin/mem-settle` clean, behavior unchanged (py310: no `Unpack`). Commit `refactor(memory): mem-settle clean`.
- [ ] **Step 2:** Goldens: builder 2 gains `--tools Read,Write` and `--strict-mcp-config`, builder 3 gains `--strict-mcp-config`; run: fail.
- [ ] **Step 3:** Both builders through `headless.command`, runners through `headless.run_raw`; env builders unchanged (`mem-capture` inline, `mem-settle` `run_env`). Goldens, suite, both `--self-check`s, lint pass. Commit `fix(memory): capture and settle sessions load no MCP server; capture has only Read and Write`.

### Task 6: Gate and docs

- [ ] **Step 1:** `pre-commit run --from-ref <plan base> --to-ref HEAD` passes; `python3 scripts/validate.py`; `claude plugin validate .`.
- [ ] **Step 2:** `plugins/memory/CHANGELOG.md` `[Unreleased]` `### Changed`: capture, settle and synthesis sessions no longer load MCP servers; capture sessions have only the Read and Write tools. Refactor plan: tick the `headless.py` half of the task and note `jobs.py` (A3) still open; backlog A2 and A7 rows; this plan's Status. Commit.

## Kill criteria

- A golden literal would have to change in Task 3, or in Tasks 4–5 beyond the listed flag additions: stop and report.
- `headless` would need to import a plugin module, or a module would import another in a cycle: stop and re-cut.
- A test patch stops reaching its code (patched on one module, called through another).
- A self-check result differs from base.
- Something in `headless.py` needs Python 3.11+: re-cut instead of raising the floor of `bin/`.
