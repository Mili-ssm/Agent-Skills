---
name: intent-elicitation
description: Use when intent, requirements, constraints or context of a project, feature or significant change are unclear, undocumented, contradictory or possibly stale - infers intent from code and docs, then interviews the owner with as many question rounds as needed and records the answers as requirements and ADRs.
---

# Intent Elicitation

Goal: no material ambiguity left between what the owner wants, what the docs say and what the code does. Runs in the **main conversation** because it must ask questions (subagents cannot). Complements Superpowers `brainstorming`, which designs something new; this skill reconciles what already exists.

## Modes

| Mode | Scope | Typical trigger |
|---|---|---|
| `project` | Whole repo | Onboarding, inherited code, before major planning |
| `feature` | One feature/module | Before extending or rewriting it |
| `change` | A proposed significant change | Before planning; pair with `change-impact` |

## Process

### 1. Gather evidence (delegate the noise)

Dispatch the `consistency-auditor` agent with the mode and scope. It returns: inferred intent, findings register (contradictions, ambiguities, stale decisions, implicit decisions) and candidate questions. If the agent is unavailable, run its process inline but keep only conclusions.

### 2. Build the intent hypothesis

Write a short hypothesis before asking anything:

```markdown
Purpose · users · core jobs · constraints · quality attributes (ranked) · non-goals · assumptions (each marked)
```

Asking from a hypothesis gives the owner something to correct; asking from nothing produces vague answers.

### 3. Interview loop

- Use `AskUserQuestion`: ≤ 4 questions per round, each with 2–4 concrete options and your recommended option first.
- Order by **impact × uncertainty**: questions whose answer changes architecture, data or scope first.
- Draw questions from [the question bank](references/question-bank.md); skip what evidence already answers.
- Each answer can open new questions; keep looping until the stop criteria hold. There is no round limit.
- Contradiction found → show both sources and ask which is true; never pick silently.
- Record answers as you go (step 4), not only at the end.

**Stop when:** every high-impact finding is resolved or explicitly deferred by the owner, and each requirement passes [the quality checks](references/requirements-quality.md).

### 4. Record

| Output | Where |
|---|---|
| Requirements (EARS-phrased, IDs) | Existing requirements doc, else `docs/requirements.md` |
| Decisions and their rationale | ADRs via `decision-records` |
| Deferred / open items | "Open questions" section with owner and trigger |
| Stale decisions confirmed | Supersede ADR or add review note with date |

Docs follow `docs-principles`: dense, no duplication of code facts.

### 5. Report

```markdown
## Intent (confirmed)
## Resolved findings | ID | Resolution | Recorded at |
## Deferred | ID | Why | Revisit trigger |
## Changes made to docs/ADRs
```

## Rules

- Never fabricate an owner answer or infer one from silence.
- Separate **requirements** (what must hold), **constraints** (imposed limits), **assumptions** (believed, unverified) and **preferences**.
- Quote evidence (`file:line`) when asking about a contradiction.
- Revisit ratings use the `decision-records` staleness rubric, never percentages.
