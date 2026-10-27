---
name: web-research
description: Research protocol that offloads web searching and reading to the cheap researcher subagent (Haiku) and returns cited lists, comparisons and conclusions on concrete questions - official docs, best practices, library options, version facts. Use when a task needs current external information, official documentation or community practice; load it before searching so reading stays out of the main context and every claim comes back sourced.
---

# Web Research

The main model reasons; the `researcher` subagent (Haiku) searches and reads. Raw pages never enter the main context, only distilled, cited findings.

## Workflow

1. **Frame** each question so it has a checkable answer: "Which X does official doc Y recommend for Z, as of version V?" beats "research X".
2. **Split** broad topics into independent questions (≤ 5) and dispatch one `researcher` per question **in parallel**.
3. **Brief** each researcher with: question, why it matters (decision it feeds), preferred sources, output shape (list, comparison table, yes/no + evidence), max length.
4. **Reason** in the main thread over the returned findings: reconcile conflicts, decide, cite.
5. **Re-dispatch** only for gaps or conflicts the findings name; never re-read pages yourself unless one fact is decisive.

## Source hierarchy (researcher follows it)

| Rank | Source | Use for |
|---|---|---|
| 1 | Official docs, specs, RFCs, changelogs, release notes | Facts, APIs, versions, recommended practice |
| 2 | Maintainer posts, source code, issue trackers | Behavior the docs miss, known bugs |
| 3 | Peer-reviewed papers, standards bodies (OWASP, W3C, NIST) | Evidence and norms |
| 4 | Reputable engineering blogs with data or reproducible tests | Trade-offs in practice |
| 5 | Forums, aggregators, SEO listicles | Leads only; confirm in ranks 1–3 |

## Output contract

```markdown
## Answer
<1–3 lines>
## Findings
| # | Claim | Source (URL) | Rank | Date/version | Confidence (high/medium/low) |
## Conflicts and gaps
## Sources
```

Confidence: high = rank 1–2 source states it directly; medium = rank 3–4 or inferred from rank 1; low = single rank-5 source or undated.
