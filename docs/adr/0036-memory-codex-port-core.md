# 0036 The memory plugin reaches Codex from its own folder, core features only

Status: accepted · Date: 2026-11-27 · Amends 0023

## Context

ADR 0023 left Codex out of the memory plugin's first version and named "the owner wants the memory in … Codex" as a revisit trigger. On 2026-11-27 the owner asked to start the port, chose design and record now with code after the stage 4 kill read (due 2026-12-01), and chose the core scope: `mem`, the `memory` skill, the session and subagent index, configuration by file. The owner runs Codex from its VS Code extension and already installs `agent-skills@mili-ssm` from this marketplace there.

Probes the same day with the extension's `codex-cli 0.171.0-alpha.13.2` settled what the docs left open ([plan](../superpowers/plans/2026-11-27-memory-codex-port.md#evidence-probes-of-2026-11-27)): trusted plugin hooks run in the CLI and their `SessionStart` output reaches the model; the plugin's `bin/` is not on the model's `PATH`; a `hooks` field in `.codex-plugin/plugin.json` replaces the default `hooks/hooks.json`.

## Decision

- The Codex plugin is `plugins/memory/` itself, with a `.codex-plugin/plugin.json` whose `hooks` field names `hooks/codex.json`; `scripts/port.py` adds its marketplace entry. No generated copy, unlike `agent-skills` (ADR 0015), because the engine is tool-neutral and the manifest keeps Claude's hooks out.
- The core runs two hooks, `SessionStart` (the index) and `SubagentStart` (the three lines), whose texts leave out Claude-only names.
- `mem` becomes a user command (owner, 2026-11-27: models call `mem`, not `uv` or a full path): `mem install-command`, run once, puts a launcher in `~/.local/bin` that runs `bin/mem` of the plugin copy the last session used; every `SessionStart` hook (Claude or Codex) records its plugin root in the plugin's state folder, so the command follows the copy the last session ran rather than a version fixed at install. Until it is installed, the session text gives the absolute path.
- Codex has no plugin options: the store comes from `mem`'s config file or the default store, so both tools on one machine share one memory.
- Background passes, agents, the compaction handoff and session-end capture stay out until each is decided on its own.

## Alternatives

| Option | Rejected because |
|---|---|
| A generated copy under `ports/codex/memory` (as `agent-skills`) | duplicates the engine on every change for no gain: the probe showed the manifest can select its own hooks file |
| One `hooks/hooks.json` shared by both tools | Codex would run the Claude-only hooks (`PreCompact`, `PostCompact`, `SessionEnd` with `claude -p`) |
| A hook that writes a `mem` shim into `~/.local/bin` on every start | writes outside the plugin each session; the one-time launcher reads a recorded plugin root instead |
| The absolute path in the session text as the only route | works only where the session text reached the model; the owner wants one command for every tool and the terminal |
| A packaged engine (`uv tool install`), no `uv` at run time | a second environment that drifts from the plugin version, against ADR 0035's single environment; it is one of the fixes plan task 1 weighs if the Codex sandbox blocks `uv` |
| Full parity in the first version (`codex exec` passes, TOML agents) | the owner chose the core: smaller cost and risk, and the kill read may still end the plugin |
| Wait for the kill read before designing | the design is cheap and reversible; only code waits |

## Consequences

- One folder serves two tools: a Claude-only change to a shared hook script can break Codex; the plan's checks run both.
- The owner trusts the hooks once per plugin version in Codex.
- `mem` works the same in Claude sessions, subagents, Codex and the owner's terminal once installed; the launcher is one more file outside the plugin, removed by `mem install-command --remove`.
- `validate.py` and `port.py` gain a memory marketplace entry; ADR 0023's "no port" consequence no longer holds for Codex.
- Ships unmeasured; kill criteria are in the plan.

## Revisit if

- The kill read ends the plugin (this record is then withdrawn).
- The Codex sandbox blocks `uv` when the model runs `mem` and plan task 1 picks the packaged engine.
- Codex documents plugin options, plugin-shipped agents or `bin/` on `PATH`.
- A Codex release stops running trusted plugin hooks in the CLI or the extension.

## Review 2026-11-27

Released in memory 0.17.0 the same day. The owner's trial in the VS Code extension: the model used `mem` (through the user command and the adapted `~/.codex/AGENTS.md`), but the session rollout held no memory index: the extension never showed the hook trust prompt and skipped both hooks silently. The CLI's `/hooks` screen (bundled binary run with `--no-daemon`) listed the two hooks from `memory@mili-ssm` as new; trusting them wrote `trusted_hash` entries under `[hooks.state]` in `~/.codex/config.toml`, and the next `codex exec` without any bypass flag logged a `host: codex` index run. The README now gives this step. Kill criterion "trusting the hooks fails in the VS Code extension" did not fire: trust is shared through `config.toml`, only the prompt is missing.
