# Recall through a cheaper subagent: experiment plan

**Goal:** Find out whether the `memory-researcher` subagent answers questions from the memory as well on Haiku as on Sonnet (its model today), and at what cost, as the first step of the owner's open item 7: memory work by secondary models of predictable cost that return only what matters to the main model.

**Status:** planned 2026-11-17; not started.

## Decisions already taken (owner, 2026-11-17)

| Decision | Reason |
| --- | --- |
| Memory interactions go preferably through secondary, cheaper models; the main model gets the conclusion; main and secondary agents keep direct `mem search` for plain queries (owner: a reference, not literal) | With an expensive main model, recall cost grows fast |
| Cost of agent work is planned and stated before it runs | The owner's usage limits (30% of a 5-hour window in one curation) |

## Design, fixed before any run

- Store: a fresh copy of the owner's default store under the ignored `target/` folder for every run (the trial fixture), passed to the session through `pluginConfigs` (as recall/run_trials.py does) so the session-start hook does not create an empty default store; a fresh scratch project per run too; the real store is never touched. The smoke run asserts that the researcher's `mem search` returns handles from the copy.
- Questions: 10 in English: 8 whose answer needs more than one note (a synthesis part or several notes: figures, conditions, disputes), each with 2–3 expected facts verified by reading the notes; 2 the memory does not cover (expected: says so). Each answerable question needs facts from 2 or more notes or parts (a question one part answers cannot separate the arms), and has one distractor fact from a neighbouring note that must not appear. Written by a worker that reads the store copy; checked by the controller on a sample.
- Arms: researcher on Sonnet (as shipped) against researcher on Haiku (a plugin copy whose `memory-researcher` has `model: haiku`). The main session runs Haiku in both arms and only relays: "Ask the memory-researcher subagent: <question>. Reply with its answer verbatim." Tools given: `Agent` only for the main session's work (no `Bash(mem *)`, no WebSearch/WebFetch at any level), so the researcher must use the memory and cannot record web findings that leak into later runs. A run is valid only with an `Agent` call whose `subagent_type` matches `(memory:)?memory-researcher` and no top-level `mem` call; the researcher's answer is limited to 250 words.
- Measures per run: expected facts present and the distractor absent (substrings), "not covered" for the two; cost per model from the `result` event's `modelUsage` (the arm's researcher model must appear with a nonzero cost, else the run is invalid); the length of the answer returned to the main session.
- Runs: 10 questions × 2 arms × 3 runs = 60 headless sessions. Estimated cost 3 to 9 USD.
- Decision rule, written before the runs: adopt Haiku for `memory-researcher` when Haiku's facts found are at least Sonnet's minus 2 (of about 50 expected facts over 20 runs per arm) and both "not covered" questions are answered as not covered in at least 3 of 4 runs, and its median cost is at most half of Sonnet's; otherwise keep Sonnet and record the gap. The result is inconclusive (no change) when runs of one arm differ by more than 2 facts on the same question set.

## Tasks

- [ ] Question set with verified expected facts (a worker reads the store copy; the controller checks 3 questions against their notes). Check: 10 questions, each fact quoted from a note path.
- [ ] Trial script `plugins/memory/evals/researcher/run_trials.py` on the `trial_env` fixture, with `--self-check` (no model) and the two arms. Check: self-check passes; one smoke run per arm parses facts and cost.
- [ ] Run the 40 sessions in the background and write `## Results` with the table and the action the rule gives. Check: every run valid or rerun.
- [ ] If the rule says adopt: change `model:` in `plugins/memory/agents/memory-researcher.md` and its description's "(Sonnet)" (a description change: the eval protocol of CLAUDE.md applies), else record why not.

## Pre-mortem of 2026-11-17 and what changed

| Risk | Change |
| --- | --- |
| The main Haiku session answers by itself | Main gets `Agent` only; a run counts only with a researcher dispatch and no top-level `mem` |
| Cost of the subagent not visible, model not shown | Cost per model from `modelUsage`; the arm's model must appear |
| The researcher reaches an empty default store | Store copy through `pluginConfigs`; smoke run asserts handles from the copy |
| Web findings recorded in one run leak into later runs | Fresh store copy per run; no web tools |
| Long answers game substring grading | 250-word answers; one distractor fact per question |
| Noise above the margin | Facts from 2+ notes per question; 3 runs; inconclusive when an arm varies by more than 2 facts |

## Results

Pending.
