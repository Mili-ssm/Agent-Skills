# 0011 One marketplace, independent plugins: agent-skills plus opt-in mods

Status: accepted · Date: 2026-10-28

## Context

The owner wants Claude Code mods (plugins whose hooks module changes Claude's own interface: panes, status line) in this repo, installable independently of `agent-skills` so nothing pollutes another install. A repo with `.claude-plugin/marketplace.json` is a marketplace: each entry is a plugin installed on its own. With `agent-skills` at `source: "./"`, its installed copy would carry every mod's folder too (not loaded, but mixed in).

## Decision

- Each plugin lives in `plugins/<name>/` with its own `.claude-plugin/plugin.json`; the root keeps only the marketplace, `docs/`, `scripts/` and `user-agents/`.
- `agent-skills` moves to `plugins/agent-skills/` (skills, agents, commands, evals); `scripts/validate.py` reads it there.
- First mods: `agents-pane` (side pane: subagents with type, model, status, duration and a per-model tally) and `status-model` (status line: main model, running subagents, last subagent with model and outcome). Both make offloading to Haiku/Sonnet visible (ADR 0010).
- No `version` in any `plugin.json` (ADR 0006): each commit updates every plugin.
- Mods are opt-in: `cloud-setup.sh` installs them only when `AGENT_SKILLS_MODS` lists them.
- Each mod ships `claude plugin test` tests; `claude plugin validate` and `tsc` gate changes.

## Alternatives

| Option | Rejected because |
|---|---|
| Keep `agent-skills` at the repo root | Its install copy would include the mods' folders |
| Mods in a separate repo | Owner wants one repo; a second marketplace to add and update |
| One mod with pane + status line | The owner may want only one; each stays installable alone |

## Consequences

Install commands are unchanged (`--marketplace Mili-ssm/Agent-Skills`). The mod hooks API is early access and may change between Claude Code releases: a failing hook is skipped, never blocks a session.

## Revisit if

The hooks API changes shape, or a mod needs data another plugin provides (then use `dependencies`).
