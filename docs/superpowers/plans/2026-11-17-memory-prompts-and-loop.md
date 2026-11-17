# Memory prompts tuned, then a leaner synthesis loop on Haiku medium: plan

Owner's request, 2026-11-17: before more trials, optimize the prompts of the memory system (agents, skills, hook texts) using the memory and its research; then test synthesis curation with Haiku at medium effort and a loop refined to avoid needless rework. Builds on `2026-11-17-memory-synthesis-haiku.md` (results: the hybrid loop was as accurate but not cheaper, because of two full fix rounds).

**Status:** done 2026-11-17 (preliminary): Haiku medium writer with the lean loop qualifies at about 0.25 USD per synthesis.

## Constraints

- A `description:` change needs a measured eval and its own commit (CLAUDE.md, N6): the audit lists description findings apart; none is applied in this plan without the owner's word.
- The session-start and subagent-start texts were measured by `evals/routing` and `evals/recall`: a change to them reruns those trials (cost stated before running).
- Bodies of skills, agents and trial briefs may ship labeled unmeasured, with a kill criterion.
- Cost of every model run is estimated and said before it starts; results always written to a file.

## Tasks

- [x] Audit by `prompt-engineer` of `plugins/memory/{agents,skills,hooks}`, the session texts in `engine/mem.py` and the trial briefs in `evals/synthesis/`, against the store's syntheses on prompting and agents and this project's lessons. Check: a findings table with line-level rewrites, descriptions and measured texts listed apart.
- [x] Apply the accepted body findings (implementer), one commit; `scripts/validate.py` and `claude plugin validate plugins/memory` pass.
- [x] Loop design, written here before any run: what the checker returns, what the fixer may touch, what the second check covers, when the loop stops; arms and decision rule.
- [x] Trial of the refined loop with Haiku medium against arm S; results in this file.

## Audit, 2026-11-17

`prompt-engineer` returned 14 body rows (table A, applied in this plan), 4 description rows and 5 rows on measured session texts (both left for the owner: each needs its eval). Description rows: a typo in `memory-synthesis`; a "not yet recorded" trigger for `memory-recorder`; cutting the how-clause of `memory`; naming the notes queue in `memory-curator`. Session-text rows: a post-compaction line to record items marked "not yet recorded"; a reason in the pre-compact text; curation and multi-search questions sent to the subagents from the index rules; the subagent-start text not searching for plain reading and returning only what was used; the index head stating why.

## Loop design, fixed before any run

- **Checker:** one line per unsupported claim (`part | first 8 words | kind | note | replacement`), then `PARTS:` and `COUNTS:`; absolutes checked against all the topic's notes.
- **Fixer:** changes only the listed sentences with the replacement verbatim; no replacement means the sentence is deleted; reports the parts and sentences it changed.
- **Second check:** only those parts and sentences. A claim still unsupported is deleted by one delete-only step and listed; no third pass. Exactly one fix round.
- **Arms** (all with the tuned briefs; checker, fixer and judge on Haiku `--effort medium`):
  - **S:** writer Sonnet → check → Sonnet fixer, no second check (today's pipeline).
  - **L:** writer Sonnet → lean loop on Haiku medium.
  - **M:** writer Haiku medium → lean loop on Haiku medium.
- **Runs:** 3 topics (human-memory, time-series-forecasting, llm-evaluation) × 3 arms × 1 run, judge per pipeline. Estimated 7 to 9 USD; the run stops at 10 USD. Preliminary by design (1 run per topic).
- **Decision rule:** among L and M, adopt the cheapest arm whose judged unsupported rate is at most S's plus 2 points (pooled), claims checked at least 80% of S's, coverage at least S's minus 10 points, `mem check` passing, and pipeline cost (judge excluded) at most 80% of S's; if none qualifies, keep S and record the gaps.

## Results

Body findings of the audit applied (`824ef44`); the lean loop built (`c4a7696`, `01ab842`). Two defects found by smoke runs and fixed before the trial: the fixer brief forbade `--shrink`, which `mem synthesis edit` needs for any replaced or deleted sentence, so the Haiku fixer edited nothing; the checker named parts by line range instead of handle.

### Lean loop trial, 2026-11-17 (3 topics × 3 arms × 1 run; checker, lean fixer and judge on Haiku medium)

| Topic | Arm | Judge: unsupported / checked | Arm checker: unsupported / checked | Deleted | Words | Pipeline cost (USD) | Wall (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| human-memory | S | 5 / 6 (judge anomaly) | 3 / 63 | 0 | 2314 | 0.609 | 282 |
| human-memory | L | 3 / 45 | 3 / 60 | 1 | 2402 | 0.562 | 403 |
| human-memory | M | 2 / 74 | 7 / 46 | 4 | 1933 | 0.197 | 514 |
| llm-evaluation | S | 3 / 44 | 4 / 86 | 0 | 2231 | 0.978 | 367 |
| llm-evaluation | L | 3 / 75 | 7 / 90 | 1 | 3179 | 0.846 | 632 |
| llm-evaluation | M | 6 / 92 | 8 / 67 | 4 | 2957 | 0.233 | 585 |
| time-series-forecasting | S | 9 / 111 | 11 / 60 | 0 | 2574 | 0.896 | 558 |
| time-series-forecasting | L | 9 / 108 | 5 / 48 | 1 | 2725 | 0.666 | 561 |
| time-series-forecasting | M | 7 / 56 | 8 / 69 | 1 | 3177 | 0.317 | 638 |

All nine valid, coverage 100%, `mem check` 0, one fix round each, no part changed outside the listed ones. Total cost 6.44 USD (plus about 0.9 USD of smoke runs).

| Arm | Unsupported per 100, 3 topics (rule) | Same without human-memory | Mean pipeline cost |
| --- | --- | --- | --- |
| S: Sonnet writer, Sonnet fixer | 10.6 | 7.7 | 0.83 |
| L: Sonnet writer, lean Haiku loop | 6.6 | 6.6 | 0.69 |
| M: Haiku medium writer, lean Haiku loop | 6.8 | 8.8 | 0.25 |

**Action by the rule written beforehand (preliminary, 1 run per topic):** adopt arm M, the cheapest that qualifies; L fails only on cost (0.69 > 0.8 × 0.83). The judge's row for human-memory S is an anomaly (6 claims checked in a 2,314-word document); without that topic M still qualifies (8.8 ≤ 7.7 + 2; cost 0.28 against 0.94).

Limits: one run per topic and three topics; the judge is Haiku at medium effort and its counts are noisy (claims checked for one document ranged 6 to 111 across rows), and it shares a model family with arm M's writer; the earlier Haiku writer at default effort with the untuned briefs scored 8.7 against 3.2 on one pair, so the gain comes from the tuned briefs, the effort level or both — not separated here. Kill criterion: if a fact-check of syntheses written this way in real use finds over 10 unsupported claims per 100, return the writer to Sonnet.

Not done: making this pipeline a command or script the curation uses (the owner's open item 4); the description and session-text findings of the audit (each needs its eval).

### After the trial (owner, 2026-11-17)

- The lean loop's Haiku steps (writer, checker, fixer, judge) are raised from medium to high effort without a new measurement: the owner reads the gain as coming mostly from the tuned briefs and takes high effort as the middle point. Unmeasured; the kill criterion above applies.
- The trial script stays as a test to run on demand (it costs model usage), not as part of any routine check.
