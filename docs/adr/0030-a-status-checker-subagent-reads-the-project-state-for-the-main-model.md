# 0030 A status-checker subagent reads the project state for the main model

Status: accepted · Date: 2026-11-25 · Reviewed 2026-11-25

## Context

At a session start or after a compaction the main model reads backlog, plans, decision records and memories to learn where the work stands. Those tokens stay in its context for the whole session and are re-read from cache on every turn. The owner asked (2026-11-25) for a cheaper agent to do that reading and hand back a schematic status plus short answers to follow-up questions; the owner left the choice between a new agent and a mode of `memory-researcher` to the model and reviews it afterwards.

## Decision

A new read-only subagent, `memory:memory-status-checker` (Haiku, `effort: medium`), in the memory plugin. It reads git, the open-work and plan documents, `mem memories --kind state` and project syntheses; marks written state that git shows to be stale; returns a fixed card with a date and a source on every line; reports stale memories without changing them; reads plans by their status ranges only, on a fixed budget; and answers follow-up questions through `SendMessage` from what it already read. Priorities come only from what the project wrote. The `SubagentStart` hook skips it like the plugin's other agents.

The main model learns when to use it, and the four other memory subagents, from the plugin's offload table, `plugins/memory/user-config/offload-policy.md`: one row per agent (situation, call, what it does and returns), which the owner pastes into the user-level CLAUDE.md right below the agent-skills offload block. Both plugins deliver their tables the same way (owner, 2026-11-25: one mechanism for both; a paste, because it is the measured one, ADR 0010, and survives compaction). When to dispatch the status checker is the model's judgment, not a fixed moment (owner, same day). `validate.py` fails when an agent has no row or a row names no agent.

## Alternatives

| Alternative | Why not |
|---|---|
| Deliver the offload table with a `SessionStart` hook (built, then removed the same day) | Unmeasured, may be lost after a compaction, and the two plugins would deliver their tables differently unless agent-skills changed too (ADR 0021, ports) |
| A status mode of `memory-researcher` | The researcher writes (its `mem-research` step records web findings); a status reader must not. A second mode would change a description with recorded trigger results |
| A hook that injects the status on every prompt | Adds latency to every message, cannot see the conversation, and lowering printed tokens did not lower total tokens in earlier measurements (memory notes on answer cards and lookup output) |
| Let it correct memories | A Haiku writing unsupervised to a shared store spreads errors to every later session; `memory-curator` and the owner apply fixes |
| Sonnet at low effort | The task is reading and cross-checking with a fixed format; the judgment parts (ranking, correcting) are removed. Revisit on the kill criterion below |

## Consequences

- One more description in every session's agent listing (about 100 tokens).
- A dispatch costs the main context about 2.5–3k tokens however short the card (global memory `m:in-claude-code-one-subagent-dispatch-costs-the`, measured over 1,075 dispatches): the agent pays off only when the main model would otherwise read more than that plus the card. In this repository listing the state memories alone prints 12.9k characters (20 records, 2026-11-25).
- Read-only is enforced for files (`disallowedTools`) but only stated in the prompt for `mem` and git, which run through Bash, as for the plugin's other agents. The prompt names the allowed command forms.
- The table costs about 500 tokens (2,026 characters) in every session once pasted. A user without it still gets the agents through their descriptions alone, which delegated less for agent-skills (ADR 0010).
- A pasted copy goes stale until the user pastes again, as for agent-skills (ADR 0021); the marker names the commit it came from.
- Unmeasured. CLAUDE.md N6 asks for a measured description before merging to `dev`: the owner rules whether to run it. The trigger case `plugins/memory/evals/trigger/memory-status-checker` is written and not run (evals cost usage; the owner decides when).

## Revisit if

- In 5 resumed sessions the main model still reads in full the files the card cites, or the card misses drift that a check by hand finds: rework or remove it.
- More than 1 in 10 card lines is wrong at its cited source: move it to Sonnet or remove it.
- Read 5 sessions with the table pasted: the main model ignores it (no memory dispatch where a row applied) or over-delegates (dispatches for a single `mem search`): reword the rows.
- The trigger case fires in fewer than 2 of 2 runs, or a `neg-*` case starts firing it: reword the description.

## Review 2026-11-25

The owner reported the agent is not dispatched on its own. A `prompt-engineer` audit named three causes; the owner accepted these changes, all unmeasured until the trigger cases run (planned 2026-11-26):

| Change | Where |
|---|---|
| Description names concrete moments and two example questions; it failed `validate.py` N2 before ("whenever you need") | `plugins/memory/agents/memory-status-checker.md` |
| Offload row names the moments and "dispatch it before reading plans or the backlog yourself", replacing "Your judgment, not a fixed moment" | `plugins/memory/user-config/offload-policy.md` |
| Session start text adds a line naming the agent, only when the project has a live state memory | `_STATUS_LINE` in `plugins/memory/engine/mem.py` |
| Trigger cases: `memory-status-checker-with-policy` (the table verbatim) and `memory-status-checker-neg-one-fact` (one git fact must stay inline) | `plugins/memory/evals/trigger/` |

Rejected: adding `resume` to the SessionStart matcher. A resumed session already holds the start text from its transcript; the matcher keeps `startup|clear|compact`.

Revisit if: the positive cases fire in fewer than 2 of 2 runs, or the negative case fires: reword the row or the description, one change per run.
