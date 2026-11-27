# Memory plugin: Codex parity (capture, options, agents) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: accepted by the owner 2026-11-27 (after a pre-mortem the same day); execution: subagent-driven; tasks 1-7 done 2026-11-27, release 0.19.0 pending the owner · Decision: [ADR 0038](../../adr/0038-memory-codex-parity-capture-and-agents.md) 

**Goal:** Codex sessions get what Claude sessions get from the memory plugin, except what Codex cannot carry: automatic capture and history commit, plugin options, and the memory agents.

**Architecture:** Hooks and engine stay one code path. Codex gets three more hook entries in `hooks/codex.json`, a helper that turns option files into the `CLAUDE_PLUGIN_OPTION_*` variables the scripts already read, and a second transcript decoder behind `capture.extract.extract()`. Agents come from `scripts/port.py` as TOML roles.

**Tech Stack:** bash hooks, Python 3 engine (stdlib), pytest, `codex-cli` 0.171 (VS Code extension binary).

**Spec:** ADR 0038.

## Global Constraints

- Hooks are silent and always exit 0; Codex `SessionEnd` timeout at most 3 s; every long step runs detached (`setsid nohup`).
- The capture pass stays on `claude -p` (ADR 0037); no `claude` binary means capture skips with no error.
- A file under `~/.config/agent-memory/` never overrides a set `CLAUDE_PLUGIN_OPTION_*` variable.
- Never log or copy `~/.codex/auth.json`; probes use a throwaway `CODEX_HOME` with an `auth.json` symlink (ADR 0037).
- Generated files (`ports/**`) are written only by `scripts/port.py`.
- Every commit passes Ruff, basedpyright, `python3 scripts/validate.py`; never `--no-verify`.
- `hooks/codex.json` changes need the owner to re-trust the hooks; probes run in a throwaway `CODEX_HOME`.

## Review Focus

1. A rollout with only `session_meta` and developer messages (a session that never got a prompt): the extract is empty and capture records nothing.
2. Injected text in user-role items (`<environment_context>`, AGENTS.md, skill bodies) must not count as the owner's words.
3. A Codex session in a folder with no project memory folder: the sweep settles it without a model run, as for Claude.
4. An option file holding `true\n` or ` true `: read as `true` (first line, stripped), like `store`.
5. Two transcript families in one sweep: a Claude session start sweeps Claude sessions only, a Codex one Codex sessions only.
6. Codex keeps rollouts in day folders that mix every project (`~/.codex/sessions/YYYY/MM/DD`), unlike Claude's per-project folder: anything keyed on `transcript.parent` (the sweep) behaves differently.
7. Codex subagent threads have their own rollouts (`session_meta.payload.thread_source` other than `user`): never captured as owner sessions.

---

### Task 1: Probe Codex before code (done 2026-11-27, § Task 1 results)

**Files:** results table in this plan (§ Task 1 results). No code.

- [ ] Throwaway `CODEX_HOME` with the plugin installed from a local marketplace, a hook that dumps its stdin JSON and `command -v claude` to a file, run in `codex exec`, the TUI (`tmux`, `--no-daemon`) (the VS Code extension, the owner's host, `originator: codex_vscode`, is checked in Task 4's live check with the real hooks and the hook log, so no probe hook enters the owner's `~/.codex`), for `SessionStart`, `SessionEnd`, `PreCompact`: record `transcript_path`, `cwd`, `source`/`trigger`, whether `transcript_path` exists when the hook runs, and whether `SessionEnd` fires at all in the extension.
- [ ] `SessionEnd` hook starts `setsid nohup sh -c 'sleep 20; touch <marker>'`: does the marker appear after `codex exec` exits, and after the TUI exits?
- [ ] Spawn one Codex subagent: record its rollout's `session_meta.payload.thread_source` / `source`.
- [ ] Change `codex.json` in the throwaway home: do the already-trusted hooks keep running until re-trust, or does the whole set stop?
- [ ] On one real rollout: where the owner's prompt text lives (`event_msg` `user_message` vs `response_item` `message` role `user`), which user-role items are injected (environment context, AGENTS.md, skills), tool call and output item types, `compacted` items.
- [ ] Check: the table exists; if the marker never appears and `SessionStart` has no `transcript_path`, stop and re-plan (ADR 0038 Revisit); if `SessionEnd` never fires in the extension, Task 4 relies on the sweep alone and its live check must pass on the next day's start.

## Task 1 results (2026-11-27)

`codex-cli` 0.171.0-alpha.13.2 (VS Code extension binary 26.1120), throwaway `CODEX_HOME` with a probe plugin whose hooks dumped their input; `codex exec` and the TUI (tmux). The owner's own VS Code rollout read for comparison (first 50 characters of user items only). The owner's `~/.codex` unchanged before and after.

| Question | Observed |
|---|---|
| Events | `SessionStart`, `SessionEnd`, `SubagentStart` in exec and TUI; `PreCompact` then `PostCompact` on `/compact` (TUI; `trigger` `manual`) |
| Payload | `session_id`, `transcript_path`, `cwd`, `hook_event_name`; plus `model`, `permission_mode` (start events), `turn_id` (compaction, subagent); `source` `startup`; `reason` `other`; no `thread_source` key |
| `transcript_path` | exists already at `SessionStart` and at `SessionEnd` |
| `claude` in a hook | on `PATH` |
| `SessionEnd` timeout | clamped to 3 s |
| Detached process after `SessionEnd` | a `setsid nohup` process survived 20 s after exit, in exec and TUI (VS Code: Task 4 live check) |
| Subagent | `SubagentStart` carries the parent `session_id` and the subagent's own `transcript_path`, `agent_id`, `agent_type`; the subagent rollout is a separate file in the same day folder, `session_meta.payload.thread_source` `subagent` (parent: `user`) |
| Rollout user items | the prompt is a `response_item` `message` role `user`; the same items also carry injected `<environment_context>` and, when present, `# AGENTS.md instructions` (owner's VS Code rollout); skills are developer messages. Duplicates of the prompt: `event_msg` `user_message` (VS Code) or `event_msg` `item_completed` `UserMessage` (CLI): ignored |
| Tool items | `custom_tool_call` (`exec`) with `custom_tool_call_output`; `function_call`/`function_call_output` (subagent tools) |
| Compaction in the rollout | a `compacted` item (`message`, `replacement_history`) |
| Re-trust | after `codex.json` changed, **no** hook of the plugin ran until re-trusted (including `SessionStart`): a release that changes `codex.json` turns the session index off until the owner re-trusts |
| `originator` / `source` | VS Code `codex_vscode`/`vscode`; TUI `codex-tui`/`cli`; exec `codex_exec`/`exec` |

Consequences for later tasks: Task 3 takes owner text only from `response_item` role `user`, dropping items that start with `<environment_context>` or `# AGENTS.md instructions`, and skips rollouts whose `thread_source` is not `user`; Task 4 needs no subagent filter in the hooks (the payload has no `thread_source`) but the sweep reads it from `session_meta`; Task 7 documents re-trust as a required step of every update that changes `codex.json`.

### Task 2: Plugin options from config files on Codex (done: f093542, 6ead686)

**Files:**
- Create: `plugins/memory/hooks/codex-options.sh`
- Modify: `plugins/memory/hooks/session-index.sh`, `session-end.sh`, `pre-compact.sh`, `subagent-start.sh` (source the helper first when `MEM_HOST=codex`)
- Test: `plugins/memory/engine/tests/hooks/test_codex_options.py`

**Interfaces:**
- Produces: shell function `codex_options` — for each name in `userConfig` of `.claude-plugin/plugin.json` except `store` and `runner` (the engine reads those files itself), when `CLAUDE_PLUGIN_OPTION_<UPPER>` is unset and `${XDG_CONFIG_HOME:-$HOME/.config}/agent-memory/<name>` exists, export the variable with that file's first line, stripped.

- [ ] Tests (run the helper with `bash -c`): `test_file_sets_unset_option` (file `auto_capture` = `true\n` → `CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE=true`); `test_set_variable_wins` (variable `false`, file `true` → `false`); `test_missing_file_leaves_unset`; `test_whitespace_stripped` (` true ` → `true`); `test_xdg_config_home_honoured`; `test_option_list_matches_plugin_json` (fails on drift).
- [ ] Implement; source it in the four hooks only when `MEM_HOST=codex`. Shell commands in a Codex session see no hook-exported variables (no `session-env.sh` equivalent), so the `auto_settle` trigger after a write stays Claude-only: document it in Task 7.
- [ ] Run `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/hooks -q`: PASS. Commit.

### Task 3: Codex rollout decoder for capture

**Files:**
- Create: `plugins/memory/engine/capture/codex_rollout.py`; fixture `plugins/memory/engine/tests/capture/fixtures/codex-rollout.jsonl` (synthetic, built from the Task 1 schema; no real session text)
- Modify: `plugins/memory/engine/capture/extract.py` (`_decode` picks the decoder), `plugins/memory/engine/entry/capture.py` (`first_cwd` reads `session_meta.payload.cwd` and `turn_context.payload.cwd`)
- Test: `plugins/memory/engine/tests/capture/test_codex_rollout.py`

**Interfaces:**
- Consumes: Task 1 schema table.
- Produces: `codex_rollout.events(entry: dict, names: dict, state: dict) -> list[str]`, same event line format as `extract._events` (owner text, assistant text, tool use with its argument, failed tool result); `codex_rollout.is_rollout(first_line: str) -> bool` (`type == "session_meta"`). `extract()` keeps its signature and return.

- [ ] Tests: `test_owner_prompt_becomes_a_user_event`; `test_injected_user_items_are_dropped` (environment context, AGENTS.md text, skill bodies: Review Focus 2); `test_assistant_message_and_tool_call_events`; `test_failed_tool_output_marked_like_claude`; `test_meta_only_rollout_gives_empty_extract` (Review Focus 1); `test_user_prompt_counted_once` (one source of owner text, from the Task 1 table); `test_subagent_rollout_gives_empty_extract` (Review Focus 7); `test_known_ignored_types_not_counted_as_skipped` (`token_count`, `token_usage_record`, `reasoning`, `world_state`); `test_unknown_item_counts_as_skipped_not_error`; `test_claude_transcript_unchanged` (existing fixtures, byte-identical extract); `test_first_cwd_from_session_meta`.
- [ ] Implement; the decoder is chosen once per file from its first line.
- [ ] Run the capture tests and the full engine suite: PASS. Commit.

### Task 4: Codex hooks for session end, pre-compact and sweep (done: 713a184, 58fa808 and a round-2 fix; deferred low: another project's rollouts are re-read (first line, ~29 KB) at every start, since the shared store keys swept sizes by file only; a session started 8+ days ago but changed within 7 is not scanned; VS Code and next-day checks are the owner's after the release)

**Files:**
- Modify: `plugins/memory/hooks/codex.json` (add `SessionEnd` → `MEM_HOST=codex session-end.sh`, timeout 3; `PreCompact` → `MEM_HOST=codex pre-compact.sh`, timeout 5), `pre-compact.sh` (no handoff text when `MEM_HOST=codex`, capture only), `engine/entry/capture.py` (sweep on Codex: the day folders of the last `SWEEP_MAX_AGE_DAYS` days, filtered by `session_meta.payload.cwd` and `thread_source == user` before a file counts as examined; Review Focus 5, 6, 7)
- Test: `plugins/memory/engine/tests/hooks/test_codex_hooks.py`, sweep tests in `tests/capture/`

**Interfaces:**
- Consumes: `codex_options` (Task 2), `codex_rollout` (Task 3).

- [ ] Tests: `test_codex_json_declares_session_end_and_pre_compact` (timeouts 3 and 5, `MEM_HOST=codex`); `test_pre_compact_prints_nothing_on_codex`; `test_sweep_on_codex_day_folder_picks_codex_sessions_only`; `test_sweep_reads_previous_day_folders`; `test_other_project_rollouts_do_not_consume_examined`; `test_subagent_rollouts_not_swept`; `test_sweep_skips_folder_without_memory_dir` (Review Focus 3); `validate.py` checks the Codex manifest still.
- [ ] Implement; run engine suite, `python3 scripts/validate.py`, `claude plugin validate plugins/memory`: PASS. Commit.
- [ ] Live check in the throwaway `CODEX_HOME`: one `codex exec` session in a folder with a memory folder and `auto_capture` file = `true` leaves a capture status line (`mem-capture` log) and a history commit; the owner closes a thread and then the window in the VS Code extension and the hook log shows (or not) a `session-end` record with `host=codex`; a session killed at its end (no `SessionEnd`) is captured by a session start the next day; nothing written to the real store or the owner's `~/.codex` (before/after snapshot).

### Task 5: Memory agents as Codex roles (done: fae669f, 3d6beec; deferred low: install-command aborts on an OSError mid-loop; the launcher-coverage test ignores commands with no bin file)

**Files:**
- Modify: `scripts/port.py` (emit `plugins/memory/agents/*.md` as `plugins/memory/codex-agents/*.toml`, inside the plugin so a Codex install carries them; moved there in the fix round), `scripts/tests/` (a port test), `plugins/memory/README.md` § Codex (copy step), `docs/ports.md` if it lists outputs
- Generated: `plugins/memory/codex-agents/*.toml`; also `mem install-command` installs `mem-research` and `mem-synthesize` launchers (the roles call them)

- [ ] Tests: each memory agent yields one TOML with `name`, `description`, `developer_instructions`, `model` from the tier table, `model_reasoning_effort` from its `effort`; read-only agents' instructions carry the tool-limit rule the `agent-skills` port uses; `port.py --check` fails when the TOML is stale; no generated role contains `~/.claude` (the synthesizer's skill lookup, `agents/memory-synthesizer.md`, gains a Codex path: `~/.codex/plugins/cache`).
- [ ] Implement; run `python3 scripts/port.py`, `uv run --with pytest pytest scripts/tests -q`, `python3 scripts/validate.py`: PASS. Commit.

### Task 6: Live checks left from ADR 0037 (done 2026-11-27, § Task 6 results)

**Files:** results in this plan; fixes only if a check fails (then a new task).

- [ ] Corroborate on real Codex: one run on a store copy (`evals/trial_env.py`), `--runner codex`, token cap default; record tokens, verdicts, and that the real store is unchanged.
- [ ] A pass started from inside a Codex session (sandbox `workspace-write`): `mem-settle run --runner codex --minutes 0` from a Codex turn; record whether the nested `codex exec` runs (network, sandbox) and what it prints.
- [ ] Check: the results table; a failure becomes a documented limit or a new task.

## Task 6 results (2026-11-27)

Raw notes: session scratchpad `task6/RESULTS.md` (not kept). About 95k Codex tokens, no Claude calls; the owner's store, state, config and `~/.codex` unchanged.

| Check | Observed |
|---|---|
| Corroborate on real Codex (`mem-corroborate run --runner codex`, isolated copy, 4 invented lessons) | exit 0, ~15k tokens, nothing written: the propose brief ends "Write nothing else and use no other tool" (`corroborate/run.py`, 7 briefs), and `gpt-6-luna` refused to read its input or write its output; the run still ended `ok`, "0 of 0 groups applied" |
| A Codex pass started from inside a Codex session (`workspace-write`) | the nested `codex exec` starts but has no network: status `failed` after ~18 s ("error sending request"), the pair stays pending; a limit, documented in Task 7 |

### Task 6b: Corroborate on Codex reads and writes its files

**Files:** `plugins/memory/engine/corroborate/` (the Codex session path), its tests.

- [x] A Codex-only addendum, as settle's `CODEX_ADDENDUM` (ADR 0037), tells Codex sessions to read the input file and write the output file in the work folder with its shell and run no other command; Claude briefs byte-identical.
- [x] A Codex session that leaves no output file counts as a failed session (status `failed` with its reason), never `ok` with 0 of 0.
- [x] Check: unit tests (Codex prompt carries the addendum, Claude prompt does not; a missing output file fails the run); one live rerun on the same isolated 4-lesson copy groups the 2 paraphrases.

Result (2026-11-27): addendum in `corroborate/run.py` `run_on`; a Codex session with no output file fails. Live: run 1 (without a final-message request) wrote `groups.json` but ended silent, so `failed`, 46k tokens; run 2 (addendum asks for a final `done`): `ok`, 92k tokens, the 2 paraphrases grouped by the proposer, the verifier refused the group as not faithful (model variance).

### Task 7: Docs and release prep (docs done 2026-11-27)

**Files:** `plugins/memory/README.md` (§ Codex: options files, capture, agents, re-trust), `plugins/memory/CHANGELOG.md` `[Unreleased]`, `docs/platform-parity.md` (memory rows), `docs/backlog.md`, ADR 0038 accepted with a `## Review`, the Codex port plan's "outside the core" list.

- [ ] Write; run `python3 scripts/validate.py`, `claude plugin validate .`: PASS. Commit.
- [ ] The release (memory 0.19.0) waits for the owner's go.

## Kill criteria

- Any probe, test or live check writes the real store or the owner's `~/.codex` outside what Codex itself writes: stop.
- Task 1 finds no transcript path at any hook: stop and re-plan.
- The Codex decoder changes a Claude extract by one byte: do not ship Task 3.
- A subagent rollout yields capture candidates: block Task 3.
- `SessionEnd` does not fire in the VS Code extension and the sweep cannot reach earlier day folders: re-plan capture before Task 4.
- The Task 4 live check: a session killed at its end is not captured at the next day's start: do not ship capture.
