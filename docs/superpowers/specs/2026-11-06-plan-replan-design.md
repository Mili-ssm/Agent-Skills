# Plan cards: whole-run percent, 50/80/95% checks and a separate replan call (tool-fold)

Status: proposed · Date: 2026-11-06 · Builds on [2026-11-02-plan-step-tracking-design.md](2026-11-02-plan-step-tracking-design.md)

## Intent
The owner, after using planned agent cards for days (screenshot 2026-11-06: `4/6 Probar vista por defe… 98% · ~2 min`):
- The `X/Y` count misleads: the step does not always advance, yet the plan works well as a reference.
- The shown percent is the current step's share (`stepPct`), which reads as the whole run's.
- The plan should become (1) a summary of what the agent is doing now (distinct from its last call, line 3) and (2) the basis of the time estimate, corrected as the run goes: near the end of each step, check whether it finished and how much is left, then regenerate the following steps from the human-readable call history and the steps done with their times.

## Goals · non-goals · anti-goals
- Goal: the header reads `<current step title> <whole-run %> · <time left>`; the remaining steps and their minutes are rewritten from evidence at least once per step.
- Goal: each Haiku call has one job (owner, 2026-11-06: split responsibilities to improve recalculation).
- Non-goal: changing the plan build (`askPlan`), the hint triggers (call words, `pensando…`, 5-min ceiling) or the non-plan `≈%` cards.
- Anti-goal: a percent that goes back, or that jumps on every replan (the `anchor` rule stays).

## Approaches (owner delegated the choice, 2026-11-06)
| | Approach | Trade-off |
|---|---|---|
| A | One call at 95% answering step, minutes left and the remaining steps; drop 50/80% | Fewest calls; one prompt with three jobs, weaker on each |
| **B (picked)** | Two calls: the existing check (`paso`, `falta`) at 50/80/95% and on hints/overdue; a new replan call (remaining steps) after a check that moved the step or found it unfinished at 95%/overdue | One job per prompt; ~1–2 more calls per step |
| C | Replan only when the step changes or runs overdue | Cheapest; a stalled step is corrected late |

Why B: the owner asked for split responsibilities; the check prompt is already tuned (2026-11-02 review) and stays as is; the replan prompt can take the long history without confusing the step question. A 99% check is not added: the overdue check (step end + `OVERDUE_GRACE_MS`) already is the "reached 100%" check, and a check at 99% and 100% would be 15 s apart.

## Design
1. **Header.** `Probar vista por defecto… 62% · ~8 min`: step title dim (as today, `STEP_TITLE_CHARS` 22 → 32, the freed room of `X/Y`), then `planBar` (the whole-run percent, the same value the bar draws), then the time left. All steps done while running: `99% · finalizando`, no title. `stepPct` and `count` go from the view.
2. **Check (existing `askStepCheck`).** Fractions `[0.5, 0.8, 0.95]` of the current step; hints, thinking, 5-min ceiling and overdue unchanged. Applying `paso`/`falta` unchanged (G1–G7 of the 2026-11-02 design).
3. **Replan (new `askReplan`).** Fires right after an applied check when (a) the step advanced, or (b) the check was the 95% one or overdue and the step did not advance. At most one replan in flight per run; a replan answer is dropped if the plan's `seq` moved since it was asked.
   - Input: `<mision>`; `<pasos_hechos>` (title, planned and real minutes); `<paso_actual>` (title, minutes spent, minutes left after the check); `<pasos_pendientes>` (the current pending titles and minutes, reference); `<historial>` (the run's `history`, up to 40 calls, oldest first, `what` text with duration and ✓/✗).
   - Output: the steps after the current one, one `N. <title> — M min` line each, numbered from current + 1, 0 to `MAX_TOTAL_STEPS − done − 1` lines (`MAX_TOTAL_STEPS` 8), or the single word `ninguno` when the current step is the last. Strict parse; anything else keeps the plan (logged for `/agents-debug`).
   - Apply: done and current steps frozen; pending steps replaced, marked `fixed` (their minutes are Haiku's, already informed by real times, so `factor` does not scale them again); `etaMs` = new plan end; the bar keeps its `anchor`.
4. **Cost.** Per step: up to 3 checks (was 2) plus 1–2 replans (`maxTokens` ~250, 15 s timeout), Haiku only.
5. **Docs.** `plugins/tool-fold/README.md` plan paragraph rewritten; this file is the design record.

## Left to the builder
Exact replan prompt wording (after a `prompt-engineer` read), the `fixed` flag vs. baking the factor into pending steps, tests: parse (`ninguno`, numbering, limits), apply (frozen past, no double scaling, monotonic bar, stale drop), the trigger rule (advanced / 95% / overdue, never at 50/80% without a step change), the header text.
