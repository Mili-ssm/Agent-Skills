# 0007 Anthropic authoring conventions, measured by evals

Status: accepted · Date: 2026-10-27 · Amended by 0010, 0012, 0014

## Context

Baseline trigger evals (`claude plugin eval`, 13 cases × 2 runs, Sonnet) fired the right skill/agent in 42% of runs; knowledge skills (QA, UX, security, architecture, docs, observability) almost never fired. Descriptions started with "Use when…" and never said what the skill does. A `doc-curator` + `consistency-auditor` self-audit found negative-only rules without reasons, inconsistent terms ("QA" for quality attributes), processes duplicated between skills and agents, derivable catalogs, and "read-only" agents enforced only by prompt text.

## Decision

- Follow Anthropic's skill-authoring and prompting guidance, digested in `skills/docs-principles/references/prompt-authoring.md` (moved to the `prompt-engineering` skill, ADR 0014); `scripts/validate.py` enforces the checkable parts (what + when, third person, ≤ 1024 chars, name format, `## Contents` above 100 lines).
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

Follow-up (owner): auto-triggering is a bonus, not a requirement, so explicit commands (`commands/*.md`, `disable-model-invocation: true`) supplement every agent plus `ux-design`. `ux-principles` is meant for planning and designing UIs with Playwright verification, not snippet review; its eval now uses a design prompt and fires 3/3.

## Review 2026-10-29

A prompt and configuration review (bounded reports, write gates, sibling boundaries, role labels in preloaded skills; ADR 0012) was measured with a stricter suite: five near-miss no-trigger cases whose grader names every skill and agent, skill-only graders for `change-impact`, `intent-elicitation` and `ux-principles`, and a `performance-analyst` case. Baseline: the `main` plugin with the same suite. Both sides ran concurrently with the same flags: Sonnet main, 3 runs per case, no Superpowers. Cases that dropped were rerun at 6 runs per side.

| Suite | `main` | This change |
|---|---|---|
| Trigger, 16 cases × 3 runs | 39/48 (81%) | 41/48 (85%) |
| No-trigger, 5 near-misses × 3 runs | 15/15 | 15/15 |
| Rerun × 6: `pre-mortem` · `ux-principles` · `architecture-principles` | 1/6 · 6/6 · 2/6 | 1/6 · 6/6 · 1/6 |

- No case dropped by 2 or more of 6, the threshold set before measuring. `pre-mortem` and `architecture-principles` fire rarely on both versions, because Sonnet critiques the plan or answers the restructuring question inline; their commands and the owner's offload row stay the entry points.
- `performance-analyst` fired 0/3 on both: with no codebase in the prompt, Sonnet answers with advice. `/agent-skills:perf-review` is the entry point.
- The near-misses never fired on `main` either, so the new boundary clauses show no measurable effect on these prompts.
- Vocabulary: a finding's basis is `evidenced | inferred`; a plan assumption's status stays `verified | unverified`.

## Review 2026-10-30

- Amended by ADR 0010 (the six workers, and only they, say "Use proactively") and ADR 0012 (workers have no command each; `/agent-skills:offload` forces them).
- The digested guidance now lives in `plugins/agent-skills/skills/prompt-engineering/` (`references/prompt-rules.md`, `references/skills-and-agents.md`; ADR 0014).
- Prompt review 2026-10-30 (three `prompt-engineer` passes, stress-tested by `pre-mortem`): body changes to skills, commands, references and three workers, plus one commit per description change (`researcher`, `Explore`, `fixer`, `intent-elicitation`, `release-hygiene`, `api-design`, `change-impact`) so each can be reverted alone. **Unmeasured**: before merging, run the trigger, no-trigger and offload suites against `main`. Kill criteria: `neg-live-bug` fires `api-design` → revert it; `neg-small-flag` fires `change-impact` → revert it; `trigger/feature-briefing` drops ≥ 2 of 6 while `change-impact` fires → revert `change-impact`; `implementer-with-policy` or `ui-verifier-with-policy` returns work left over or misses defects → revert that worker's round budget; any trigger case drops ≥ 2 of 6 → revert the description named for it.
