# Recall through a cheaper subagent: experiment plan

**Goal:** Find out whether the `memory-researcher` subagent answers questions from the memory as well on Haiku as on Sonnet (its model today), and at what cost, as the first step of the owner's open item 7: memory work by secondary models of predictable cost that return only what matters to the main model.

**Status:** planned 2026-11-17; not started.

## Decisions already taken (owner, 2026-11-17)

| Decision | Reason |
| --- | --- |
| Memory interactions go preferably through secondary, cheaper models; the main model gets the conclusion; main and secondary agents keep direct `mem search` for plain queries (owner: a reference, not literal) | With an expensive main model, recall cost grows fast |
| Cost of agent work is planned and stated before it runs | The owner's usage limits (30% of a 5-hour window in one curation) |

## Design, fixed before any run

- Store: a read-only copy of the owner's default store under the ignored `target/` folder (the trial fixture of PR #120); the real store is never touched.
- Questions: 10 in English: 8 whose answer needs more than one note (a synthesis part or several notes: figures, conditions, disputes), each with 2–3 expected facts verified by reading the notes; 2 the memory does not cover (expected: says so). Written by a worker that reads the store copy; checked by the controller on a sample.
- Arms: researcher on Sonnet (as shipped) against researcher on Haiku (a plugin copy whose `memory-researcher` has `model: haiku`). The main session runs Haiku in both arms and only relays: "Ask the memory-researcher subagent: <question>. Reply with its answer verbatim."
- Measures per run: expected facts present (graded by substring, plus "not covered" for the two), the run's total cost from the final `result` event (the main model is the same in both arms, so the difference is the researcher), the length of the answer returned to the main session.
- Runs: 10 questions × 2 arms × 2 runs = 40 headless sessions. Estimated cost 2 to 6 USD.
- Decision rule, written before the runs: adopt Haiku for `memory-researcher` when Haiku's facts found are at least Sonnet's minus 2 (of about 50 expected facts over 20 runs per arm) and both "not covered" questions are answered as not covered in at least 3 of 4 runs, and its median cost is at most half of Sonnet's; otherwise keep Sonnet and record the gap.

## Tasks

- [ ] Question set with verified expected facts (a worker reads the store copy; the controller checks 3 questions against their notes). Check: 10 questions, each fact quoted from a note path.
- [ ] Trial script `plugins/memory/evals/researcher/run_trials.py` on the `trial_env` fixture, with `--self-check` (no model) and the two arms. Check: self-check passes; one smoke run per arm parses facts and cost.
- [ ] Run the 40 sessions in the background and write `## Results` with the table and the action the rule gives. Check: every run valid or rerun.
- [ ] If the rule says adopt: change `model:` in `plugins/memory/agents/memory-researcher.md` and its description's "(Sonnet)" (a description change: the eval protocol of CLAUDE.md applies), else record why not.

## Results

Pending.
