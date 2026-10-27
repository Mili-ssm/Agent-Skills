# 0007 Anthropic authoring conventions, measured by evals

Status: accepted · Date: 2026-10-27

## Context

Baseline trigger evals (`claude plugin eval`, 13 cases × 2 runs, Sonnet) fired the right skill/agent in 42% of runs; knowledge skills (QA, UX, security, architecture, docs, observability) almost never fired. Descriptions started with "Use when…" and never said what the skill does. A `doc-curator` + `consistency-auditor` self-audit found negative-only rules without reasons, inconsistent terms ("QA" for quality attributes), processes duplicated between skills and agents, derivable catalogs, and "read-only" agents enforced only by prompt text.

## Decision

- Follow Anthropic's skill-authoring and prompting guidance, digested in `skills/docs-principles/references/prompt-authoring.md`; `scripts/validate.py` enforces the checkable parts (what + when, third person, ≤ 1024 chars, name format, `## Contents` above 100 lines).
- Agents reference their skill's workflow and keep only role, modes, agent-specific additions, rules and output; no copied processes.
- Rules are positive with a reason; one canonical `<example>` per agent output.
- Vocabulary: "quality attribute" in full; "owner" for the human decision-maker; "subagent" for the mechanism; "findings" for defects, "risks" for pre-mortem/change-impact; "churn hotspot" vs. "profile hotspot"; ratings `low | medium | high` unless a domain scale is declared (Nielsen 0–4, security critical…info, architecture critical…note).
- Reviewer agents get `disallowedTools: Edit, Write, NotebookEdit`.
- No "use proactively" in descriptions: current models already over-delegate.
- Small role-specific catalogs may stay inside an agent (`pre-mortem` lenses, `performance-analyst` tooling) until a second consumer needs them.
- Skill names stay as they are (noun phrases, accepted by the guidance); renaming would break installs and evals.
- Every description/prompt change is measured against the previous version with `evals/` (trigger and no-trigger cases).

## Alternatives

| Option | Rejected because |
|---|---|
| "Use PROACTIVELY / MUST" in descriptions | Overtriggering and over-delegation on current models |
| Keep processes in both skill and agent | Drift between copies; tokens loaded twice |
| Rename to gerunds now | Breaks references for no measured gain |

## Consequences

- Trigger quality is measurable; regressions show up before merge.
- Agents depend on their skills' workflow sections staying stable.

## Revisit if

Trigger evals regress after a model change, or Anthropic's guidance changes the description or naming rules.

## Review 2026-10-27

Trigger evals, Sonnet, same graders (skill fired or its preloading agent dispatched):

| Version | Positive cases fired | No-trigger cases clean |
|---|---|---|
| Original descriptions ("Use when…" first) | 42% (2 runs) | 100% |
| What + when rewrite | 58% (2 runs) | 100% |
| + reason to load ("load it before answering so …") | 87% (3 runs) | 100% |

Adding the reason to load turned 0% → 100% for architecture, security and pre-mortem, and lifted QA and refactoring to 100%. `ux-principles` stays unreliable (2 of 6 runs over the last two measurements): Sonnet answers small HTML reviews from memory.

Revisit `ux-principles` triggering with more prompt variants or a dedicated `/ux-review` command.
