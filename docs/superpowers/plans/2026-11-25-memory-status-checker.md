# Memory plugin: `memory-status-checker` subagent

Status: done · merged in #187, 2026-11-25

Released in memory 0.13.0 (triggers reworded in 0.14.0, ADR 0030 Review 2026-11-25), unmeasured until its trigger cases run · Branch `feat/memory-status-checker` (merged) · Owner request 2026-11-25, design chosen by the model, owner reviews afterwards.

## Goal

At a session start or after a long continuation, the main model dispatches one cheap read-only subagent instead of reading backlog, plans, ADRs and memories itself. The subagent returns a fixed status card with references, then stays addressable (`SendMessage`) to answer follow-up questions from what it already read. Aim: fewer tokens persisting in the main context, same or better grasp of the current state.

## Decisions

| Decision | Reason |
|---|---|
| New agent, not a mode of `memory-researcher` | The researcher writes (its `mem-research` step records web findings); a status checker must be read-only. A second mode would also change a measured description |
| In the `memory` plugin | It depends on `mem` (state memories, project syntheses); the memory plugin has no ports (ADR 0023) |
| Haiku, `effort: medium` | Reading, cross-checking and citing with a fixed format; `low` stops early (prompt-engineering models.md). Priorities are read from the project, never invented |
| Reports stale memories under Drift, runs no fix | A Haiku writing unsupervised to a shared store propagates errors to every later session; `memory-curator` and the owner apply |
| Core value: drift | Cross written state (backlog, plan state sections, `state` memories, project syntheses) against `git log` since it was written |
| Offload table per plugin, pasted into the user-level CLAUDE.md like agent-skills' (owner, 2026-11-25: same mechanism for both plugins); the status checker's row leaves the moment to the model | Session start text is measured and owner-shortened; a nudge from `SessionStart`/`PostCompact` is proposed for later, after the agent proves useful |

## Tasks

- [x] 1 Agent file `plugins/memory/agents/memory-status-checker.md` — check: frontmatter like the other four, read-only tools, report format with a length bound
- [x] 2 `hooks/subagent-start.sh` skips `memory-status-checker` (and `memory-synthesizer`, which the README already says is skipped) — check: memory tests pass
- [x] 3 README Subagents row and count, CHANGELOG `[Unreleased]` line — check: `python3 scripts/validate.py`
- [x] 4 Trigger eval case `plugins/memory/evals/trigger/memory-status-checker` (written, not run: evals cost usage; owner decides) — check: case parses in validate
- [x] 5 ADR 0030 with kill criteria (unmeasured prompt) — check: Status line format
- [x] 6 Checks and reviews: validate.py, `claude plugin validate .`, memory tests; `skeptical-reviewer` and `prompt-engineer` on the agent file

- [x] 7 `plugins/memory/user-config/offload-policy.md` with a `validate.py` row check (a hook delivery was built and removed: owner chose the paste for both plugins) — check: validate, negative checks for a missing and an extra row
- [x] 8 Paste the table into the owner's `~/.claude/CLAUDE.md` below the agent-skills offload block (owner asked), with a backup

## Kill criteria (also in ADR 0030)

- On 5 resumed sessions, the main model still reads the files the card cites in full, or the card misses a drift a human check finds → remove or rework.
- Card claims wrong at a cited reference in more than 1 of 10 items → raise to Sonnet or remove.
