# 0010 Cheap offload workers and an explicit offload policy

Status: accepted · Date: 2026-10-28 · Amends 0007 · Amended by 0017, 0018, 0019

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

## Review 2026-11-15

The "Revisit if" trigger about cost had not been checked since the decision. Token counts from the owner's 62 sessions (2026-10-27 to 2026-11-15, main conversations and their subagents): subagents produced 75% of the output tokens (Sonnet 48%, Haiku 20%, Opus subagents 7%) and the main conversation 25%. This is a share of tokens, not a cost: no price was applied, and it does not show what the main model would have spent alone.

ADR 0019 puts `implementer` inside the Superpowers plan loop as its implementer.

## Review 2026-11-18

The checks row of `user-config/offload-policy.md` is narrowed, at the owner's request, from "another long read-only command" to a command "that you expect to take over a minute or to print more than a screen of output", and "Keep inline" gains "a short check with its output cut". Reason, from [docs/studies/2026-11-18-weekly-usage.md](../studies/2026-11-18-weekly-usage.md): in one week the main sessions ran 453 checks inline against 51 `check-runner` calls; 94% of the inline ones already cut their output (median result 394 characters), while one `check-runner` call took about 35k weighted Haiku tokens. The old row asked for a dispatch that costs more than the lines it keeps out.

The case `offload-check-runner-with-policy` changed with the row: its suite now takes over a minute (a 65-second module fixture) and the prompt says so, because the old two-test suite is what the new row keeps inline. Its earlier results are not comparable.

Sonnet main, 2 runs per case, `--case 'offload-*-with-policy'`, $1.40:

| Case | Last record | 2026-11-18 |
|---|---|---|
| `offload-check-runner-with-policy` (changed case) | 2/3, rerun 6/6 (ADR 0017) | 2/2 dispatched, nothing run inline, right answer |
| `offload-summarizer-with-policy` · `-extract-` | 3/3 · 3/3 | 2/2 · 2/2 |
| `offload-skeptical-reviewer-with-policy` | 2/6 | 2/2 |
| `offload-ui-verifier-with-policy` | 2/3 (judge), rerun 6/6 | dispatched 2/2; one run lost two judge graders on the worker's report (score 0.83) |
| `offload-implementer-with-policy` | 0.17 | 0.17 (no dispatch, as before; the owner sees it fire in real use) |

No case fell below its record on dispatch, so no 6-run comparison was made. The `ui-verifier` judge misses concern the content of that worker's report, which this change does not touch.

Not measured: that a short check now stays inline (no case covers it; it is what the transcripts already show).

Revisit if the next usage study shows checks over a minute or with long output run inline more often than in this window (49 of 453 ran over 60 s; 18 results exceeded 4,000 characters).
