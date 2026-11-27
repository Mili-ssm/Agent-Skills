# mem-integrate: the check session rejects every append

Status: planned · Date: 2026-11-27 · Branch: fix/memory-integrate-check-append

Owner ruling 2026-11-27: fix and measure, then release memory 0.16.1.

## Root cause (observed 2026-11-27, about 0.03 USD)

The stage 3 trial ([seamless plan § Results, "Stage 3 trial"](2026-11-17-memory-seamless.md)) placed 0 of 17 appends. A rerun with the run folder kept showed: place proposed all 17 appends and the 8 unit rows; check accepted only the 8 units. A diagnostic check run (same brief and input, one reason per item) rejected each append because "the part does not mention X, so the claim adds a new fact". The `part_text` row of `plugins/memory/engine/integrate/briefs/check-brief.md` judges "what the part covers" against the part's current sentences, which an append by definition extends. With one added sentence in that row (the part's subject is the name after `#` in its handle; a fact the part does not mention yet is not a reason to reject), check accepted 25 of 25 on the same input. Not yet run on wrong rows.

## Tasks

- [ ] 1. Check probe: `plugins/memory/evals/integrate/check_probe.py` builds the seeded store with the trial's helpers, takes the candidate with the engine's `candidates`, builds rows with `row_line`, the check input with `check_input`, and runs only the check session through `Job.ask` with the shipped brief (or a brief file given), so its input is the production input. Rows, as a table committed before task 2: the 25 right rows (17 appends to their labelled part; 8 unit rows: `belongs-existing-sentence` and `duplicate-of-existing` on their labelled sentence); wrong rows: each `on-topic-no-fit` note appended to its nearest part (4); wrong-part appends to the nearest plausible part (`usage-statistics`, `load-then-index`, `clustered-key-order` → `#selection`; `function-defeats-index` → `#structures`); at least 4 contradiction appends that negate a part sentence (written into the probe's table, e.g. "Hash indexes serve range lookups well" → `#structures`), plus `indexes-speed-all` and `index-everything` claims as contradictions; 5 `append` notes as `unit N` on a sentence of their own part that does not state them. Superseded and disputed notes never reach check (refused by `_loose_notes` and again at apply in `commands/integrate.py`), so they are not probe rows. `--self-check` with a fake `claude`, no cost, and a test that the probe's check input equals what `place_and_check` builds for the same rows. Check: its tests and self-check pass; Ruff and basedpyright clean.
- [ ] 2. Baseline: the probe on the current brief, 2 runs (expected: 0 appends accepted). Check: table recorded under Results.
- [ ] 3. Brief fix in `check-brief.md` (`part_text` row only). Check: the probe on the new brief, 2 runs; rule below; `mem-integrate --self-check` passes.
- [ ] 4. Trial rerun `run_trial.py --budget 0.30` on the new brief, the Sonnet audit of the appended sentences, `run_trial.py verdict`. Check: verdict `pass`, recorded in the seamless plan § Results.
- [ ] 4b. Held-out run on a copy of the real store (`cp -a` to the scratchpad; `MEM_MEMORIES` unset; `mem-integrate run --store COPY --budget 0.10` from the repo engine). Every applied append gets a Sonnet audit for right part and backing. Check: no applied append judged wrong.
- [ ] 5. Docs and release: memory CHANGELOG `[Unreleased]` line (what changed, how it was measured: probe, trial, real copy; kill criteria linked), README integrate heading, the `entry/integrate.py` docstring if it says "not measured", seamless plan and backlog; PR to `dev`, review, release memory 0.16.1, update the installed plugin.

## Rule, fixed before the probe runs on the new brief

Adopt the new wording when, in each of 2 probe runs: no wrong row (no-fit, wrong-part, contradiction, wrong unit) is accepted; at least 13 of the 17 right appends and at least 7 of the 8 right unit rows are accepted; and task 4b applies no append its audit judges wrong. One revision of the wording is allowed only if task 4b (the held-out set) gates it as well; then stop and report to the owner. The trial in task 4 keeps its own kill criteria. Limit: 2 runs and about 20 wrong rows bound a false-accept rate only below about 8%; the real copy is the check that matters for production.

Kill criteria: any wrong row accepted in a probe run with the final wording → revert; an applied append judged wrong on the real copy → do not release, re-plan (e.g. give check the part heading or the neighbouring parts); right appends under 13 of 17 after the one revision → stop and report; tasks 2–4b above 1 USD → stop.

Cost cap: 1 USD for tasks 2–4b.

## Results
