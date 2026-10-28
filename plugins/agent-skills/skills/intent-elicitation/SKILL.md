---
name: intent-elicitation
description: Reconstructs intent from code and docs, then interviews the owner in prioritized question rounds until no material ambiguity remains, recording answers as EARS requirements and ADRs. Use when requirements, constraints or the reasons behind existing code are unclear, undocumented, contradictory or possibly stale, for a whole project, a feature or a significant change.
---

# Intent Elicitation

Goal: what the owner wants, what the docs say and what the code does agree, with every remaining gap explicit. Runs in the **main conversation** because subagents cannot ask the user questions. Superpowers `brainstorming` (if installed) designs something new; this skill reconciles what already exists.

## Modes

| Mode | Scope | Typical trigger |
|---|---|---|
| `project` | Whole repo | Onboarding, inherited code, before major planning |
| `feature` | One feature/module | Before extending or rewriting it |
| `change` | A proposed significant change | Before planning; pair with `change-impact` |

## Workflow

Copy and tick:

```
- [ ] 1 Evidence: dispatch the consistency-auditor subagent (mode, scope) → findings + candidate questions
- [ ] 2 Hypothesis: purpose · users · core jobs · constraints · ranked quality attributes · non-goals · assumptions (marked)
- [ ] 3 Interview rounds until the stop criteria hold
- [ ] 4 Record answers as you go
- [ ] 5 Report
```

1. **Evidence**: the subagent keeps noisy scanning out of this context; long specs or transcripts go to `summarizer`. Unavailable → run its checks inline and keep only conclusions.
2. **Hypothesis first**: the owner corrects a concrete draft faster and more precisely than they answer open questions.
3. **Interview** with `AskUserQuestion`:
   - ≤ 4 questions per round, each with 2–4 concrete options, recommended option first.
   - Order by impact × uncertainty: answers that change architecture, data or scope come first.
   - Draw from the [question bank](references/question-bank.md); skip what evidence already answers.
   - For a contradiction, show both sources (`file:line`) and ask which holds.
   - Each answer may open new questions; keep looping (no round limit).
   - Ask in the owner's language.
4. **Record**:

| Output | Where |
|---|---|
| Requirements (EARS, IDs) | Existing requirements doc, else `docs/requirements.md` |
| Decisions with rationale | ADRs via `decision-records` |
| Deferred items | "Open questions" with owner and revisit trigger |
| Confirmed or refuted stale decisions | Dated `Review` note on the ADR, or a superseding ADR when the decision changes |

5. **Report**:

```markdown
## Intent (confirmed)
## Resolved | ID | Resolution | Recorded at |
## Deferred | ID | Why | Revisit trigger |
## Docs/ADRs changed
```

**Stop when** every high-impact finding is resolved or explicitly deferred by the owner and each requirement passes the [quality checks](references/requirements-quality.md).

## Rules

- Record only answers the owner gave; unanswered items stay open, because an inferred answer becomes a false requirement.
- Keep requirements (must hold), constraints (imposed), assumptions (believed, unverified) and preferences in separate lists; they change for different reasons.
- Rate stale decisions with the `decision-records` staleness rubric.
- Write records per `docs-principles`: dense, no copies of code facts.
