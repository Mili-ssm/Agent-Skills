# Memory plugin: background passes choose a runner (Claude Code or Codex)

Status: ADR 0037 accepted by the owner 2026-11-27; tasks 1-6 done; release (memory 0.18.0) pending the owner · Decision: [ADR 0037](../../adr/0037-memory-background-passes-choose-a-runner.md)

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

- [x] 1. Probe `codex exec` before code (results in § Task 1 results; web search and a pass started from inside a Codex sandbox not probed: the web step stays on Claude, and the nested case is task 4's) (throwaway `CODEX_HOME`, plus one run with the real one and `-c` overrides): `which mem` and `mem search` inside the session with `HOME` redirected (must fail), touching the store under `workspace-write` (must fail), each tier model name, a run started from inside a Codex sandbox (network), the `--json` event schema (final message, token usage, tool events), `--output-schema`, `-c model_reasoning_effort`, `--disable hooks` (does this plugin's `SessionStart` stay silent?), how to drop the owner's AGENTS.md and MCP servers, `workspace-write` limited to a run folder, the web search tool (enabled how, what it returns: snippets or page text), time per call. Check: a table in this plan; each later task cites it.
- [x] 2. Runner layer in `engine/core` (`runner.py`): resolution (flag → `MEM_RUNNER` → config file → `MEM_RUNNER_OPTION` → `claude`), the Codex binary found at run time (`MEM_CODEX`, `PATH`, newest extension folder), Codex argv from a `Session`, output normalized (`has_result` = final message and exit 0; cost 0 plus tokens; a token cap every budget site uses), the Codex environment (`HOME`/`XDG_CONFIG_HOME` = run folder, no `MEM_STORE`, no `mem` on `PATH`); the model table with a repository test against `shared/models.toml`. Check: unit tests per runner; Claude argv byte-identical to today (existing tests).
- [x] 3. Builders on the runner layer, one commit each: settle, integrate, corroborate; the others refuse `codex` with a clear message (synthesis, curator, research, capture). Budget sites counted in tokens for Codex: `entry/auto.py`, `entry/integrate.py`, `entry/settle.py`, `corroborate/run.py`. Check: each builder's tests gain a Codex case, including a test that the Codex environment finds no store; the full engine suite passes.
- [x] 4. Settings: `--runner` on each pass command; `runner` in the Claude plugin's `userConfig`, passed as `MEM_RUNNER_OPTION` by `session-env.sh` (shell commands) and explicitly by `session-end.sh`, `session-index.sh` and `pre-compact.sh` (passes they start); the config file read by `engine/core/config.py`; `trial_env.make_env` clears `MEM_RUNNER*`. Check: precedence tests, including a hook-started pass; `claude plugin validate plugins/memory`.
- [x] 5. (closed 2026-11-27 by owner decision, see § Task 5 final: settle passes on Codex with its addendum; integrate is Claude-only; corroborate not tried on real Codex) Trial on a store copy (`evals/` harness, `trial_env.py`): settle and integrate on the same inputs with each runner; compare decisions, failures, time and tokens/cost. Rule fixed before the run: the same seeded inputs and ground truth for both arms (settle: the 40 derived records of stage W; integrate: its trial set), each arm given `--runner`; Codex passes when its wrong actions are not more than Claude's and no run fails on the runner itself; after the run, `~/.codex/sessions` of the trial home holds nothing outside the run.
- [x] 6. Docs (release left open: memory 0.18.0, bump, tag, after the owner's go): README (setting, precedence, what stays on Claude and why), CHANGELOG, platform-parity, backlog; ADR 0037 accepted with the trial in a `## Review`.

## Task 1 results (2026-11-27)

`codex-cli 0.171.0-alpha.13.2` (the VS Code extension's binary), throwaway `CODEX_HOME` with `memory` 0.17.0 installed from a local marketplace on `origin/dev`, `env -i` with `HOME` and `XDG_*` set to the run folder and `PATH=/usr/bin:/bin`.

| Question | Observed |
|---|---|
| `--json` events | `thread.started`, `turn.started`, `item.started`/`item.completed` (`agent_message` with `text`; `command_execution` with `command`, `aggregated_output`, `exit_code`), `turn.completed` with `usage` (`input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens`); no money figure. Final text = the last `agent_message` |
| A step that writes a file | `-s workspace-write -C <run folder>`: the model wrote `verdict.json` there |
| `mem` and the store from the session | `command -v mem` found nothing; `touch` on the real store failed (sandbox); reading by absolute path stays possible (the known weakness, ADR 0037) |
| This plugin's hooks inside the session | `--dangerously-bypass-hook-trust` alone: `SessionStart` ran (2 hook lines); with `--disable hooks`: none; with `--ignore-user-config`: none |
| Tier models | `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.2-sol` all answered |
| Cost of a trivial call | about 44k input tokens (38k cached) and 315 output tokens on `gpt-6-luna`: Codex's own system prompt dominates, so the token cap per pass must allow for it |

## Kill criteria

- Any Codex session runs `mem` or writes the store in a probe, test or trial: stop and re-plan isolation.
- The probe shows no final message or no token usage in `--json`: stop (budgets cannot hold).
- A hook-started pass picks the wrong runner in a precedence test: do not ship task 4.
- The trial shows more wrong actions with `codex` than with `claude` on the same inputs.
- A Codex run reads or writes outside its run folder in any test or trial.
- Codex runs of a week cost more plan credits than the same week on Claude would in money, by the owner's judgment.

## Task 5 results (2026-11-27)

Harnesses: `--runner claude|codex` on `evals/settle/run_trial.py` and `evals/integrate/run_trial.py`; the Codex arm sets `MEM_CODEX` (newest VS Code extension binary, `codex-cli` 26.1120) and the real `CODEX_HOME` in its env (`trial_env.apply_runner`). One run per arm, same inputs: settle on `target/settle-trial` (55 base, 40 derived, `--runs 2`), integrate on `seed.json` (33 loose notes). Results files: `target/iso/` (git-ignored).

| Pass | Arm | Acted / placed | Wrong | Retrieval misses | Failures | Wall | Claude USD | Codex tokens |
|---|---|---|---|---|---|---|---|---|
| settle | claude | 18 of 20 should-act | 0 of 40 | 0 | 0 | 75 s | 0.033 | 0 |
| settle | codex | 20 of 20 should-act | 1 of 40 (a `version` row merged) | 0 | 0 | 75 s | 0 | 126138 |
| integrate | claude | 22 notes integrated, 14 sentences appended (17 `append` seeds: 14 joined) | 0 | n/a | 0 | 38 s | 0.014 | 0 |
| integrate | codex | 7 notes integrated, 0 appended (all 17 `append` seeds left loose; 4 of 5 restatements and 3 of 3 duplicates joined) | 0 | n/a | 0 | 18 s | 0 | 61521 |

Integrate criteria 3 (unbacked sentences, a paid Sonnet audit) and 7 (cost) stay `pending` for both arms: the audit was not run.

**Verdict by the rule: Codex fails on settle** (1 wrong action against 0 for Claude), so kill criterion 4 ("more wrong actions with `codex` than with `claude` on the same inputs") fired for settle. Integrate meets the rule (0 wrong, no runner failure) but Codex placed far fewer notes (7 against 22) and appended none: a recall gap, not a wrong action. No run failed on the runner itself in either pass. Task 5 stays open. One run per arm gives no variance: the single wrong action may be noise (Codex also acted on 20 of 20 against Claude's 18), so a rerun at more runs needs the owner's decision.

Isolation checks (before/after snapshots): real store files and mtimes identical; `~/.local/state/agent-memory` identical; `~/.codex/sessions` no new file; `git status` shows only the harness files. Not attributable: `~/.codex/logs_2.sqlite-wal/-shm` and `models_cache.json` changed during the window (the VS Code extension runs there too); no file under `~/.codex/sessions` appeared. Claude spend of the trial: 0.047 USD of the 2 USD cap.

### Diagnosis run (2026-11-27)

Before the prompt fixes, one more run per arm with `MEM_DIAG_DIR` keeping each session's input and reply (raw files in `target/diag/`, git-ignored; tokens not recorded). Settle on Codex merged the same pair as in the first trial (`a-headless-eval-started-with-claude-plugin-eval` into `a-headless-trial-launched-from-inside-a-claude`: the second loses the first's command). Integrate on Codex again appended 0 of 17; its place step proposed no `append` at all, reading "what that part covers" as only what the part's sentences already say. Claude appended 16 of 17.

## Task 5 rerun after prompt fixes (2026-11-27)

Pre-registered before any rerun. Prompt fixes (owner-approved, model-neutral): the settle brief's `merge` row says a pair where one claim states anything the other lacks is not a merge (choose `nothing`); the integrate place step's input gains a `subject` per part (the part's heading) and the brief defines a part as covering its `subject`, not only what its sentences say.

Runs: 3 per arm per pass (settle claude, settle codex, integrate claude, integrate codex), same inputs as the first trial (`target/settle-trial` with `derived.json`, `--runs 2`; integrate `seed.json`). Spend cap for Claude: 0.5 USD for the rerun (owner's total cap 2 USD, about 0.09 spent before).

Rule:
- Codex passes a pass when its median wrong actions <= Claude's median and no run fails on the runner itself; for integrate also Codex median appends >= 8 of 17.
- Claude must not regress: settle median wrong 0 and should-act acted >= 17 of 20; integrate median wrong 0 and median appends >= 12 of 17. If Claude regresses, the prompt change is reverted (numbers recorded) even if Codex improved.
- Task 5 is ticked only if both passes meet the rule.

### Results (3 runs per arm, in parallel; raw output in `target/rerun/`, git-ignored)

| Pass | Arm | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|---|
| settle: should-act acted (of 20) / wrong (of 40) | claude | 16 / 0 | 17 / 0 | 16 / 0 | 16 / 0 |
| settle | codex | 20 / 0 | 19 / 0 | 18 / 1 | 19 / 0 |
| integrate: appends (of 17) / wrong | claude | 0 / 0 (void: the reply had a prose line above the rows, so the place answer was "not rows or none") | 0 / 0 (same failure) | 10 / 0 | 0 / 0 |
| integrate | codex | 0 / 0 (5 notes integrated) | 1 / 0 (8 notes) | 0 / 0 (6 notes) | 0 / 0 |

Spend: Claude about 0.10 USD (settle 0.078, integrate 0.025), within the 0.5 cap. Codex runs failed no run on the runner itself.

**Verdict by the rule: both changes reverted** (`git revert`, commits `6cd9660` and `e2ae50c`).
- Settle: Codex passes (median wrong 0 <= 0, no runner failure; the one wrong action in run 3 is the earlier `version` merge), but Claude regresses: median acted 16 of 20 (< 17), against 18 in the first trial.
- Integrate: Claude regresses (median appends 0, two runs void because the reply carried a prose line before the rows; the Claude replies seen held the right rows, e.g. 6 appends for one part, so the subject text made it add a comment); Codex median appends 0 (< 8), so the subject field did not close the recall gap either.
- Task 5 stays open. Not established: whether the settle drop of Claude (16/17/16 against one earlier run of 18) is the brief or noise; the earlier single run gives no variance.

## Task 5 final (2026-11-27)

Owner decision 2026-11-27: Codex ships as experimental. The shared settle brief stays as before the reverted fix (Claude's recall is kept); Codex sessions of settle append a Codex-only addendum (`entry/settle.py` `CODEX_ADDENDUM`: a pair where one claim states anything the other lacks is not a merge, choose `nothing`). Integrate is Claude-only (Codex placed 0 of 17 appends in 4 runs); its Codex path is removed. Corroborate is not tried on real Codex: unit-tested with the fake only.

Pre-registered before the run: settle on Codex, 3 runs, same inputs as the first trial (`target/settle-trial` with `derived.json`, `--runs 2`), harness `evals/settle/run_trial.py --runner codex`; Codex plan credits only, no Claude spend. Rule: Codex settle passes when the median wrong actions <= 0 and no run fails on the runner itself.

### Results (3 runs, Codex only; raw logs in `target/final/`, git-ignored)

| Run | Should-act acted (of 20) | Wrong (of 40) | Runner failures | Tokens | Wall |
|---|---|---|---|---|---|
| 1 | 16 | 0 | 0 | 146246 | 83 s |
| 2 | 15 | 0 | 0 | 154513 | 86 s |
| 3 | 16 | 0 | 0 | 145029 | 80 s |
| Median | 16 | 0 | 0 | 146246 | 83 s |

**Verdict by the rule: Codex settle passes** (median wrong 0 <= 0, no run failed on the runner). Cost of the addendum: Codex's recall falls to a median 16 of 20 (19 without it, rerun), the same level as Claude's rerun, in exchange for no wrong action in 3 runs (the unfixed brief gave 1 wrong in run 3 of the earlier rerun). Task 5 is ticked: settle is the Codex-experimental pass; integrate is out of Codex scope by decision; corroborate is untested on real Codex (fake-codex unit tests only).

## Known limits after the code review (2026-11-27)

Fixed: `sync_auth` copied any newer valid JSON from the run folder (the sandbox's writable root) over the real `auth.json`; it now requires the same `tokens.account_id` and non-empty tokens.

Deferred (low, or bounded by the session timeout):
- The token cap is checked between sessions only: `codex exec` takes no token limit, so one session is bounded by its timeout (600 s), not the cap; one `mem-corroborate` run gives fill, reword, digest and the pass one cap each.
- When the real `auth.json` is a symlink, a refreshed token stays in the run folder until runs are pruned.
- A timeout kills `codex`, not its shell children; the last 5 stderr lines go unredacted into the status file.
- Unprobed: whether the sandbox lets a session write the real `auth.json` through the run folder's link.
