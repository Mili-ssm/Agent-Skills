# 0036 The memory plugin reaches Codex from its own folder, core features only

Status: proposed · Date: 2026-11-27 · Amends 0023

## Context

ADR 0023 left Codex out of the memory plugin's first version and named "the owner wants the memory in … Codex" as a revisit trigger. On 2026-11-27 the owner asked to start the port, chose design and record now with code after the stage 4 kill read (due 2026-12-01), and chose the core scope: `mem`, the `memory` skill, the session and subagent index, configuration by file. The owner runs Codex from its VS Code extension and already installs `agent-skills@mili-ssm` from this marketplace there.

Probes the same day with the extension's `codex-cli 0.171.0-alpha.13.2` settled what the docs left open ([plan](../superpowers/plans/2026-11-27-memory-codex-port.md#evidence-probes-of-2026-11-27)): trusted plugin hooks run in the CLI and their `SessionStart` output reaches the model; the plugin's `bin/` is not on the model's `PATH`; a `hooks` field in `.codex-plugin/plugin.json` replaces the default `hooks/hooks.json`.

## Decision

- The Codex plugin is `plugins/memory/` itself, with a `.codex-plugin/plugin.json` whose `hooks` field names `hooks/codex.json`; `scripts/port.py` adds its marketplace entry. No generated copy, unlike `agent-skills` (ADR 0015), because the engine is tool-neutral and the manifest keeps Claude's hooks out.
- The core runs two hooks, `SessionStart` (the index) and `SubagentStart` (the three lines), and their texts give `mem` by absolute path and leave out Claude-only names.
- Codex has no plugin options: the store comes from `mem`'s config file or the default store, so both tools on one machine share one memory.
- Background passes, agents, the compaction handoff and session-end capture stay out until each is decided on its own.

## Alternatives

| Option | Rejected because |
|---|---|
| A generated copy under `ports/codex/memory` (as `agent-skills`) | duplicates the engine on every change for no gain: the probe showed the manifest can select its own hooks file |
| One `hooks/hooks.json` shared by both tools | Codex would run the Claude-only hooks (`PreCompact`, `PostCompact`, `SessionEnd` with `claude -p`) |
| A hook that writes a `mem` shim into `~/.local/bin` | writes outside the plugin on every session start; a path in the session text has no side effect. Revisit if the model fails to use the path |
| Full parity in the first version (`codex exec` passes, TOML agents) | the owner chose the core: smaller cost and risk, and the kill read may still end the plugin |
| Wait for the kill read before designing | the design is cheap and reversible; only code waits |

## Consequences

- One folder serves two tools: a Claude-only change to a shared hook script can break Codex; the plan's checks run both.
- The owner trusts the hooks once per plugin version in Codex.
- `validate.py` and `port.py` gain a memory marketplace entry; ADR 0023's "no port" consequence no longer holds for Codex.
- Ships unmeasured; kill criteria are in the plan.

## Revisit if

- The kill read ends the plugin (this record is then withdrawn).
- Codex documents plugin options, plugin-shipped agents or `bin/` on `PATH`.
- A Codex release stops running trusted plugin hooks in the CLI or the extension.
