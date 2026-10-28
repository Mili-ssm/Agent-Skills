---
name: feature-briefing
description: Orchestrates a briefing before building a new feature - brainstorming with the owner, parallel researcher, consistency-auditor and specialist subagents to contrast docs, code, requirements and external practice, then an options decision and an implementation plan stress-tested by pre-mortem. Use when asked how to approach or plan a new feature or significant change, or to compare ways of doing something before committing; load it before planning so evidence is gathered in parallel and the decision is recorded.
---

# Feature Briefing

A briefing turns "how should we build X?" into a decided, evidenced plan. It runs in the **main conversation** because subagents cannot dispatch other subagents or ask the owner questions. It chains existing pieces instead of duplicating them.

## Workflow

Copy and tick:

```
- [ ] 1 Frame: goal, success criteria, constraints (Superpowers brainstorming if installed; else intent-elicitation in feature mode)
- [ ] 2 Gather evidence in parallel (one message, several subagents)
- [ ] 3 Synthesize: options matrix
- [ ] 4 Decide with the owner; record an ADR if significant
- [ ] 5 Impact and plan: change-impact, then the plan (Superpowers writing-plans if installed)
- [ ] 6 Stress-test: pre-mortem on the plan; amend
- [ ] 7 Brief: one-page summary
```

**2. Evidence** — dispatch only what the feature needs, all at once:

| Question | Subagent |
|---|---|
| What do our docs, ADRs and code already say or assume? | `consistency-auditor` (mode `change`) |
| What do official docs and practitioners recommend? | `researcher` × 1–5, one question each |
| Does it fit the architecture? | `architect` (mode `propose`) |
| Security, UX or test risks? | `security-reviewer` / `ux-reviewer` / `qa-engineer` (mode `design`), when relevant |
| Where does the code change? | `Explore` (Haiku with the user-scope override) |
| What do long specs, logs or tickets say? | `summarizer` |

Each brief states the question, the decision it feeds and a max length, so reports stay small.

**3. Options matrix**:

```markdown
| Option | Fits requirements | Fits existing code/ADRs | External evidence | Risks | Effort S/M/L | Reversibility |
```

Prefer the simplest option that meets ranked quality attributes and is reversible (two-way door); name what would change the choice.

**4. Decide**: present the matrix with a recommendation via `AskUserQuestion`; the owner decides. Significant choices → ADR (`decision-records`).

**7. Brief output**:

```markdown
## Goal and success criteria
## Evidence (cited, conflicts noted)
## Options and decision (+ ADR link)
## Plan (link) and pre-mortem amendments
## Open questions and kill criteria
```

## Rules

- Parallelize independent evidence gathering; sequential dispatch wastes wall-clock time.
- Keep raw research in subagents; the main thread holds only distilled findings.
- Skip steps that add nothing for small features (say which and why).
- No code is written during a briefing. Execution later goes to `implementer` (one bounded task each, owned files) with `check-runner` for verification.
