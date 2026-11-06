# Plan cards v3: Haiku judges "done?", code owns time, steps remembered (tool-fold)

Status: proposed · Date: 2026-11-06 · Amends [2026-11-06-plan-replan-design.md](2026-11-06-plan-replan-design.md) and [2026-11-02-plan-step-tracking-design.md](2026-11-02-plan-step-tracking-design.md)

## Intent
Owner's `/agents-debug` of an implementer run (2026-11-06): `factor=0.50` (the floor), then a loop of `plan step 4 ignored (done=3/5)` + `plan overdue ok done=3→3/5` every ~30 s, no replan line, card stuck at `94% · ~1 min` for minutes. Reading:
- Step detection was right at that point (Haiku kept "step 4"); the **time model** failed: a 0.5 factor from fast early steps halved the long testing step and the rest; `falta` blended 50/50 with a 30 s floor creeps the end; replans are clamped to ≤ 2× a tiny rest.
- `factor` at its floor also means steps 1–3 were closed in ≤ half their estimate: premature advances (the 2026-11-02 rule "a step is current as soon as its kind of work starts", and an implementer runs tests from the start) or genuinely fast steps. Either way one global factor that can shrink the rest is a poor predictor.
- Owner (2026-11-06): proceed with B + logging; store steps and their times in the mod's memory to improve future plans; typical series maybe too much.

Research (2026-11-06, snippets; arxiv not reachable): showing a judge its previous answer anchors it (7/8 models); yes/no against a criterion is steadier than scales; LLM numeric answers round and anchor; ETA practice = observed pace + history of similar runs; stalls near the end hurt most.

## Goals · non-goals · anti-goals
- Goal: the time left never sits at `~1 min` while a step overruns; Haiku answers only what it judges well (is the current step done, with evidence).
- Goal: each finished planned run leaves its steps with planned and real times, used by later plan builds and to measure accuracy.
- Non-goal: the 64% command-translation failure rate (separate task); aggregated per-step statistics (examples of similar runs suffice for now).
- Anti-goal: the percent going back; more Haiku calls than v2 on a stalled step.

## Approaches (owner picked B + logging, 2026-11-06)
| | Approach | Trade-off |
|---|---|---|
| A | Prompt tweaks only (narration, criteria, no anchor) | Haiku still guesses minutes |
| **B** | Haiku answers yes/no with evidence; code computes time; event-driven checks | Medium change; deterministic time |
| C | Data first: traces + hindsight labels before changing behaviour | Slow to help |

## Design
1. **Factor never shortens.** `FACTOR_MIN` 0.5 → 1: real/estimated of finished steps (1 to 3) lengthens what remains, never shrinks it (an early finish ends the run sooner: the pleasant surprise).
2. **Overdue growth in code.** A check that does not find the step done once it is past `stepEndAt + OVERDUE_GRACE_MS` sets `stepEndAt = elapsed + max(1 min, 0.5 × time in step)`. No `falta`; `applyLeft` goes.
3. **Overdue backoff.** Overdue checks of one step are spaced 30 s, 1, 2, 4 min (then 4 min); the counter resets when the step advances.
4. **Binary check.** Reply `evidencia: <short quote from <llamadas> or <dice_el_agente>, or ninguna>` then `terminado: sí|no` (evidence first). Input: mission; current step title and its `listo cuando` criterion; next step title and criterion (if the agent already works on it, the current one ended); activity since the step began; last 8 calls; the agent's last 3 text messages (`<dice_el_agente>`, labelled a claim, not proof); thinking state. No previous-step number, no calendar reference. `sí` with calls added since the last check (G1) advances exactly one step and marks a hint, so a fast following step is checked again after the 1-min gap (supersedes the owner's 2026-11-03 multi-step jumps: one binary verdict judges one step; catch-up is consecutive checks). `no` or no answer on an overdue check grows the step (2).
5. **Triggers.** `overdue` (2, 3), `event` (a hint after the last check: call words, thinking, the agent's text pointing at a later step's title or criterion; ≥ 1 min gap) and `ceiling` (5 min without a check). The 50/80/95% fractions go.
6. **Plan build.** Lines `N. <título> — M min — listo cuando: <criterio>` (criterion optional for the parser, ≤ 100 chars); `maxTokens` 400. `<tareas_parecidas>` shows each similar run's real steps when stored: `… — 14 min (pasos reales: Leer 2 · Implementar 6 · Probar 5 · Informar 1)`.
7. **Replan.** Only after an advance and only when at least one step follows the new current one. Same line format with criteria; minutes are a split, not a total: code scales them to the old pending (unscaled) sum, so the total and the percent do not jump. `ninguno` keeps the plan. Max 8 steps. `fixed`, `replannedDone` and the 0.5–2× clamp go.
8. **Memory.** A planned run that ends well stores `steps: { title, estMs, ms }[]` (real ms; the last step ends at the run's end) in its `agent-samples` entry (last 50, old entries without steps stay valid). Used by (6) and to compare planned vs real per step.
9. **Narration.** `session.append` with an `agentId` and `door: 'response'` keeps the run's last 3 text blocks (300 chars each) as `said`. Unverified against a live session: that subagent responses arrive with `agentId` and `door: 'response'`.
10. **Logs.** `plan check <kind> terminado=sí|no|? evidencia="…" → advanced|kept|grown`; `plan step N kept` replaces "ignored"; plan build logs whether criteria came.

## Left to the builder
Prompt wording (Spanish, instruction first, examples for sí and no), type shapes, test rewrites for the removed `falta`/fractions behaviour (every removed assertion replaced by its v3 counterpart), README plan paragraph.
