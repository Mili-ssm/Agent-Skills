---
name: docs-principles
description: Checklists for accurate, dense repository documentation - Diátaxis, a density checklist and a compression workflow with before/after metrics. Use when writing, tightening, reviewing or updating a README, docs, ADRs, docstrings or a CLAUDE.md/AGENTS.md, including requests like "make this shorter", "tighten this section" or "this feels bloated" (not for general prose such as emails; how wording steers an LLM - prompts, skills, agents - belongs to `prompt-engineering`); load it before editing so cuts follow the density checklist and keep rationale and gotchas.
---

# Documentation Principles

**Core rule:** every sentence carries information that is not cheaper to get elsewhere (code, types, `--help`, git history). Bloat costs reader attention and LLM tokens, and measurably lowers agent task success.

## Principles

| Principle | Meaning |
|---|---|
| Why > what | Code shows what; docs keep intent, constraints, trade-offs |
| Single source of truth | State a fact once and link to it; copies drift |
| Diátaxis | Tutorial, how-to, reference and explanation stay separate |
| LLM-facing text | Wording of prompts, skills and agents follows `prompt-engineering`; cuts to CLAUDE.md/AGENTS.md keep every line that changes behavior |

## References

| Open when | Reference |
|---|---|
| Cutting or tightening any text (workflow step 4) | [density-checklist.md](references/density-checklist.md) |
| Sorting sections by reader need or splitting a mixed section (step 2) | [diataxis.md](references/diataxis.md) |

## Writing rules

- Tables for comparisons and mappings, lists for sequences, prose for reasoning.
- One term per concept; synonyms read as different concepts.
- Prefer one concrete example to an abstract explanation.
- Date time-sensitive facts ("as of 2026-10") so readers can judge staleness.
- Decisions go to ADRs (`decision-records`).
- Open [density-checklist.md](references/density-checklist.md) and apply it to every paragraph you write or cut.

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

## Review output (default; a format in the caller's task or agent definition replaces it)

```markdown
| File:line | Issue (stale · false · duplicate · bloat · mixed-type · missing-why · unverified) | Fix |
Metrics: N lines / ~T tokens → M / ~U (−X%)
Removed facts: fact → still at / reason dropped
```
