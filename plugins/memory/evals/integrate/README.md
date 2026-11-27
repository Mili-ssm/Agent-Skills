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

## Kill criteria (the run reports each as pass or fail with its count)

1. Seed size: at least 30 seeded notes and at least 15 labelled `append`.
2. Wrong attachment: any note attached where its label says it must not be (`on-topic-no-fit`, `superseded`,
   `disputed`), attached to a part other than the one its label names, or joined as `append` where the label names a
   sentence (and the reverse). Joined to another sentence of the right part: counted and reported apart, not a kill.
3. Unbacked sentences: more than 1 appended sentence its note does not back. The harness writes the appended
   sentences with their notes to `audit-prompt-*.md`; a Sonnet session answers `N | backed | reason` lines. That
   session belongs to the paid run and is never started by this script; until it ran the criterion is `pending`.
4. Another note changed: for every note the run did not integrate, any change to its body or to a frontmatter field
   outside `ALLOWED_OTHER_FIELDS` (`updated`, `part_of_hash`, the re-stamp).
5. Stale to current: a note stale before and current after without a change to its part.
6. Undo: `mem-integrate --undo RUN` must return every file of the store byte for byte (logs aside).
7. Cost: above twice the estimate printed by `--dry-run`.

Verdict: `kill: <criteria>` when one failed, `pending: <criteria>` when none failed but one is not known yet, else `pass`.

## Commands

| Command | What it does | Cost |
|---|---|---|
| `python3 plugins/memory/evals/integrate/run_trial.py --self-check` | the whole flow against a fake `claude` whose answers come from the labels (grading must come out clean), then once more with one wrong answer (the grader must catch it) | none |
| `python3 plugins/memory/evals/integrate/run_trial.py --dry-run` | builds the seeded store, runs `mem-integrate run --dry-run`, prints syntheses, sessions, input size and the cost estimate (Haiku price constants in `run_trial.py`, dated; `shared/models.toml` holds only relative costs) | none |
| `python3 plugins/memory/evals/integrate/run_trial.py --budget USD --claude PATH [--out DIR]` | the paid run: Haiku sessions through `mem-integrate run`, grade, undo and compare; writes the results JSON and the audit prompt under `target/integrate-results/` | needs the owner's cap |

Unit tests of the grading: `plugins/memory/engine/tests/integrate/test_trial_grading.py`.
