# Plan cards: whole-run percent and replan call — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Planned agent cards show `<step title> <whole-run %> · <time left>` (no `X/Y`), check the step at 50/80/95%, and rewrite the pending steps with a separate Haiku replan call.

**Architecture:** Pure plan logic and both Haiku prompts live in `plugins/tool-fold/hooks/plan.tsx`; `hooks/agents.tsx` wires the replan after an applied check (`checkPlan`) and draws the header (`runHeader`). No new files besides tests.

**Tech Stack:** TypeScript/TSX mod hooks (`claude-code` mod API), tests with `claude-code/testing`.

**Spec:** `docs/superpowers/specs/2026-11-06-plan-replan-design.md`

## Global Constraints

- `PLAN_ENABLED` stays the single switch; `false` keeps the non-plan cards unchanged.
- The bar/percent never goes back (`anchor`); answers older than the plan's `seq` are dropped.
- Haiku only; replan `maxTokens` 250, `timeoutMs` 15000; at most one replan in flight per run.
- `MAX_TOTAL_STEPS` = 8 (plan build still 3–6).
- `STEP_TITLE_CHARS` 22 → 26 (A7).
- Prompt text in Spanish, code/comments in English; no line numbers stored in the repo.
- Checks before commit (repo root): `claude plugin validate plugins/tool-fold`, `claude plugin test plugins/tool-fold`, `tsc -p plugins/tool-fold`, `python3 scripts/validate.py`.

## Review Focus

1. Replan answer arrives after the step advanced again (stale): must be dropped (`seq` guard) — test in Task 2.
2. Replan reply with too many lines, wrong numbering, or `ninguno` plus lines: plan kept — test in Task 1.
3. Factor applied twice to replanned steps (time left inflates): `fixed` steps unscaled — test in Task 1.
4. A replan that shortens the plan must not lower the shown percent — test in Task 1.
5. 50%/80% checks without a step change must not replan (cost) — test in Task 2.

---

### Task 1: Pure plan logic (`plan.tsx`)

**Files:** Modify `plugins/tool-fold/hooks/plan.tsx`; Test `plugins/tool-fold/tests/plan.test.tsx`

**Interfaces — Produces:**
- `CHECK_FRACTIONS = [0.5, 0.8, 0.95]`; `nextPlanCheck` generalised over its length (`fired` 0..3), same return type.
- `PlanStep.fixed?: boolean` — minutes from a replan; `restMs` sums `estMs × (fixed ? 1 : factor)`; the check prompt's pending line uses the same rule.
- `PlanState.replanSeq?: number` — the `seq` a replan was asked at.
- `MAX_TOTAL_STEPS = 8`.
- `parseReplan(reply: string, from: number, max: number): { title: string; minutes: number }[] | undefined` — `from` is the 1-based number of the first line expected (current + 1); returns `[]` for a reply that is exactly `ninguno` (case-insensitive, trimmed); lines in `parsePlan`'s format, numbered from `from` consecutively, 1..`max` lines; else `undefined`.
- `applyReplan(plan: PlanState, steps: readonly { title: string; minutes: number }[], elapsedMs: number): PlanState` — keeps `steps[0..done]` (done + current), replaces the rest with `{ title, estMs: max(1000, minutes·60000), fixed: true }`, `anchor = planBar(plan, elapsedMs)`.
- `shouldReplan(kind: 'progress' | 'overdue', firedBefore: number, firedNow: number, advanced: boolean): boolean` — true when `advanced`, or `kind === 'overdue'`, or this check is the one that fired the 95% fraction (`firedBefore < CHECK_FRACTIONS.length && firedNow === CHECK_FRACTIONS.length`); hint/ceiling checks after it do not replan.
- `planView` returns `{ percent, step?, isWrappingUp, leftMs }` (drop `text`, `count`, `stepPct`, `shown`, `total`).
- `askReplan($, ask: { mission: string; plan: PlanState; elapsedMs: number; history: string; id: string }): Promise<{ title: string; minutes: number }[] | undefined>` — prompt per spec § Design 3 (`<mision>`, `<pasos_hechos>`, `<paso_actual>`, `<pasos_pendientes>`, `<historial>`), instruction first, one example with lines and one with `ninguno`, closing line repeating the format; logs `plan replan ok|failed` via `logReestimate`.

- [ ] **Step 1: Failing tests** in `tests/plan.test.tsx`:
  - `parseReplan` — `parseReplan('3. Probar — 4 min\n4. Informar — 1 min', 3, 6)` → 2 steps; `'ninguno'` → `[]`; numbering from 2 when `from` is 3 → `undefined`; `max` + 1 lines → `undefined`; `'ninguno\n3. X — 1 min'` → `undefined`.
  - `applyReplan` — on `fresh()` with `done` 1: steps 0–1 unchanged, new ones `fixed`; after `factor` 2 via `applyCount`, `restMs` of fixed steps equals their minutes (no ×2); a replan that halves the rest keeps `planBar` ≥ the value before.
  - `nextPlanCheck` — fires at 50%, 80% and 95% of the step (`fired` 1, 2, 3), 1 min apart.
  - `shouldReplan` — `(progress,0,1,false)` false, `(progress,1,2,false)` false, `(progress,2,3,false)` true, `(progress,3,3,false)` false (a hint after the 95% check), `(overdue,3,3,false)` true, `(progress,0,1,true)` true.
  - `askReplan` — mocked Haiku; prompt contains `<historial>` and `<pasos_hechos>`, `maxTokens` 250.
- [ ] **Step 2:** `claude plugin test plugins/tool-fold` → new tests FAIL.
- [ ] **Step 3:** Implement the interfaces above; update tests that assert `count`/`stepPct`/`text` on `planView`.
- [ ] **Step 4:** Tests pass; `tsc -p plugins/tool-fold` clean.
- [ ] **Step 5:** Commit `feat(tool-fold): plan checks at 95% and a replan parser/applier`.

### Task 2: Wiring and header (`agents.tsx`)

**Files:** Modify `plugins/tool-fold/hooks/agents.tsx` (`checkPlan`, `runHeader`); Test `plugins/tool-fold/tests/plan.test.tsx`; Modify `plugins/tool-fold/README.md` (plan paragraph).

**Interfaces — Consumes:** all of Task 1. `history` text: the run's `history` (≤ 40), oldest first, `- <duration> ✓|✗ <what>` one line each (reuse the line format of `recentCalls`, without the 8 cap).

- [ ] **Step 1: Failing tests:**
  - Header: `/^Leer el código \d+% · ~10 min$/` (title dim, `size: 'footnote'`; percent and time bold); no `/^\d\/\d/` text; all done → `/\d+% · finalizando$/`.
  - Replan trigger: mocked Haiku answering `paso: 2` → a `<historial>` prompt follows; a 50% check answering the same step → no `<historial>` prompt; the 95% check answering the same step → one `<historial>` prompt; a replan reply applied changes the next shown title/time.
  - Stale: replan answer delivered after another check advanced the step (`seq` moved) → plan unchanged.
  - Replay tests (`shownCount`) read the step index from the shown title (titles of the replay plan are distinct) instead of `N/5`.
- [ ] **Step 2:** Tests FAIL.
- [ ] **Step 3:** In `checkPlan`, after the check's `patch` applies, if `shouldReplan(due.kind, plan.fired, due.fired, advanced)` and no replan is in flight for the run (module `Set`), stamp `replanSeq = plan.seq`, call `askReplan`, and apply with `applyReplan` only if the run is running and `item.plan.seq === replanSeq`; then `etaMs = planEndAt(...)`. In `runHeader`, plan datum = `${percent}% · ${isWrappingUp ? 'finalizando' : formatRemaining(leftMs)}`, title span before it when `step` exists; keep one `Text` with nested spans (vscode wrap, see comment there).
- [ ] **Step 4:** All tool-fold tests pass, `tsc` clean, `claude plugin validate plugins/tool-fold`, `python3 scripts/validate.py`.
- [ ] **Step 5:** README plan paragraph: header format, 50/80/95% checks, replan trigger/inputs/`fixed`, `ninguno`, max 8 steps, cost. Commit `feat(tool-fold): plan cards show the whole-run percent and replan pending steps`.

---

## Amendments (pre-mortem 2026-11-06) — required, override the tasks above where they differ

| # | Risk | Amendment | Owner task · test |
|---|---|---|---|
| A1 | Replan storm on a stuck step: `applyLeft` with `falta: 1` and 0 remaining moves the end ~30 s, overdue refires, `shouldReplan('overdue')` always true | `PlanState.replannedDone?: number`: a replan **without a step change** runs at most once per `done` value (an advance always may replan) | T1/T2 · stuck step, overdue checks answering `falta: 1` for 10 min → exactly 1 `<historial>` prompt |
| A2 | Factor applied twice when a `fixed` step becomes current (`applyCount` sets `stepEstMs = estMs × factor`) | One helper `scaledMs(step: PlanStep, factor: number): number` used by `restMs`, `applyCount` and `askStepCheck`'s pending lines | T1 · replan, then advance with factor 2 → `stepEstMs` equals the fixed `estMs` |
| A3 | `checkPlan`'s closure `plan` is the pre-check state (old `seq`, old `done`) | Capture the plan the check's `patch` updater produced (outer variable), ask the replan from it after the patch resolves; apply guard: `item.plan.seq === replanSeq && item.plan.done === asked.done` | T2 · check advances 1→2, Haiku's step 3 becomes the next pending step (no duplicate of step 2) |
| A4 | Haiku's minutes make the percent jump up (short round numbers, early `ninguno`) | `applyReplan` scales the new pending minutes so their sum stays within 0.5–2× the old `restMs`; `ninguno` accepted only when at most 1 step was pending, else treated as a failed parse | T1 · halving the rest → `planBar` rises ≤ 15 points; `ninguno` with 3 pending → plan kept |
| A5 | Anchor computed at ask time, answer arrives up to 15 s later → bar can drop | `applyReplan` takes the elapsed ms read from `$.clock.now()` when the answer is applied | T2 · answer delayed 15 s → shown percent not below the pre-answer value |
| A6 | Haiku numbers from 1 → strict parse always fails | `parseReplan` accepts a consecutive list starting at `from` **or at 1** (renumbered), logs which | T1 · `'1. A — 2 min\n2. B — 1 min'` with `from` 3 → 2 steps |
| A7 | vscode header clips the time left (`wrap="truncate"`) | `STEP_TITLE_CHARS` = 26 (not 32) | T2 · header test with a 40-char title ends in `· ~N min` |
| A8 | `invalid plan reply falls back` test becomes vacuous without `N/M` | Assert the plain `≈N%` card and that no step title appears | T2 |

Kill criteria (record in README limits if hit): replans > 2 × steps per run, or > 30% replan parse failures, in the first 10 real runs → set `REPLAN_ENABLED` false (new constant in `plan.tsx`, default true) and fix; any replan lowering the shown percent or raising it > 15 points; vscode header losing the time left.
