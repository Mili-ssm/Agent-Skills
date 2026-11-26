# 0032 Offload tables load from a session start hook

Status: accepted · Date: 2026-11-26 · Amends 0021, 0012

## Context

ADR 0012 keeps one copy of the offload table; ADR 0021 makes `user-config/` the source the owner pastes into the user-level `CLAUDE.md`. Every Claude Code user of `agent-skills` or `memory` therefore pastes and re-pastes the tables by hand, and a stale copy goes unnoticed. The owner asked to plan a hook (backlog 4d, 2026-11-25) and to build it with a switch (2026-11-26). The case rests on upkeep: the usage study of 2026-11-23 put the cost gain at about 7 USD a week.

Facts (probe of 2026-11-26, throwaway plugin, Sonnet, plan `docs/superpowers/plans/2026-11-26-offload-policy-hook.md`):

- Hook output reached the model in 4 of 4 eval runs, as plain output and as `additionalContext`; the hooks run once per eval session, source `startup`.
- A dispatched subagent did not report the hook text in 4 of 4 runs (weak: the grader also fails when no subagent ran).
- An option nobody touched leaves `CLAUDE_PLUGIN_OPTION_<KEY>` unset. A case variable reaches the hook only under `execution.env`.
- An eval session carries `CLAUDE_CODE_EVAL_CONFINED`; it is not documented.
- Plain hook output is capped at 10,000 characters. Tables: `agent-skills` 2,806, `memory` 2,095, routing 8,626.

## Decision

| Item | Decision |
|---|---|
| What ships | `agent-skills` option `offload_policy` and `memory` option `offload_table`, both boolean, on by default. Each plugin's `SessionStart` hook prints its table (matcher `startup\|clear\|compact`). The table text keeps its single source; `scripts/port.py` generates the copy `agent-skills` needs inside its plugin folder (`plugins/agent-skills/hooks/offload-policy.md`) |
| Silent when | the option is exactly `false`; `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/CLAUDE.md` holds the table's heading as an exact line (the migration step for everyone who pasted it); inside `claude plugin eval` unless the case sets `execution.env: {EVAL_OFFLOAD_HOOK: "on"}` |
| Turning it off | `/plugin configure agent-skills@mili-ssm` and `/plugin configure memory@mili-ssm`; or keep the pasted table, which the hook detects |
| Routing | `user-config/routing.md` stays pasted: 8,626 characters against the 10,000 cap, and no eval covers it |
| Copilot and Codex | users keep pasting both files: the ports have no hook parity (`docs/platform-parity.md`) |
| Cloud | `scripts/cloud-setup.sh` sets `offload_policy: false` for `agent-skills@mili-ssm` unless `AGENT_SKILLS_OFFLOAD_HOOK=1`, because the owner's cloud account instructions already carry the table and a hook cannot see them |
| Evals | six `offload-*-with-hook` cases (the table from the hook, no `append_system_prompt`) twin the `-with-policy` cases. The hook is silent in every other eval, so no recorded trigger or `neg-*` result changes arm |
| Canary | before a policy measurement, run `offload-summarizer` (bare, table absent) and `offload-summarizer-with-hook` (table present) with a scratch grader, because the eval marker is undocumented |

The text of both tables does not change; this ADR changes how they arrive. ADR 0021's single source stands; its "the owner pastes" step becomes optional for Claude Code. ADR 0012's one copy stands, plus one generated copy.

## Alternatives

| Option | Rejected because |
|---|---|
| Option only, no skip check | Every current user loads the table twice until they read the changelog |
| Off by default | Safe for current users, no gain for new ones |
| All sources in the matcher | A resumed session keeps its transcript, which already holds the text |
| An opt-out line in every eval case | 32 of 42 cases are prompt-only and cannot set a variable; it would also need `validate.py` changes |
| Parse imports and every instruction file in the hook | Each double load costs about 700 tokens; the option is the remedy |
| Routing in the same hook | Too close to the 10,000-character cap, and unmeasured |

## Consequences

- New Claude Code users paste only the routing text; current users who pasted the table see no change.
- Blind spots of the skip check: a table that arrives through an `@import`, a project `CLAUDE.md`, `CLAUDE.local.md`, account instructions, or a file with CRLF line ends is not seen, so it loads twice (about 700 and 520 tokens) until the option is turned off. A stale pasted copy wins over the plugin's until the user deletes it.
- A cloud snapshot older than the release keeps the old setup script for up to about 7 days: two copies until it reruns. Accepted.
- Hook output is added again after `/clear` and after a compaction; whether it survives a compaction is not documented.
- The `memory` trial harnesses run with the user's real home, so on a machine without the pasted table they now gain it.
- A hook that fails would disturb every session: both scripts exit 0 whatever happens, and tests pin the output byte for byte.

## Revisit if

| Kill criterion | Action |
|---|---|
| A `-with-hook` case scores 2 or more of 6 below its twin | Default `false` for that plugin; the hook stays opt-in |
| The canary shows the table in a bare case (the eval marker was dropped or renamed) | Every recorded result since the last passing canary is suspect: rerun them, re-plan the switch |
| Real sessions show the table twice (the skip check misses a common delivery path) | Widen the check, or default `false` |
| `memory` delegation does not improve with the hook on, or `memory-*` subagents are not dispatched (no eval covers its table's delivery) | Measure it, or revert the `memory` hook |
| Routing grows or shrinks so that it fits under the cap with margin and an eval covers it | Reconsider a routing hook |
| A Claude Code release documents or changes hook output handling or the eval marker | Re-run the probe and the canary |

## Measurement 2026-11-26

Sonnet main model, `--runs 2`, `--scaffold --allow-tools Bash Edit Write`, both arms the same day on the same commit; runs passed. Cost 1.45 USD (`-with-policy`) and 1.57 USD (`-with-hook`). Canary (with `--scaffold`): table absent by default 2 of 2, present with the switch 2 of 2.

| Case | `-with-policy` (table in `append_system_prompt`) | `-with-hook` (table from the hook) |
|---|---|---|
| `offload-check-runner` | 2/2 | 2/2 |
| `offload-skeptical-reviewer` | 2/2 | 2/2 |
| `offload-summarizer` | 2/2 | 2/2 |
| `offload-summarizer-extract` | 2/2 | 2/2 |
| `offload-implementer` | 0/2 (`delegated` 0/2) | 0/2 (`delegated` 1/2) |
| `offload-ui-verifier` | 0/2 (`delegated` 2/2, `inline` 2/2) | 0/2 (`delegated` 2/2, `inline` 2/2) |

- No hook case scored below its twin, so no 6-run rerun, and the default stays on.
- `implementer` at 0/2 matches its record (ADR 0017 `## Measurement 2026-11-26`).
- `ui-verifier` fails on its two browser graders in both arms because no browser launches in the eval sandbox (backlog 3g, set aside by the owner on 2026-11-26); it is dispatched in every run.
- Unmeasured: the `memory` hook, the skip check, and the undocumented eval marker; each has a kill criterion above.
