# Memory plugin: Codex parity (capture, options, agents) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: proposed 2026-11-27, amended after a pre-mortem the same day; waiting for the owner's review · Decision: [ADR 0038](../../adr/0038-memory-codex-parity-capture-and-agents.md) (proposed)

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

### Task 1: Probe Codex before code

**Files:** results table in this plan (§ Task 1 results). No code.

- [ ] Throwaway `CODEX_HOME` with the plugin installed from a local marketplace, a hook that dumps its stdin JSON and `command -v claude` to a file, run in `codex exec`, the TUI (`tmux`, `--no-daemon`) and **the VS Code extension** (the owner's host: `originator: codex_vscode`; the owner opens and closes a thread, then the window), for `SessionStart`, `SessionEnd`, `PreCompact`: record `transcript_path`, `cwd`, `source`/`trigger`, whether `transcript_path` exists when the hook runs, and whether `SessionEnd` fires at all in the extension.
- [ ] `SessionEnd` hook starts `setsid nohup sh -c 'sleep 20; touch <marker>'`: does the marker appear after `codex exec` exits, and after the TUI exits?
- [ ] Spawn one Codex subagent: record its rollout's `session_meta.payload.thread_source` / `source`.
- [ ] Change `codex.json` in the throwaway home: do the already-trusted hooks keep running until re-trust, or does the whole set stop?
- [ ] On one real rollout: where the owner's prompt text lives (`event_msg` `user_message` vs `response_item` `message` role `user`), which user-role items are injected (environment context, AGENTS.md, skills), tool call and output item types, `compacted` items.
- [ ] Check: the table exists; if the marker never appears and `SessionStart` has no `transcript_path`, stop and re-plan (ADR 0038 Revisit); if `SessionEnd` never fires in the extension, Task 4 relies on the sweep alone and its live check must pass on the next day's start.

### Task 2: Plugin options from config files on Codex

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

### Task 4: Codex hooks for session end, pre-compact and sweep

**Files:**
- Modify: `plugins/memory/hooks/codex.json` (add `SessionEnd` → `MEM_HOST=codex session-end.sh`, timeout 3; `PreCompact` → `MEM_HOST=codex pre-compact.sh`, timeout 5), `pre-compact.sh` (no handoff text when `MEM_HOST=codex`, capture only), `engine/entry/capture.py` (sweep on Codex: the day folders of the last `SWEEP_MAX_AGE_DAYS` days, filtered by `session_meta.payload.cwd` and `thread_source == user` before a file counts as examined; Review Focus 5, 6, 7)
- Test: `plugins/memory/engine/tests/hooks/test_codex_hooks.py`, sweep tests in `tests/capture/`

**Interfaces:**
- Consumes: `codex_options` (Task 2), `codex_rollout` (Task 3).

- [ ] Tests: `test_codex_json_declares_session_end_and_pre_compact` (timeouts 3 and 5, `MEM_HOST=codex`); `test_pre_compact_prints_nothing_on_codex`; `test_sweep_on_codex_day_folder_picks_codex_sessions_only`; `test_sweep_reads_previous_day_folders`; `test_other_project_rollouts_do_not_consume_examined`; `test_subagent_rollouts_not_swept`; `test_sweep_skips_folder_without_memory_dir` (Review Focus 3); `validate.py` checks the Codex manifest still.
- [ ] Implement; run engine suite, `python3 scripts/validate.py`, `claude plugin validate plugins/memory`: PASS. Commit.
- [ ] Live check in the throwaway `CODEX_HOME`: one `codex exec` session in a folder with a memory folder and `auto_capture` file = `true` leaves a capture status line (`mem-capture` log) and a history commit; a session killed at its end (no `SessionEnd`) is captured by a session start the next day; nothing written to the real store or the owner's `~/.codex` (before/after snapshot).

### Task 5: Memory agents as Codex roles

**Files:**
- Modify: `scripts/port.py` (emit `plugins/memory/agents/*.md` as `ports/codex/memory/agents/*.toml`), `scripts/tests/` (a port test), `plugins/memory/README.md` § Codex (copy step), `docs/ports.md` if it lists outputs
- Generated: `ports/codex/memory/agents/*.toml`

- [ ] Tests: each memory agent yields one TOML with `name`, `description`, `developer_instructions`, `model` from the tier table, `model_reasoning_effort` from its `effort`; read-only agents' instructions carry the tool-limit rule the `agent-skills` port uses; `port.py --check` fails when the TOML is stale; no generated role contains `~/.claude` (the synthesizer's skill lookup, `agents/memory-synthesizer.md`, gains a Codex path: `~/.codex/plugins/cache`).
- [ ] Implement; run `python3 scripts/port.py`, `uv run --with pytest pytest scripts/tests -q`, `python3 scripts/validate.py`: PASS. Commit.

### Task 6: Live checks left from ADR 0037

**Files:** results in this plan; fixes only if a check fails (then a new task).

- [ ] Corroborate on real Codex: one run on a store copy (`evals/trial_env.py`), `--runner codex`, token cap default; record tokens, verdicts, and that the real store is unchanged.
- [ ] A pass started from inside a Codex session (sandbox `workspace-write`): `mem-settle run --runner codex --minutes 0` from a Codex turn; record whether the nested `codex exec` runs (network, sandbox) and what it prints.
- [ ] Check: the results table; a failure becomes a documented limit or a new task.

### Task 7: Docs and release prep

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
