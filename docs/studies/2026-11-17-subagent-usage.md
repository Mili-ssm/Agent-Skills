# Subagent usage study (read-only)

**Window**: calls dated 2026-11-01 to 2026-11-17 (files modified in the last 14 days). **38 session files, 1,919 unique Agent calls** (deduped by `id`), 6 projects (P1, P2, P3, P4, P6, P7; P6 dominates). 53% ran in background.

## 1. Calls per type

| Type | Calls | Share |
|---|---|---|
| skeptical-reviewer | 615 | 32% |
| implementer | 466 | 24% |
| **general-purpose** | **404** | **21%** |
| fact-checker | 75 | 4% |
| pre-mortem | 73 | 4% |
| researcher | 70 | 4% |
| check-runner | 49 | 3% |
| ui-verifier | 43 | 2% |
| Explore | 38 | 2% |
| performance-analyst / prompt-engineer | 18 / 18 | 1% each |
| summarizer | 12 | 0.6% |
| doc-curator 9, ux-reviewer 6, architect 6, 4 each consistency-auditor/fixer/security-reviewer, qa-engineer 3, claude-code-guide 2 | 38 | 2% |

Catch-all `claude`: 0. Memory-plugin agents: 0.

| ISO week | Calls | general-purpose | skeptical-reviewer | implementer |
|---|---|---|---|---|
| 45 | 730 | 153 (21%) | 295 | 181 |
| 46 | 859 | 217 (25%) | 242 | 163 |
| 47 (partial) | 326 | 34 (10%) | 78 | 120 |

## 2. General-purpose clusters (404 calls; 341 in P6; 370 Sonnet, 24 Haiku, 9 Opus)



| Cluster | Calls | Model | Example descriptions (generic) | Existing agent that could take it |
|---|---|---|---|---|
| Write notes/documents from sources, in numbered "waves" with a shared brief | 131 | Sonnet | "Wave N: topic"; "Writer C: topic" | none fits (implementer is code-only, bounded task) |
| Fact-check notes against cited sources | 101 | Sonnet | "Fact-check wave N area B" | `fact-checker` (read-only, verdict per claim): fits; 75 named calls already |
| Apply accepted review findings to notes | 27 | Sonnet | "Apply fact-check fixes, area F" | `implementer` or `doc-curator` (apply mode) |
| Plan-task review (spec + quality) | 43 | Sonnet (4 Opus) | "Review Task N"; "Scoped re-review" | `skeptical-reviewer` (Haiku; the plan loop names it) |
| Synthesis documents per subject | 31 | Sonnet | "Synthesis: subject" | none fits (same as writing); `memory-recorder` is closest in spirit |
| Retrieval-eval runs (answer questions with fixed commands; judges) | 37 | Haiku 20, Sonnet 16 | "Lookup run X"; "Agent run baseline" | none: deliberate test subjects, need a generic agent |
| Literature/paper search, source sweeps | ~9 | Sonnet | "Paper search: field"; "Sweep: topic" | `researcher` (Haiku) |
| Relevance judging (grades for an experiment) | ~6 | Sonnet | "Judge relevance q01-q08" | none (judgment-by-rubric worker) |
| Read-only code study / assessment | ~6 | Sonnet | "Map X code" | `Explore`, `architect` |
| Defect root-cause and fix | 7 | Sonnet 4, Opus 3 | "Debug issue N" | none (implementer is plan-bound; fixer is mechanical) |

## 3. Rare and off-scope named agents

| Agent | Calls | Observation |
|---|---|---|
| security-reviewer 4, qa-engineer 3, consistency-auditor 4, fixer 4, architect 6, ux-reviewer 6, doc-curator 9 | 36 total | Rare. Specialists are used for one-off assessments, as designed. |
| memory-curator / recorder / researcher | 0 | Not yet released or not triggered in the window. |
| skeptical-reviewer | 615 | Mostly plan-loop task reviews, in scope; no drift seen. |

## 4. Model overrides

`model` set in 433 of 1,919 calls (23%): sonnet 395, haiku 27, opus 11. In general-purpose calls it was set in 403 of 404 (Sonnet 370), i.e. the owner's main model routes the catch-all to Sonnet by explicit choice; named agents rarely override (their files fix the model).

## 5. Proposals (evidence = calls)

| # | Proposal | Evidence | Type |
|---|---|---|---|
| a1 | Widen `fact-checker` description to cover batch checking of notes by "area/wave" and to say it also applies accepted corrections when asked | 101 gp + 27 apply vs 75 named | widen |
| a2 | Make plan-task review explicitly route to `skeptical-reviewer`, or admit a Sonnet-tier review mode, since 43 gp reviews (39 Sonnet) bypassed it | 43 | widen/clarify |
| b1 | **`note-writer`** (Sonnet): writes literature notes or synthesis documents from named sources under a shared brief, owns listed files, cites each claim | 131 + 31 = 162 | new |
| b2 | **`defect-investigator`** (Sonnet, Opus for hard cases): root-causes one defect then applies the smallest fix, following systematic-debugging | 7 (below the 5+ bar only marginally; Opus use) | new, weak |
| b3 | **`rubric-judge`** (Sonnet): grades items against a fixed rubric for an experiment | ~6 | new, weak |
| c1 | `fixer` (4 calls) and `consistency-auditor` (4) look near-idle; `fixer` overlaps `implementer` | 4 each | possibly redundant |

## Limits

- One user, 17 days, one dominant project (P6 = 84% of general-purpose calls): patterns reflect a single hub workflow, not general usage.
- Clusters come from description keywords, not outcomes; the ~26 "other" rows were hand-read from 80 characters of prompt only.
- Whether a general-purpose call was a deliberate eval subject (37) or a routing miss cannot be told from the transcript.
- Memory agents had no usage to evaluate.
