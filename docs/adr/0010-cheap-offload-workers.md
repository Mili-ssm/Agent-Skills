# 0010 Cheap offload workers and an explicit offload policy

Status: accepted · Date: 2026-10-28 · Amends 0007

## Context

The owner saw little delegation to cheaper models. Verified in Claude Code docs: the built-in `Explore` runs on the main conversation's model; subagents without a `model` (general-purpose, Superpowers implementers) inherit it; `CLAUDE_CODE_SUBAGENT_MODEL` sets their default; a user- or project-scope agent named `Explore` overrides the built-in. The plugin only had specialists (4 Opus, 4 Sonnet) plus one Haiku researcher.

Delegation evals (Sonnet main, 3 runs, scaffolded project): with worker descriptions alone, `check-runner` fired 0/3 and `summarizer` 2/3; with a short offload policy in the system prompt (as the owner's CLAUDE.md), both fired 3/3.

## Decision

- Workers: `check-runner` (Haiku), `summarizer` (Haiku), `implementer` (Sonnet), `fixer` (Sonnet), plus `user-agents/Explore.md` (Haiku) installed at user scope by `cloud-setup.sh`.
- Workers say "Use proactively … instead of doing it yourself, because …" — an exception to ADR 0007's no-proactive rule, limited to cheap workers.
- `cloud-setup.sh` sets `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`.
- `consistency-auditor` moves Opus → Sonnet; Opus stays for architect, security-reviewer, pre-mortem.
- Every agent declares `effort`; read-only agents set `omitClaudeMd: true`; writers keep CLAUDE.md for project conventions; workers set `maxTurns`.
- Workflow skills name the worker for their reading and verification steps; `/agent-skills:offload` forces delegation.
- The owner's CLAUDE.md carries the offload trigger table: it is the lever the evals showed to work.

## Alternatives

| Option | Rejected because |
|---|---|
| Rely on descriptions only | 0/3 for check-runner in evals |
| `CLAUDE_CODE_SUBAGENT_MODEL=haiku` | Implementers would write code on Haiku |
| Explore override inside the plugin | Plugin agents are namespaced and do not override the built-in |

## Consequences

Cost shifts to Haiku/Sonnet for reading, checks and bounded implementation; the main model reviews worker output, so briefs must be self-contained.

## Revisit if

`/cost` shows no saving after a week of use, or worker output needs frequent rework.

## Review 2026-10-28

Regression after adding the workers (Sonnet, 2 runs): 15/17 trigger cases clean, no false triggers; `pre-mortem` auto-delegation dropped to 2/6 runs (was 3/3) as the agent catalog grew. Mitigation: explicit `/agent-skills:premortem` and a "before executing a plan → pre-mortem" row in the owner's CLAUDE.md offload table.

## Review 2026-10-30

`implementer` goes from `maxTurns: 40` to 60, because the owner sees its runs end half done, and the soft stop added earlier today (~32 rounds, ADR 0007 Review 2026-10-30) left less room than the old cap alone. Its prompt now has a conditional checkpoint at ~24 rounds (stop with `BLOCKED — checkpoint` only when less than half of the acceptance criteria is met or the brief no longer fits the code) and the soft stop at ~48 rounds. A subagent cannot report to the main conversation mid-run, so every checkpoint ends the run: reporting at every checkpoint would cost the main conversation a turn per run, while the conditional one costs it only when the task is off track or too large. Measured: `offload-implementer-with-policy`, Opus main, 2 runs: delegated, brief complete and implemented 2/2, about $0.54. Revisit if runs still end with `BLOCKED — turn budget`: the task is then too large for one brief, not the cap too low.
