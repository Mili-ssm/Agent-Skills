# Plan step tracking: current step + remaining minutes (tool-fold)

Status: proposed · Date: 2026-11-02

## Intent
Long agent cards with a step plan (`plugins/tool-fold/hooks/plan.tsx`) stay at `0/N` and jump at the end. A replay showed checks fire every 40–80 s and answers apply; the cause is the evidence and the prompt: `<progreso>` lists bare calls (`✓ Read f5.md`), and the prompt says "con duda, repite" and "el tiempo no prueba nada", so a conservative Haiku answers 0. The owner wants Haiku to answer two things: which step the agent is on, and how long each unfinished step takes.

## Goals · non-goals · anti-goals
- Goal: the count moves when activity changes phase; the time left reflects Haiku's reading of the current step.
- Non-goal: changing triggers (hints, thinking, 5-min ceiling, 1-min gap) — they already fire often enough.
- Anti-goal: a count driven by elapsed time alone (the schedule prior must not replace evidence).

## Approaches (owner picked A)
| | Approach | Trade-off |
|---|---|---|
| **A** | Richer evidence + one call answering `paso: N` and `falta: M` | Same call count; prompt quality decides |
| B | Deterministic phase from tool kinds per step | Free per check, fragile mapping |
| C | B triggers, A confirms | More parts, small gain over A |

## Design (A)
- One check call returns two lines: `paso: N` (current step, 1-based; done = N − 1, never decreases) and `falta: M` (minutes left in the current step). The overdue-step ask disappears; every check carries `falta`.
- Prompt order: instruction; plan with expected minutes per step, real minutes of finished steps, minutes spent in the current one; schedule prior labelled "solo referencia, no es una prueba"; activity summary; last ~8 calls (translated text) and thinking state at the end (edges of context, Liu et al. 2024).
- Activity summary (deterministic, from `run.counts`/history): files read, files edited/created, commands run, test runs, since start and since the current step began.
- Decision rule replaces "con duda, repite": choose the step whose description best matches the recent activity; a step counts as current once its kind of work started.
- `falta` updates the current step's end (`stepEndAt = elapsed + falta`); remaining steps keep the factor; bar anchor and monotonic rules unchanged.
- Parsing: first two lines, each strict; a missing `falta` keeps the time, a missing `paso` keeps the count.

## Evidence
Replay (diagnosis 2026-11-02): truthful answers moved 0→1→2→3; conservative answers kept 0/5 all run. Research: counting is weak in LLMs (arXiv 2409.07638); numeric anchors bias outputs (arXiv 2202.12299, 2505.15392); stalls then jumps read as deceptive (Apple HIG progress indicators).

## Left to the builder
Exact wording (after prompt-engineer review), summary format, tests (replay with a truthful and a conservative mock; parse; monotonic).

## Prompt (prompt-engineer, 2026-11-02)
Instruction first; rules: `paso` = step whose kind of work best matches `<actividad>`/`<llamadas>`, current as soon as its kind of work started, never below `<paso_anterior>`; repeat only if the previous step still fits, else advance; `falta` = whole minutes left in that step from the work seen, minimum 1; `<referencia_calendario>` is reference only. Three examples at different steps (3, 4, 2) incl. an overdue one. Data: `<mision>`, `<pasos>` (expected min; real min for finished; minutes in current), `<paso_anterior>`, `<actividad>` (since start / since current step), `<referencia_calendario>`, `<llamadas>` (≤8, newest last), `<pensando>` when thinking; closing line repeats the format.

## Guards (pre-mortem, 2026-11-02) — required
| # | Guard |
|---|---|
| G1 | Advance only if the history grew since the last check. (The +1-per-check cap was dropped by the owner on 2026-11-03 to accept fast steps; it may return.) |
| G2 | Skipped steps (if any) stay out of the factor |
| G3 | `falta` clamped to [0.5 min, 3× step estimate], blended 50/50 with the previous value, never shortening more than 30% per check |
| G4 | On every `falta` apply: anchor = current bar first, then update the step estimate and the 50/80% `fired` like an overdue update |
| G5 | Count applied before `falta`, and `falta` refers to the (possibly new) current step |
| G6 | Lenient parse: key regexes over the first 3 non-empty lines, ignoring `**`, `~`, `min`; 1 ≤ paso ≤ N; maxTokens 40; parse failures logged in `/agents-debug` |
| G7 | "Since current step" summary from a `countsAtStep` snapshot taken when the step starts; test runs detected by command text |

## Kill criteria
Parse failures > 10% of checks; a frozen-activity replay (same calls, clock +10 min) moves `paso`; time left jumping > 2 min between checks in > 20% of checks; checks per run > 1.3× today.

## Tests
Replay with a truthful mock (count must reach ≥3 of 5) and a conservative mock; frozen-activity replay; prior 2/23 vs 22/23 gives the same `paso`; parse variants; bar never drops on a `falta` increase.
