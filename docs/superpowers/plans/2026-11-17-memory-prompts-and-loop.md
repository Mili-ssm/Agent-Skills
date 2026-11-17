# Memory prompts tuned, then a leaner synthesis loop on Haiku medium: plan

Owner's request, 2026-11-17: before more trials, optimize the prompts of the memory system (agents, skills, hook texts) using the memory and its research; then test synthesis curation with Haiku at medium effort and a loop refined to avoid needless rework. Builds on `2026-11-17-memory-synthesis-haiku.md` (results: the hybrid loop was as accurate but not cheaper, because of two full fix rounds).

**Status:** in progress.

## Constraints

- A `description:` change needs a measured eval and its own commit (CLAUDE.md, N6): the audit lists description findings apart; none is applied in this plan without the owner's word.
- The session-start and subagent-start texts were measured by `evals/routing` and `evals/recall`: a change to them reruns those trials (cost stated before running).
- Bodies of skills, agents and trial briefs may ship labeled unmeasured, with a kill criterion.
- Cost of every model run is estimated and said before it starts; results always written to a file.

## Tasks

- [x] Audit by `prompt-engineer` of `plugins/memory/{agents,skills,hooks}`, the session texts in `engine/mem.py` and the trial briefs in `evals/synthesis/`, against the store's syntheses on prompting and agents and this project's lessons. Check: a findings table with line-level rewrites, descriptions and measured texts listed apart.
- [ ] Apply the accepted body findings (implementer), one commit; `scripts/validate.py` and `claude plugin validate plugins/memory` pass.
- [x] Loop design, written here before any run: what the checker returns, what the fixer may touch, what the second check covers, when the loop stops; arms and decision rule.
- [ ] Trial of the refined loop with Haiku medium against arm S; results in this file.

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

Pending.
