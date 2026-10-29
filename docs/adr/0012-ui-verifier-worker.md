# 0012 UI verification worker, worker commands through offload

Status: accepted · Date: 2026-10-29

## Context

The owner's working agreement requires every web UI change to be verified in a real browser: affected flows, console, desktop and mobile, keyboard and focus, error recovery. That work ran in the main conversation, where screenshots, DOM snapshots and console output fill the most expensive context, or went to `ux-reviewer`, which audits usability and accessibility with Nielsen severities and preloads the whole `ux-principles` skill, most of which a pass/fail check does not use.

A prompt and configuration review of the plugin (2026-10-29) also found that four workers had no command although N8 asked one per agent, and that the owner's offload table, the lever ADR 0010 measured, existed only as escaped strings inside two eval cases.

## Decision

- New worker `ui-verifier` (Sonnet, read-only, `maxTurns`, `omitClaudeMd: true`, no preload). It drives a web UI through the flows and acceptance criteria in its brief at desktop and mobile widths, with whichever Playwright driver is installed (Python, Node or `playwright-cli`), checks console errors and failed requests, and returns pass/fail per check with evidence. Keyboard and error-recovery checks are advisory unless the brief lists them.
- When it starts the app itself, it starts it, runs every flow and stops it in one Bash call, because sandboxed shells may not keep background processes or share the network between calls. It drives only localhost or the brief's URL.
- The "Use proactively" exception of ADR 0010 covers the cheap workers `scripts/validate.py` names, now including `ui-verifier`.
- N8 changes: every specialist agent and the UX design workflow keep a user-only command; workers are forced with `/agent-skills:offload`, which lists each one.
- `ux-principles` names `ui-verifier` for its verification step, as ADR 0010 asks of workflow skills.
- `user-config/offload-policy.md` is the single copy of the offload table. The owner's CLAUDE.md, `cloud-setup.sh` (opt-in) and the eval cases use it verbatim, and `validate.py` checks the cases. This adds `user-config/` to the root layout of ADR 0011: files the owner copies into user scope that are not agents.

## Alternatives

| Option | Rejected because |
|---|---|
| A `verify` mode in `ux-reviewer` | Its preload and Nielsen-severity output do not fit pass/fail checks, and one agent with two contracts blurs both descriptions |
| Playwright MCP tools in the allowlist | Plugin MCP tool names depend on the install (`mcp__plugin_<plugin>_<server>__*`); Bash reaches every driver the owner uses |
| Verification stays in the main conversation | Browser output is the largest context sink the agreement names |
| One command per worker | Five near-identical commands duplicate `/agent-skills:offload` |

## Consequences

- Browser verification runs on Sonnet; the main model reads a bounded report.
- One more agent competes for delegation: ADR 0010 saw `pre-mortem` drop as the catalog grew. The evals below measure it.
- Owners add the `ui-verifier` row to their own offload table.

## Revisit if

`ui-verifier` reports false failures or "not verified" on most runs, or trigger evals show `ux-principles`, `ux-reviewer` or `pre-mortem` losing dispatches to it.
