---
name: docs-principles
description: Checklists for accurate, dense documentation and LLM-facing prompts - Diataxis, density checklist, CLAUDE.md/AGENTS.md rules and Anthropic skill and subagent authoring guidance. Use when writing, tightening, reviewing or updating a README, docs, docstrings, CLAUDE.md, AGENTS.md, skills or agent prompts, including requests like "make this shorter" or "this feels bloated"; load it before editing so cuts follow the density checklist and keep rationale and gotchas.
---

# Documentation Principles

**Core rule:** every sentence carries information that is not cheaper to get elsewhere (code, types, `--help`, git history). Bloat costs reader attention and LLM tokens, and measurably lowers agent task success.

## Principles

| Principle | Meaning |
|---|---|
| Why > what | Code shows what; docs keep intent, constraints, trade-offs |
| Single source of truth | State a fact once and link to it; copies drift |
| Diátaxis | Tutorial, how-to, reference and explanation stay separate ([detail](references/diataxis.md)) |
| BLUF / inverted pyramid | Conclusion and most-used facts first |
| Every page is page one (Baker) | Readers land from search; each page states its context and links onward |
| Minimalism (Carroll) | Support the reader's real task; cut what they would skip |
| Docs as code | Versioned and reviewed with code; examples run in CI where possible |
| Minimal context files | CLAUDE.md/AGENTS.md hold only what agents cannot discover ([detail](references/agent-context-files.md)) |
| LLM-aligned prompts | Skills, agents and prompts follow Anthropic authoring guidance ([detail](references/prompt-authoring.md)) |
| Progressive disclosure | Short index, detail one link away |
| Verifiable | Commands, paths, versions exact and tested; time-sensitive facts dated |

## Writing rules

- Tables for comparisons and mappings, lists for sequences, prose for reasoning.
- One term per concept; synonyms read as different concepts.
- Prefer one concrete example to an abstract explanation.
- Decisions go to ADRs (`decision-records`).
- Apply the [density checklist](references/density-checklist.md) to every paragraph.

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
