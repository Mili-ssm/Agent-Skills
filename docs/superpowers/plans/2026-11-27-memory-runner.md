# Memory plugin: background passes choose a runner (Claude Code or Codex)

Status: proposed 2026-11-27, amended after its pre-mortem the same day; waiting for the owner's review · Decision: [ADR 0037](../../adr/0037-memory-background-passes-choose-a-runner.md)

Owner, 2026-11-27: a `runner` choice (`claude` | `codex`) for the background passes, given per call, with a default in configuration and as a plugin option. Design and record first, code after the owner's review.

## Session builders today

| Builder | Steps | Tools it allows | Notes |
|---|---|---|---|
| `entry/settle.py` | settle judgments | none (reads a file, writes a verdict file); its env keeps `mem` and `MEM_STORE` (`synthesize/run.py` `session_env`) | Haiku, medium effort; **first scope** |
| `entry/integrate.py` | integrate check | none | Haiku; **first scope** |
| `corroborate/run.py` (+ `corroborate/fill.py`) | corroboration | none | own command for one call site; **first scope** |
| `entry/capture.py` | capture candidates | no Bash, no web | Haiku or Sonnet, `--budget`; later |
| `synthesize/pipeline.py`, `synthesize/references.py` | synthesis writer, reference linker | `Bash(mem <sub>*)` for 12 subcommands, `--agent`, `--plugin-dir`, writes the store through `mem synthesis` | stays on Claude (pre-mortem 2026-11-27) |
| `entry/auto.py` curator | curation pass | `Bash(mem …)`, `mem curate apply --safe` | stays on Claude |
| `research/pipeline.py` | memory step, web step, writing step | web step: `WebSearch,WebFetch` only, sees no store | own `web_cmd` / `file_cmd`; stays on Claude |

Every loop treats a session with no cost report as fatal (`synthesize/pipeline.py` `NO_COST`, `entry/auto.py`, `corroborate/run.py`), and budgets are money (`--max-budget-usd`, `--budget`, `run.gate`); the runner layer must redefine both for Codex.

All go through `core/headless.py` (`Session`, `command`, `run_raw`, `session_env`) except the research and corroborate commands noted.

## Tasks

- [ ] 1. Probe `codex exec` before code (throwaway `CODEX_HOME`, plus one run with the real one and `-c` overrides): `which mem` and `mem search` inside the session with `HOME` redirected (must fail), touching the store under `workspace-write` (must fail), each tier model name, a run started from inside a Codex sandbox (network), the `--json` event schema (final message, token usage, tool events), `--output-schema`, `-c model_reasoning_effort`, `--disable hooks` (does this plugin's `SessionStart` stay silent?), how to drop the owner's AGENTS.md and MCP servers, `workspace-write` limited to a run folder, the web search tool (enabled how, what it returns: snippets or page text), time per call. Check: a table in this plan; each later task cites it.
- [ ] 2. Runner layer in `engine/core` (`runner.py`): resolution (flag → `MEM_RUNNER` → config file → `MEM_RUNNER_OPTION` → `claude`), the Codex binary found at run time (`MEM_CODEX`, `PATH`, newest extension folder), Codex argv from a `Session`, output normalized (`has_result` = final message and exit 0; cost 0 plus tokens; a token cap every budget site uses), the Codex environment (`HOME`/`XDG_CONFIG_HOME` = run folder, no `MEM_STORE`, no `mem` on `PATH`); the model table with a repository test against `shared/models.toml`. Check: unit tests per runner; Claude argv byte-identical to today (existing tests).
- [ ] 3. Builders on the runner layer, one commit each: settle, integrate, corroborate; the others refuse `codex` with a clear message (synthesis, curator, research, capture). Budget sites counted in tokens for Codex: `entry/auto.py`, `entry/integrate.py`, `entry/settle.py`, `corroborate/run.py`. Check: each builder's tests gain a Codex case, including a test that the Codex environment finds no store; the full engine suite passes.
- [ ] 4. Settings: `--runner` on each pass command; `runner` in the Claude plugin's `userConfig`, passed as `MEM_RUNNER_OPTION` by `session-env.sh` (shell commands) and explicitly by `session-end.sh`, `session-index.sh` and `pre-compact.sh` (passes they start); the config file read by `engine/core/config.py`; `trial_env.make_env` clears `MEM_RUNNER*`. Check: precedence tests, including a hook-started pass; `claude plugin validate plugins/memory`.
- [ ] 5. Trial on a store copy (`evals/` harness, `trial_env.py`): settle and integrate on the same inputs with each runner; compare decisions, failures, time and tokens/cost. Rule fixed before the run: the same seeded inputs and ground truth for both arms (settle: the 40 derived records of stage W; integrate: its trial set), each arm given `--runner`; Codex passes when its wrong actions are not more than Claude's and no run fails on the runner itself; after the run, `~/.codex/sessions` of the trial home holds nothing outside the run.
- [ ] 6. Docs and release: README (setting, precedence, what stays on Claude and why), CHANGELOG, platform-parity, backlog; ADR 0037 accepted with the trial in a `## Review`.

## Kill criteria

- Any Codex session runs `mem` or writes the store in a probe, test or trial: stop and re-plan isolation.
- The probe shows no final message or no token usage in `--json`: stop (budgets cannot hold).
- A hook-started pass picks the wrong runner in a precedence test: do not ship task 4.
- The trial shows more wrong actions with `codex` than with `claude` on the same inputs.
- A Codex run reads or writes outside its run folder in any test or trial.
- Codex runs of a week cost more plan credits than the same week on Claude would in money, by the owner's judgment.
