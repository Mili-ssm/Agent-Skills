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
   sentences with their notes to `audit-prompt-*.md`; a Sonnet session answers one line per sentence, `N | backed |
   reason` or `N | not backed | reason`. That session belongs to the paid run and is never started by this script
   (the paid run only writes the prompt): the owner runs it, saves its reply to a file and runs
   `run_trial.py verdict RESULT_JSON --audit-reply FILE [--audit-cost USD]`, which prints the table and the final
   verdict (no model call). The reply is parsed strictly: exactly one line for every appended sentence, numbers
   matching, verdict `backed` or `not backed`; anything else is a usage error (exit 2) naming the sentence or line
   at fault, with no verdict. The unbacked count is the number of `not backed` lines. Until the reply is given the
   criterion is `pending`.
4. Another note changed: for every note the run did not integrate, any change to its body (compared with its line
   endings as on disk) or to a frontmatter field outside `ALLOWED_OTHER_FIELDS` (`updated`, `part_of_hash`, the
   re-stamp); any knowledge note the run created.
5. Stale to current: a note stale before and current after without a change to its part.
6. Undo: `mem-integrate --undo RUN` must return every file of the store byte for byte (the `.git` folder and the
   `.curation-log` files aside; `.gitignore` is compared).
7. Cost, two bars, both must hold: the sessions' cost within twice the sessions estimate, and, once the audit cost is
   known (`verdict --audit-cost USD`), the sessions plus the audit within twice the total estimate printed by
   `--dry-run` (two parts and their sum). The sessions bar is checked at once: a sessions cost above twice its estimate
   fails the criterion immediately and does not stay pending, and a cheap audit cannot mask it. With the sessions
   inside their bar and no audit cost yet, the criterion is `pending`. The audit estimate is one request: the audit
   prompt (about 4 characters a token) plus a fixed overhead for the system prompt in, one short line per appended
   sentence out, at the Haiku constants of `run_trial.py` times the Sonnet/Haiku relative cost of `shared/models.toml`.

Verdict: `void: <reason>` when a session failed (the failures are listed) or no note was integrated: the run proves
nothing; else `kill: <criteria>` when one failed, `pending: <criteria>` when none failed but one is not known yet, else
`pass`.

## Commands

| Command | What it does | Cost |
|---|---|---|
| `python3 plugins/memory/evals/integrate/run_trial.py --self-check` | the whole flow against a fake `claude` whose answers come from the labels (grading must come out clean), then once per wrong answer (a forbidden label attached; `append` where the label names a sentence; another sentence than the label's; a row for another part): the verdict must kill each | none |
| `python3 plugins/memory/evals/integrate/run_trial.py --dry-run` | builds the seeded store, runs `mem-integrate run --dry-run`, prints syntheses, sessions, input size and the cost estimate in two parts with their sum (Haiku price constants in `run_trial.py`, dated; `shared/models.toml` holds only relative costs) | none |
| `python3 plugins/memory/evals/integrate/run_trial.py --budget USD --claude PATH [--out DIR]` | the paid run: Haiku sessions through `mem-integrate run`, grade, undo and compare; writes the results JSON and the audit prompt under `target/mem-trials/integrate-results/`; if the run raises after sessions spent money, it saves the run record (cost, failures, output, exception text) as `integrate-failed-*.json` there and exits 1; removes its work folder and the session folders under the user's Claude projects folder | needs the owner's cap |
| `python3 plugins/memory/evals/integrate/run_trial.py verdict RESULT_JSON --audit-reply FILE [--audit-cost USD]` | the table and the final verdict of a saved result with the audit session's reply (strict parse, see criterion 3) | none |

Unit tests of the grading: `plugins/memory/engine/tests/integrate/test_trial_grading.py`.

## What the self-check covers

The self-check's four wrong answers all exercise the **wrong attachment** criterion (four different branches of it: a forbidden label attached, `append` against a sentence label, another sentence of the right part, a row for another part). The other criteria (seed size, append share, unbacked sentences, another note changed, stale to current, undo, both cost bars, void) are covered by the unit tests on canned data, not end to end.

The `append` floor: the seed holds 17 `append` notes; the kill criterion needs at least 15 (`MIN_APPEND`), and `test_seed_keeps_its_label_counts` floors the seed at 16, so one note may go before the seed test fails.

## Check probe

`check_probe.py` measures only the **check** session of `mem-integrate` on fixed right and wrong rows, so a change to `plugins/memory/engine/integrate/briefs/check-brief.md` can be judged without a full trial (plan `docs/superpowers/plans/2026-11-27-memory-integrate-check-append.md`). It builds the seeded store, takes the candidate with the engine's `candidates`, builds the input with `check_input` and runs the session through `ask_readable`, as production does, so the shipped brief, settings and session command are what is measured. A run counts only when the session returned a parsable answer (rows or `none`): a failed, unreadable or malformed run is `void`, shown as such, excluded from every total and counted (`void runs: N`). The result JSON keeps each run's raw answer, the brief's path and sha256 and the row table's sha256, so a baseline and a post-fix file can be told apart. The row table is fixed in code before any paid run: do not tune it afterwards.

| Group | Rows | Right answer |
|---|---|---|
| `right-append` | 17: the seed's `append` notes on their labelled part | accept |
| `right-unit` | 8: `belongs-existing-sentence` and `duplicate-of-existing` on their labelled sentence | accept |
| `no-fit` | 4: each `on-topic-no-fit` note appended to its nearest part | reject |
| `wrong-part` | 3: `load-then-index`, `clustered-key-order` to `#selection`; `function-defeats-index` to `#structures` | reject |
| `arguable` | 1: `usage-statistics` to `#selection` (the owner may judge it right) | reported, not counted in the wrong-row gate |
| `contradiction` | 8: six claims written in the table, each negating one sentence of its part, plus the claims of the seed notes `indexes-speed-all` and `index-everything` (injected into the check input only, handles `probe-contra-N`) | reject |
| `wrong-unit` | 5: `append` notes joined as `unit N` to a sentence of their own part that does not state them | reject |

| Command | What it does | Cost |
|---|---|---|
| `python3 plugins/memory/evals/integrate/check_probe.py --self-check` | a fake `claude` that accepts the right rows (the grade must be clean), then once also one wrong row (it must be reported) | none |
| `python3 plugins/memory/evals/integrate/check_probe.py --budget USD [--claude PATH] [--runs N] [--brief PATH] [--out DIR]` | the paid run: `--runs` check sessions (default 2) over all 46 rows, one session per run; `--brief` uses another check brief for the run without touching the shipped one; prints accepted/total per group and each wrong row accepted; writes the JSON under `target/mem-trials/check-probe/`; stops when `--budget` is spent | about 0.01 USD a run |

Unit tests: `plugins/memory/engine/tests/integrate/test_check_probe.py`.

What it cannot show: one seeded synthesis of three parts; place is not run (it proposed every right row in the trial); and 2 runs over about 21 wrong rows bound a false-accept rate only below about 8%. The held-out run on a copy of the real store is the check that matters for production.
