---
name: docs-principles
description: Use when writing, reviewing, compressing or updating documentation (README, docs/, docstrings, CLAUDE.md, AGENTS.md, skills) - principles for accurate, concise, semantically dense docs that serve humans and LLMs without bloat.
---

# Documentation Principles

**Core rule:** every sentence must carry information that is not cheaper to obtain elsewhere (code, types, `--help`, git history). Bloat is a defect: it costs reader attention and LLM tokens, and measurably lowers agent task success.

## Principles

| Principle | Meaning |
|---|---|
| Why > what | Code shows what; docs keep intent, constraints, trade-offs |
| Single source of truth | State a fact once; link elsewhere. Duplicates drift |
| Diátaxis | Separate tutorial / how-to / reference / explanation ([detail](references/diataxis.md)) |
| Inverted pyramid | Conclusion and most-used info first; detail after |
| Docs as code | Versioned with code, reviewed in PRs, examples executed in CI where possible |
| Minimal context files | CLAUDE.md/AGENTS.md hold only what agents cannot discover ([detail](references/agent-context-files.md)) |
| Progressive disclosure | Short index → linked detail loaded on demand |
| Verifiable | Commands, paths, versions are exact and tested |

## Writing rules

- Tables for comparisons, options, mappings; lists for sequences; prose only for reasoning.
- Exact terms; one term per concept (no synonyms for variety).
- Delete: marketing adjectives, hedging, restated headings, "this section describes", obvious code narration.
- Prefer concrete example over abstract explanation; one good example beats three.
- Dates on anything time-sensitive ("current as of YYYY-MM-DD").
- Decisions go to ADRs (`decision-records` skill), not scattered prose.

## Compression process

1. **Inventory** files, sizes (lines, approx tokens = chars/4).
2. **Classify** each section by Diátaxis type; flag mixed sections.
3. **Verify** every claim against code; mark stale/false.
4. **Cut** with [the density checklist](references/density-checklist.md).
5. **Check nothing lost**: list each removed fact and where it still lives (code, other doc) or why it was worthless.
6. **Measure**: before/after lines + tokens.

## Output when reviewing

```markdown
| File:line | Issue (stale/duplicate/bloat/mixed/missing-why/unverified) | Fix |
Metrics: before N lines / ~T tokens → after M / ~U (−X%)
Removed facts: fact → still available at / reason dropped
```
