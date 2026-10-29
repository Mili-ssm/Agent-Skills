---
name: docs-principles
description: Checklists for accurate, dense repository documentation and LLM-facing files - Diátaxis, density checklist, CLAUDE.md/AGENTS.md rules and Anthropic skill and subagent authoring guidance. Use when writing, tightening, reviewing or updating a README, docs, ADRs, docstrings, CLAUDE.md, AGENTS.md, skills or agent prompts, including requests like "make this shorter" or "this feels bloated" (not for general prose such as emails; the skill-authoring process belongs to Superpowers writing-skills); load it before editing so cuts follow the density checklist and keep rationale and gotchas.
---

# Documentation Principles

**Core rule:** every sentence carries information that is not cheaper to get elsewhere (code, types, `--help`, git history). Bloat costs reader attention and LLM tokens, and measurably lowers agent task success.

## Principles

| Principle | Meaning |
|---|---|
| Why > what | Code shows what; docs keep intent, constraints, trade-offs |
| Single source of truth | State a fact once and link to it; copies drift |
| Diátaxis | Tutorial, how-to, reference and explanation stay separate |
| Minimal context files | CLAUDE.md/AGENTS.md hold only what agents cannot discover |
| LLM-aligned prompts | Skills, agents and prompts follow Anthropic authoring guidance |

## References

| Open when | Reference |
|---|---|
| Cutting or tightening any text (workflow step 4) | [density-checklist.md](references/density-checklist.md) |
| Sorting sections by reader need or splitting a mixed section (step 2) | [diataxis.md](references/diataxis.md) |
| Writing or auditing CLAUDE.md or AGENTS.md | [agent-context-files.md](references/agent-context-files.md) |
| Writing or reviewing a skill, agent prompt or description (wording, examples, evals) | [prompt-authoring.md](references/prompt-authoring.md) |

## Writing rules

- Tables for comparisons and mappings, lists for sequences, prose for reasoning.
- One term per concept; synonyms read as different concepts.
- Prefer one concrete example to an abstract explanation.
- Date time-sensitive facts ("as of 2026-10") so readers can judge staleness.
- Decisions go to ADRs (`decision-records`).
- Apply the density checklist to every paragraph.

## Compression workflow

Copy and tick:

```
- [ ] 1 Inventory: files, lines, ~tokens (chars/4)
- [ ] 2 Classify sections by Diátaxis type; flag mixed ones
- [ ] 3 Verify each claim against code; mark stale/false/unverified
- [ ] 4 Cut with the density checklist
- [ ] 5 Prove nothing lost: each removed fact → where it still lives, or why it was worthless
- [ ] 6 Measure before/after; repeat 3–5 until no item fires
```

## Review output

```markdown
| File:line | Issue (stale · false · duplicate · bloat · mixed-type · missing-why · unverified) | Fix |
Metrics: N lines / ~T tokens → M / ~U (−X%)
Removed facts: fact → still at / reason dropped
```
