# 0038 The memory plugin on Codex gains session capture, plugin options and its agents

Status: accepted · Date: 2026-11-27 · Amends 0036

## Context

ADR 0036 ported the core (session index, `mem`, skills, one shared store) and left out, each to be decided on its own: capture and the history commit at session end, the compaction handoff, and the agents. ADR 0037 added Codex runners for settle and corroborate. On 2026-11-27 the owner asked for feature parity with Claude Code.

Facts (Codex hooks docs, read 2026-11-27; a rollout file of `codex-cli` 0.171 read the same day; [parity plan](../superpowers/plans/2026-11-27-memory-codex-parity.md)):

| Claude feature | What Codex offers |
|---|---|
| `SessionEnd` capture and commit (detached) | `SessionEnd` exists, synchronous, 1 s default, 3 s at most; unfinished `async` hooks are cancelled at session end; whether a `setsid` process survives is not documented |
| `SessionStart` sweep of sessions left open | `SessionStart` with `transcript_path` (common input field) |
| Transcript (Claude JSONL) read by `capture/extract.py` | `transcript_path` to a rollout JSONL (`session_meta`, `response_item`, `event_msg`, `turn_context`); the docs call its format "not a stable interface" |
| `PreCompact` handoff text on stdout | plain stdout ignored; JSON fields `continue`, `stopReason`, `systemMessage` only, none reaches the model |
| `PostCompact` `compact-log` (checks the handoff in `compact_summary`) | `PostCompact` exists; no handoff to check |
| Plugin options (`CLAUDE_PLUGIN_OPTION_*`) | none |
| Plugin agents (`agents/*.md`) | roles only in `~/.codex/agents/` or `.codex/agents/` (TOML); plugins cannot ship them |

## Decision

- **Capture on Codex**: the Codex hooks run `session-end.sh` (`SessionEnd`, timeout 3 s), `pre-compact.sh` (`PreCompact`, capture only) and the sweep in `session-index.sh`, all with `MEM_HOST=codex`. The engine reads Codex rollouts through a second decoder chosen by the file's first line (`session_meta`), behind the same `extract()`; an unknown shape is counted as skipped lines, never an error. The capture pass stays on Claude (`claude -p`, ADR 0037): without a `claude` binary capture skips, as today.
- **The sweep is the safety net**: if Codex kills the detached process at session end, or never fires `SessionEnd` (the VS Code extension keeps threads open), a later `SessionStart` sweep captures the session once it has been idle 6 h. On Codex the sweep reads the day folders of the last 7 days (Codex mixes all projects in one folder per day), keeps rollouts of the starting folder's project and of owner threads (`thread_source` `user`, never subagent threads) before counting them, and the history commit is idempotent and runs at the next session end.
- **Plugin options on Codex** come from one file per option under `~/.config/agent-memory/` (as `store` and `runner` already do), named as the Claude option (every `userConfig` key; a test keeps the list equal to `plugin.json`); a hook helper exports each as its `CLAUDE_PLUGIN_OPTION_*` variable when that variable is unset, so the scripts and the engine below stay unchanged. Claude keeps its plugin options; a file never overrides one. The `auto_settle` trigger after a write in a shell command stays Claude-only: Codex gives shell commands no hook-exported variables.
- **Agents on Codex**: `scripts/port.py` generates the memory plugin's agents as TOML roles (`ports/codex/memory/agents/`), tools limited by rules in their instructions, models by tier; the owner copies them to `~/.codex/agents/` as for `agent-skills`.
- **Not ported**: the compaction handoff and `compact-log`, because nothing a Codex compaction hook prints reaches the model.

## Alternatives

| Option | Rejected because |
|---|---|
| Codex capture runs on `codex exec` | capture is Claude-only in ADR 0037 (its pass reads transcripts with tools a Codex session cannot be denied) |
| One `options` file with `key=value` lines | the config folder already uses one file per setting (`store`, `runner`); two conventions in one folder |
| Engine reads options itself on Codex | every script and pass would gain a second lookup; exporting the variables keeps one path |
| A `mem install-agents` command | YAGNI: `agent-skills` already documents a copy step; revisit when Codex lets plugins ship roles |

## Consequences

- Codex sessions leave memories and store history like Claude ones, on machines with `claude` installed.
- A second transcript decoder to keep, against a format Codex calls unstable; its tests use a synthetic rollout built from the observed schema.
- Changing `hooks/codex.json` changes its trust hash: after the update the owner re-trusts the hooks (`codex --no-daemon` → `/hooks`).

## Revisit if

- Codex documents a context field for compaction hooks (port the handoff), or lets plugins ship agent roles.
- The probe shows a detached process never survives `SessionEnd` and `SessionStart` lacks `transcript_path` (capture would have no path).
- A Codex release changes the rollout format so the decoder skips most lines.
