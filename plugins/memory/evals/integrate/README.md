# Trial of `mem-integrate`

Stage 3 of `docs/superpowers/plans/2026-11-17-memory-seamless.md`. Question: when `mem-integrate run` joins loose
knowledge notes to the parts of a synthesis, how often does a note land where it does not belong, how often is a
sentence added that its note does not back, and is anything else in the store touched? Everything happens in a store
under `target/` built from `seed.json` (one synthesis of three parts, nine member notes, 33 loose notes); nothing
outside `target/` is read or written.

## Labels (fixed by the commit that added `seed.json`, before any paid run)

| Label | Count | Meaning | Names |
|---|---|---|---|
| `append` | 17 | no sentence states the claim; it belongs in one part | the part (`s:<handle>#<section>`) |
| `belongs-existing-sentence` | 5 | the claim restates one sentence in other words | the part and the sentence number |
| `duplicate-of-existing` | 3 | the claim equals one sentence | the part and the sentence number |
| `on-topic-no-fit` | 4 | same broad subject, belongs in none of the parts | nothing |
| `superseded` | 2 | the note has `superseded_by`: must never be attached | nothing |
| `disputed` | 2 | the note is disputed: must never be attached | nothing |

The `superseded` and `disputed` seeds are never offered to a session: the candidates listing leaves them out. They test that filter only, not a session's judgment. Seeded note handles describe their subject only (a test checks that none hints at its label).

## Kill criteria (the run reports each as pass or fail with its count)

1. Seed size: at least 30 seeded notes and at least 15 labelled `append`.
2. Wrong attachment: any note attached where its label says it must not be (`on-topic-no-fit`, `superseded`,
   `disputed`), attached to a part other than the one its label names, or joined as `append` where the label names a
   sentence (and the reverse). Joined to another sentence of the right part (a `belongs-existing-sentence` or `duplicate-of-existing` note whose
   reference lands on a sentence that does not state the claim): a kill too, and also reported apart. The grader reads
   the references of every unit of every part, so a note cited in a part its label does not allow is wrong whatever
   its `part_of` says.
3. Unbacked sentences: more than 1 appended sentence its note does not back. The harness writes the appended
   sentences with their notes to `audit-prompt-*.md`; a Sonnet session answers `N | backed | reason` lines. That
   session belongs to the paid run and is never started by this script; until it ran the criterion is `pending`:
   `run_trial.py verdict RESULT_JSON --unbacked N [--audit-cost USD]` prints the table and the final verdict from a
   saved result and the audit's answer (no model call).
4. Another note changed: for every note the run did not integrate, any change to its body (compared with its line
   endings as on disk) or to a frontmatter field outside `ALLOWED_OTHER_FIELDS` (`updated`, `part_of_hash`, the
   re-stamp); any knowledge note the run created.
5. Stale to current: a note stale before and current after without a change to its part.
6. Undo: `mem-integrate --undo RUN` must return every file of the store byte for byte (the `.git` folder and the
   `.curation-log` files aside; `.gitignore` is compared).
7. Cost: the run's sessions plus the audit above twice the estimate printed by `--dry-run` (two parts: the
   `mem-integrate` sessions, and the Sonnet audit sized from the audit listing; and their sum). Until the audit cost is
   known (`verdict --audit-cost USD`), the sessions alone are held to twice their own estimate and the criterion stays
   `pending`.

Verdict: `void: <reason>` when a session failed (the failures are listed) or no note was integrated: the run proves
nothing; else `kill: <criteria>` when one failed, `pending: <criteria>` when none failed but one is not known yet, else
`pass`.

## Commands

| Command | What it does | Cost |
|---|---|---|
| `python3 plugins/memory/evals/integrate/run_trial.py --self-check` | the whole flow against a fake `claude` whose answers come from the labels (grading must come out clean), then once per wrong answer (a forbidden label attached; `append` where the label names a sentence; another sentence than the label's; a row for another part): the verdict must kill each | none |
| `python3 plugins/memory/evals/integrate/run_trial.py --dry-run` | builds the seeded store, runs `mem-integrate run --dry-run`, prints syntheses, sessions, input size and the cost estimate in two parts with their sum (Haiku price constants in `run_trial.py`, dated; `shared/models.toml` holds only relative costs) | none |
| `python3 plugins/memory/evals/integrate/run_trial.py --budget USD --claude PATH [--out DIR]` | the paid run: Haiku sessions through `mem-integrate run`, grade, undo and compare; writes the results JSON and the audit prompt under `target/mem-trials/integrate-results/`; removes its work folder and the session folders under the user's Claude projects folder | needs the owner's cap |
| `python3 plugins/memory/evals/integrate/run_trial.py verdict RESULT_JSON --unbacked N [--audit-cost USD]` | the table and the final verdict of a saved result with the audit's answer | none |

Unit tests of the grading: `plugins/memory/engine/tests/integrate/test_trial_grading.py`.
