# 0039 The main conversation budgets calls, reports and briefs

Status: accepted · Date: 2026-11-27 · Amends 0013, 0017

## Context

- 7 days to 2026-11-27, 52 main sessions: the main session made 73% of spend; 60% of its 6,824 calls ran one shell command, at a median context of 248k tokens re-read per call. Figures, scripts and sources: [the plan](../superpowers/plans/2026-11-27-main-context-token-reduction.md) § Why and § Stage 0 figures.
- A dispatch keeps about six times more out of the main than it adds (median 2,984 tokens added), so delegation pays; the cost that remains sits in reports (caps stated in lines did not bound them: 546 words under 40 lines), in briefs that restate files, and in `skeptical-reviewer`, the most frequent dispatch (6.0 per 100 main calls), whose triggers overlapped.
- A Codex user reported fast quota use. The owner's rollouts showed why: Codex 0.171 `spawn_agent` defaults to `fork_turns: "all"`, and a forked worker's first request held a median 118k input tokens against 25.6k fresh (plan § Codex findings).
- Owner rulings 2026-11-27: fewer main calls, a report budget, briefs by reference; a reviewer rethink; D1 yes for plan-loop fix rounds, D2 a measured workflow pilot, D3 text only. The context ceiling stays.

## Decision

1. Worker reports are capped in words by one fragment (`shared/fragments/report-budget.md`): result first, specifics verbatim, `Left out:` for the rest; a brief may lower a cap, never raise it. Caps per agent: plan stage 1 table. The eight specialists and `consistency-auditor` keep their caps.
2. A brief has four parts and names files a worker can open instead of restating them; every worker carries its own stop rule and report format (`shared/fragments/worker-brief.md`, `stop-rule.md`).
3. `skeptical-reviewer` reviews each change once, with no size threshold; round 2 runs only when a fix touches a file or behavior no finding named; low findings are one hedged line each; the plan-loop fix worker verifies findings first and lists the refuted ones (D1).
4. The offload policy counts calls before tokens: batch independent commands and tool calls; delegate from about eight calls of inline work (twelve for code); rows with their own threshold keep it; no filler messages while waiting (D3).
5. The Codex port tells Codex to spawn every worker with `fork_turns: "none"` and to wait with `wait_agent`.

## Alternatives

| Option | Rejected because |
|---|---|
| Lower the context ceiling or the fixed load | Owner ruling 2026-11-27; the fixed load is P5 and needs an ADR against 0021 |
| Tool-output filters | Raised billed cost 6.8% in the one independent study (plan § What the literature adds) |
| Batch reviews to the end of a plan | A late finding costs rework across tasks |
| Terse notation (JSON, TOON) for reports | Gains inside noise; strict formats lower reasoning |
| `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` to make the main wait | Also removes background Bash (owner, D3) |

## Consequences

- Users who pasted the offload table or the routing text, in Claude Code or Codex, must paste the new version (CHANGELOG).
- `CODEX_REWRITES` anchors on four exact source sentences; editing one breaks `port.py` until the rewrite changes too.
- The `skeptical-reviewer-quality` graders judge the new low-line format.
- Hooks that enforce the cap or the call economy stay escalations (plan stage 7), Claude Code only.

## Revisit if

The after-read (plan stage 7, five working days after the release) hits a "Revert or escalate" row: follow-ups above 15% of dispatches, `implementer` redo above 33%, reports with a high finding below 12%, a defect that a skipped review would have caught, or a Codex role child whose first request exceeds 40k input tokens.

## Measurement 2026-11-27

Eval protocol, Sonnet main model, `--runs 2`, `--scaffold --allow-tools Bash Edit Write`, `claude plugin eval` 2.1.332, branch `feat/main-context-budget` at `a52a2da` (stages 1–5 and review round 1). Records: ADR 0032 Measurement 2026-11-26 (`-with-policy`, `-with-hook`), ADR 0017 (`offload-skeptical-reviewer-quality`). Spend: 6.7 USD, of which 1.6 USD on a first run stopped and discarded after review round 1 changed the measured text.

| Case | `-with-policy` | `-with-hook` | Record |
|---|---|---|---|
| `offload-check-runner` | 2/2 | 2/2 | 2/2 · 2/2 |
| `offload-skeptical-reviewer` | 2/2 | 2/2 | 2/2 · 2/2 |
| `offload-summarizer` | 2/2 | 2/2 | 2/2 · 2/2 |
| `offload-summarizer-extract` | 2/2 | 2/2 | 2/2 · 2/2 |
| `offload-implementer` | 0/2 (`delegated` 0/2) | 0/2 (`delegated` 0/2) | 0/2 · 0/2 |
| `offload-ui-verifier` | 1/2 (browser graders) | 0/2 (browser graders) | 0/2 · 0/2, environment (backlog 3g) |
| `offload-skeptical-reviewer-quality` | 2/2 | — | 3/3, 4/6 |
| `offload-check-runner` (no policy) | 0/2, then 1/6 at 6 runs | — | none recorded; `dev` at 6 runs the same day: 1/6 |
| `neg-*` (5 cases) | 10/10 silent | — | 10/10 |
| Canary: `offload-summarizer` · `-with-hook` (first run) | table absent 0/2 · present 2/2 | — | same |

- The first run, before review round 1, had `offload-skeptical-reviewer-with-policy` at 0/2 (`delegated` 0/2): the main wrote a 60-line, two-file change and replied without a review. The call-economy rule then said "this rule covers the rest", and a change that small probably fell under its eight-call threshold (inferred: the eval deleted the traces). Round 1 added "`skeptical-reviewer` has no size threshold: it reviews every change", and the case returned to 2/2.
- Report size: the reviewer's report as it lands in the main measured 2,228, 2,444, 2,452 and 2,516 characters (342 to 407 words with the frame) in four runs (`-quality`, `-with-hook`), against a 4,750-character median baseline and a 2,900 target. The other agents' sizes are left to the after-read (stage 7), because the cases dispatch them with briefs of their own.
- Two runs per case are too few to claim equivalence or a gain. `implementer` stays at its record: the main writes the 60-line task itself in every arm, before and after.
