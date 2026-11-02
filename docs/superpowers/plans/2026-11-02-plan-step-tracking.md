# Plan Step Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan checks ask Haiku the current step and the minutes left in it, from richer evidence, with hard guards in code.

**Architecture:** `plugins/tool-fold/hooks/plan.tsx` owns the prompt, parse and pure apply functions; `hooks/agents.tsx` builds the evidence (activity summary, calls) and calls them from `checkPlan`. Triggers are unchanged.

**Tech Stack:** TypeScript Claude Code mod; tests with `claude plugin test plugins/tool-fold`.

**Spec:** `docs/superpowers/specs/2026-11-02-plan-step-tracking-design.md`

## Global Constraints
- Render never writes state; all writes from events/tick.
- `PLAN_ENABLED=false` keeps today's non-plan behaviour.
- Prompt text: the prompt-engineer version in the spec § Prompt (Spanish, instruction first, examples paso 3/4/2 with falta 2/9/6).
- maxTokens 40 for the check call.
- Checks before commit: `claude plugin test plugins/tool-fold`, `claude plugin validate plugins/tool-fold`, `python3 scripts/validate.py`.

## Review Focus
- Agent never edits (pure reading/measuring run): steps must still move by kind of work (reads → measuring commands).
- Reply with only `paso` or only `falta`: apply the part present.
- Haiku answers `paso` beyond N or below previous: ignored (count stays), logged.
- A check while all steps done: no check (unchanged).
- Long thinking with no calls: G1 blocks advancing (history did not grow).

---

### Task 1: Pure logic in plan.tsx (parse, apply, prompt)

**Files:** Modify `plugins/tool-fold/hooks/plan.tsx`; Test `plugins/tool-fold/tests/plan.test.tsx`

**Interfaces — Produces:**
- `parseStepReply(text: string, total: number): { step?: number; leftMin?: number }` — key regexes over first 3 non-empty lines, ignoring `**`, `~`, `min`; step only if 1 ≤ N ≤ total.
- `applyStep(plan: PlanState, step: number, elapsedMs: number, now: number, historyGrew: boolean): PlanState | undefined` — done = min(step − 1, plan.done + 1) (G1); undefined unless historyGrew and done > plan.done; skipped steps excluded from factor (G2); snapshot hook for G7 via a `countsAtStep` field set by the caller.
- `applyLeft(plan: PlanState, leftMin: number, elapsedMs: number): PlanState` — clamp [0.5 min, 3× stepEstMs], blend 50/50 with current remaining, shorten ≤30% (G3); anchor = planBar first, then stepEndAt/stepEstMs/fired as `applyOverdue` (G4).
- `askStepCheck($, ask: { mission; plan; elapsedMs; activity: string; calls: string; thinking?: string; id }): Promise<{ step?: number; leftMin?: number } | undefined>` — replaces `askStepCount`; logs parse failures.
- Overdue branch of `nextPlanCheck` stays as a trigger but uses `askStepCheck` (no separate minutes ask).

- [ ] Step 1: tests — parse variants (`paso: 3\nfalta: 4`, `**paso:** 2`, `falta: ~3 min` only, swapped order, paso 9 of 5 → no step); applyStep +1 cap (answer 4 from done 0 → done 1), no advance when !historyGrew, never decreases; applyLeft clamp/blend/30% rule and bar never drops when falta grows.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; prompt text from spec § Prompt.
- [ ] Step 4: run, expect PASS.

### Task 2: Evidence and wiring in agents.tsx

**Files:** Modify `plugins/tool-fold/hooks/agents.tsx`, `README.md` (one sentence); Test `plugins/tool-fold/tests/plan.test.tsx`

**Interfaces — Consumes:** Task 1 functions. **Produces:** `activitySummary(run, plan): string` (since start / since current step, from `run.counts` and a `countsAtStep` snapshot stored on the plan when a step starts; tests counted by command text matching `test|pytest|cargo test|bun test|jest|vitest`); `recentCalls(run, now): string` (≤8, newest last, translated text).

- [ ] Step 1: replay tests (pattern of the deleted diagnosis: 5-step plan 120/15/10/5/5 min, a call every 20 s, thinking gaps): truthful mock reaches ≥3/5; frozen activity (no new calls, clock +10 min) does not move `paso`; prior 2/23 vs 22/23 gives the same applied step (mock echoes the prior to prove it is labelled, assert prompt contains `solo referencia`); falta increase never drops the bar.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: wire `checkPlan` to `askStepCheck`; apply count first then falta (G5); historyGrew = history length grew since last check (store `historyAtCheck` on the plan); `/agents-debug` logs parse failures and each applied/kept check.
- [ ] Step 4: all three checks pass; commit.
