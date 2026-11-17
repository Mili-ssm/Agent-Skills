# Memory prompts tuned, then a leaner synthesis loop on Haiku medium: plan

Owner's request, 2026-11-17: before more trials, optimize the prompts of the memory system (agents, skills, hook texts) using the memory and its research; then test synthesis curation with Haiku at medium effort and a loop refined to avoid needless rework. Builds on `2026-11-17-memory-synthesis-haiku.md` (results: the hybrid loop was as accurate but not cheaper, because of two full fix rounds).

**Status:** in progress.

## Constraints

- A `description:` change needs a measured eval and its own commit (CLAUDE.md, N6): the audit lists description findings apart; none is applied in this plan without the owner's word.
- The session-start and subagent-start texts were measured by `evals/routing` and `evals/recall`: a change to them reruns those trials (cost stated before running).
- Bodies of skills, agents and trial briefs may ship labeled unmeasured, with a kill criterion.
- Cost of every model run is estimated and said before it starts; results always written to a file.

## Tasks

- [ ] Audit by `prompt-engineer` of `plugins/memory/{agents,skills,hooks}`, the session texts in `engine/mem.py` and the trial briefs in `evals/synthesis/`, against the store's syntheses on prompting and agents and this project's lessons. Check: a findings table with line-level rewrites, descriptions and measured texts listed apart.
- [ ] Apply the accepted body findings (implementer), one commit; `scripts/validate.py` and `claude plugin validate plugins/memory` pass.
- [ ] Loop design, written here before any run: what the checker returns, what the fixer may touch, what the second check covers, when the loop stops; arms and decision rule.
- [ ] Trial of the refined loop with Haiku medium against arm S; results in this file.

## Results

Pending.
