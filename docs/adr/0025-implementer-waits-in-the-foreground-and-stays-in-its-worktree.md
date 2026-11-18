# 0025 The implementer waits in the foreground and stays in its worktree

Status: accepted · Date: 2026-11-18

## Context

The weekly usage study ([docs/studies/2026-11-18-weekly-usage.md](../studies/2026-11-18-weekly-usage.md), 271 `implementer` runs in 7 days) counted these failed tool calls (the cause column comes from four sampled commands per error, so rule 2 below rests on a sampled cause):

| Error | In `implementer` | Sampled cause |
|---|---|---|
| `Blocked: sleep N followed by …` | 34 | a command started in the background, then `sleep` plus a read of its output file |
| `No such tool available: Monitor` | 10 | waiting on a background command with a tool the agent does not have |
| `This agent is isolated in the worktree` | 17 | an absolute path of the main checkout, or of the session scratchpad, used from an isolated worktree |

`implementer.md` had no line on how to wait for a long command or on paths under worktree isolation.

## Decision

Two rules in the body of `plugins/agent-skills/agents/implementer.md`, each with its reason:

1. A long command runs in the foreground with the Bash `timeout` set to its expected duration (at most 10 minutes); a command that cannot finish in that time is reported for the caller to run.
2. In an isolated worktree, paths are relative to the working directory, and a path the brief gives inside the main checkout maps to the same file under it; a file that exists only outside it is opened with Read, and when a command itself needs it, it is missing input, reported instead of retried.

The `description` is unchanged, so no eval case moves; the change ships **unmeasured** (requirement N6 in [requirements.md](../requirements.md)).

## Alternatives

| Alternative | Why not |
|---|---|
| Give `implementer` the `Monitor` tool | Widens its tool list for a case the foreground timeout covers; `port.py` would need a mapping for each port |
| Put the worktree rule in the caller's brief guidance (`user-config/offload-policy.md`) | That file is a measured surface (N6); the worker-side rule covers the same failures at no eval cost. Revisit if the refusals persist |
| A rule on the lower-case `bash` tool name (19 errors) | The error text already names the fix and costs one turn; a line for it would be read on every run |

## Consequences

- Two more lines are read on every `implementer` run (an estimated 150 tokens, not measured).
- A command over 10 minutes now ends in a report instead of a polling loop; the caller runs it through `check-runner` or itself.
- The shell errors of the same study (230 zsh errors across agents) are not covered here: they are an environment matter (study suggestion G1).

## Revisit if

Kill criterion, read from the next usage study (`docs/studies/scripts/usage_errors.py`, a window of at least 100 `implementer` runs after this ships). The unit is failed tool calls per 100 runs, not runs that hit one:

| Rule | Before (271 runs) | Revert if still above |
|---|---|---|
| 1 | 34 `Blocked: sleep` + 10 `Monitor` = 44, or 16 per 100 runs | 8 per 100 runs |
| 2 | 17 worktree refusals, or 6 per 100 runs | 3 per 100 runs |

Over-stopping (a `BLOCKED` report where the run used to finish) has no baseline: the script's count of `BLOCKED` in the results returned to the main session was 0 in this window, and it does not tell agents apart. Revisit both rules if the owner or a plan-loop ledger shows `implementer` runs stopping for a long command or an outside file that the caller then ran without trouble.
