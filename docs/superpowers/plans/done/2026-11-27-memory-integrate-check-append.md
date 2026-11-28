# mem-integrate: the check session rejects every append

Status: done, released in memory 0.16.1 (PR #223) · Date: 2026-11-27 · Branch: fix/memory-integrate-check-append

Owner ruling 2026-11-27: fix and measure, then release memory 0.16.1.

## Root cause (observed 2026-11-27, about 0.03 USD)

The stage 3 trial ([seamless plan § Results, "Stage 3 trial"](../2026-11-17-memory-seamless.md)) placed 0 of 17 appends. A rerun with the run folder kept showed: place proposed all 17 appends and the 8 unit rows; check accepted only the 8 units. A diagnostic check run (same brief and input, one reason per item) rejected each append because "the part does not mention X, so the claim adds a new fact". The `part_text` row of `plugins/memory/engine/integrate/briefs/check-brief.md` judges "what the part covers" against the part's current sentences, which an append by definition extends. With one added sentence in that row (the part's subject is the name after `#` in its handle; a fact the part does not mention yet is not a reason to reject), check accepted 25 of 25 on the same input. Not yet run on wrong rows.

## Tasks

- [x] 1. Check probe: `plugins/memory/evals/integrate/check_probe.py` builds the seeded store with the trial's helpers, takes the candidate with the engine's `candidates`, builds rows with `row_line`, the check input with `check_input`, and runs only the check session through `Job.ask` with the shipped brief (or a brief file given), so its input is the production input. Rows, as a table committed before task 2: the 25 right rows (17 appends to their labelled part; 8 unit rows: `belongs-existing-sentence` and `duplicate-of-existing` on their labelled sentence); wrong rows: each `on-topic-no-fit` note appended to its nearest part (4); wrong-part appends to the nearest plausible part (`usage-statistics`, `load-then-index`, `clustered-key-order` → `#selection`; `function-defeats-index` → `#structures`); at least 4 contradiction appends that negate a part sentence (written into the probe's table, e.g. "Hash indexes serve range lookups well" → `#structures`), plus `indexes-speed-all` and `index-everything` claims as contradictions; 5 `append` notes as `unit N` on a sentence of their own part that does not state them. Superseded and disputed notes never reach check (refused by `_loose_notes` and again at apply in `commands/integrate.py`), so they are not probe rows. `--self-check` with a fake `claude`, no cost, and a test that the probe's check input equals what `place_and_check` builds for the same rows. Check: its tests and self-check pass; Ruff and basedpyright clean.
- [x] 2. Baseline: the probe on the current brief, 2 runs (expected: 0 appends accepted). Check: table recorded under Results.
- [x] 3. Brief fix in `check-brief.md` (`part_text` row only). Check: the probe on the new brief, 2 runs; rule below; `mem-integrate --self-check` passes.
- [x] 4. Trial rerun `run_trial.py --budget 0.30` on the new brief, the Sonnet audit of the appended sentences, `run_trial.py verdict`. Check: verdict `pass`, recorded in the seamless plan § Results.
- [x] 4b. Held-out run on a copy of the real store (`cp -a` to the scratchpad; `MEM_MEMORIES` unset; `mem-integrate run --store COPY --budget 0.10` from the repo engine). Every applied append gets a Sonnet audit for right part and backing. Check: no applied append judged wrong.
- [x] 5. Docs and release: memory CHANGELOG `[Unreleased]` line (what changed, how it was measured: probe, trial, real copy; kill criteria linked), README integrate heading, the `entry/integrate.py` docstring if it says "not measured", seamless plan and backlog; PR to `dev`, review, release memory 0.16.1, update the installed plugin.

## Rule, fixed before the probe runs on the new brief

Adopt the new wording when, in each of 2 probe runs: no wrong row (no-fit, wrong-part, contradiction, wrong unit) is accepted; at least 13 of the 17 right appends and at least 7 of the 8 right unit rows are accepted; and task 4b applies no append its audit judges wrong. One revision of the wording is allowed only if task 4b (the held-out set) gates it as well; then stop and report to the owner. The trial in task 4 keeps its own kill criteria. Limit: 2 runs and about 20 wrong rows bound a false-accept rate only below about 8%; the real copy is the check that matters for production.

Kill criteria: any wrong row accepted in a probe run with the final wording → revert; an applied append judged wrong on the real copy → do not release, re-plan (e.g. give check the part heading or the neighbouring parts); right appends under 13 of 17 after the one revision → stop and report; tasks 2–4b above 1 USD → stop.

Cost cap: 1 USD for tasks 2–4b.

## Results

Probe rows (fixed in `check_probe.py` before task 2, commit b91378d; ruling 0d81333, before any run of a new brief: `usage-statistics → #selection` moved to an `arguable` group outside the gate, since its part is debatable). Groups: right-append 17, right-unit 8, no-fit 4, wrong-part 3, contradiction 8, wrong-unit 5, arguable 1.

| Run set | Brief | Parser | Right appends | Right units | Wrong rows accepted | Void | Cost USD |
|---|---|---|---|---|---|---|---|
| Baseline, 2 + 6 runs | old | strict | 24 of 136 (17 and 7 in two runs, 0 in six) | 64 of 64 | 0 of 168 (4 wrong-part rows then) | not counted (old grading) | 0.061 |
| New brief, 6 runs | new (dd4b7ae) | strict | 66 of 68 | 32 of 32 | 0 of 80 | 2 (format: a cut first line; a `row:` prefix) | 0.052 |
| New brief, 6 runs | new | tolerant (da76d54, owner's choice) | 99 of 102 | 48 of 48 | 0 of 120 | 0 | 0.052 |

Rule: met in every counted run (at least 13 of 17 appends, 7 of 8 units, no wrong row). Replaying the two void answers through the tolerant parser kept 19 and 25 rows offline, with the cut line ignored.

Trial (task 4; brief dd4b7ae, strict parser, before da76d54): **pass**, 16 notes integrated, 8 of 17 appends placed, 0 wrong; Sonnet audit 8 of 8 backed (0.155 USD); sessions 0.012 USD. Why 9 appends were not placed was not read (the run folder is removed by the harness).

Held-out (task 4b, copy of the real store; brief dd4b7ae, strict parser; the gate "no applied append judged wrong" held trivially, since none was applied, so the stress run below is the evidence for check on real parts; `MEM_DATA` and `--store` in the scratchpad): `mem-integrate run` found 1 synthesis (`llm-agents`, 4 loose notes); place answered `none`, nothing applied (0.007 USD). Stress on the same copy, check only: each of the 4 notes forced as an append into each of the 8 parts (32 wrong rows): 0 of 32 accepted in 2 runs; a third run was void because the input (each row carries its whole part) reached about 340k tokens. That size is an artifact of 32 forced rows, but it shows check input grows with rows times part size: see backlog.

Parser revision after review (2026-11-27): a prose line (no ` | `, such as a "Rejected:" heading above refused rows) voids the check answer, since the tolerant parser of da76d54 would have kept rows listed under it. Replaying the 12 saved answers of the new brief offline through the final parser: 0 void, the kept counts equal the right rows recorded, no wrong row kept.

Spent on this plan: about 0.42 USD of the 1 USD cap (diagnosis 0.03, probes 0.165, trial with audit 0.17, real copy 0.055).
