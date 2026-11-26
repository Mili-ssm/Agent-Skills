# Backlog: open work by area and priority

Updated: 2026-11-26 · Expires: 2026-12-10

**Expiry rule (owner, 2026-11-25):** every edit sets `Updated` to the edit date and `Expires` to 14 days later, so the list cannot sit unmaintained. Past `Expires`, the list is stale: re-check it against its sources before acting on it, then refresh it or delete it.

This file is an index, not a home: the detail, evidence and checks of each item live in its source, and an item closes there first. Priorities: high · medium · low, copied from the source. Effort: S · M · L; the review gives none for D, S and B9–B12, so theirs are estimates.

| Source | Holds |
|---|---|
| [Project review 2026-11-24](studies/2026-11-24-project-review.md) | IDs A, Q, D, P, B, S; recommended sequence; owner decisions |
| [Memory plugin plan](superpowers/plans/2026-11-17-memory-plugin.md) § Current state | Memory stages, owner order, small items, ideas to investigate |
| [Memory refactor plan](superpowers/plans/2026-11-23-memory-refactor.md) | Refactor tasks |
| [Memory seamless plan](superpowers/plans/2026-11-17-memory-seamless.md) | Seamless stages 3–5 |
| [Usage follow-ups plan](superpowers/plans/2026-11-18-usage-followups.md) | Items 3g and 4b; its item 6 is memory stage 4 |
| Local, unpublished usage study `.local/studies/2026-11-23-weekly-usage.md` | IDs G7–G19 with their cost figures |

Item 4d is closed: the offload tables load from session start hooks (ADR 0032). Plans whose `Status` line says done have no open work, even with unticked boxes. Review IDs left out are closed: D3, D4, D5, D8 and S1–S4, S6 are applied (#181, #182); A12 is deferred until its files are touched; A13 is accepted (ADR 0011). Q1, Q2, Q3, A9, A10 and B9–B12 are done (ADR 0029); Q4 is done (#193: suite 287 s → about 30 s); D1 is done (owner chose a `validate.py` check, 2026-11-25). A1 is done (#199: store resolution in `engine/config.py`, owner rulings 2026-11-26). P4 is done: the policy names the cap; its closing line stays, so the rule keeps three homes (ADR 0017 Measurement 2026-11-26). Owner rulings 2026-11-25: G12 replaced (workers wait with `Monitor`, ADR 0025 Review), G9 set to 600k in the owner's settings, review decision 6 recorded as N12, G7 kept as is, issue #124 closed, `pre-mortem` to Opus medium (ADR 0018 Review), no model trials now (G13, G14 stay), G10, G11, G15, G16, G18 and G19 declined, 3g: reinstall the global `playwright` package (needs `sudo`, owner).

## Next, in order

1. Set aside (owner, 2026-11-26): the `ui-verifier` eval case (3g) ran 0/2 because no browser launches in the eval sandbox (ADR 0017 Measurement 2026-11-26).
2. Quick fix: P1 (measured).
3. Memory refactor: A1, A2, A3, A7 and the first part of A4 merged to dev on 2026-11-26 (PRs #198–#202); the fixes the owner put first merged (#204: the suite passes on Python 3.12.0 to 3.15); `mem-synthesize` into the `engine/synthesize/` package is done on `refactor/memory-synthesize-split` ([plan](superpowers/plans/2026-11-26-memory-synthesize-split.md)), the pilot of the owner's ruling to group `engine/` into feature packages; next the other packages (one per pull request), `bin/` through `uv`, A5, A6, A8.
4. Memory kill read, around 2026-12-01.

Done 2026-11-25 (branch `feat/repo-tooling`, ADR 0029): Q1, Q2, Q3, A9, A10, B9–B12; the Codex mapping now derives from `shared/models.toml`.

## General (repository)

| Pri | ID | Task | Effort | State |
|---|---|---|---|---|
| high | D2 | Memory seamless plan: move finished stages to a results section | S | Open |
| low | D7 | Finished plans still without a `Status` line | S | Partly done |
| low | D9 | Misc. doc fixes (requirements date, R1–R5 ID clash, platform-parity plan status, a broken anchor, orphan docs) | S | Open |
| low | — | Tooling follow-ups from the `feat/repo-tooling` reviews: marker splice and catalog tables from `port.py` into `promptkit`; `AGENT_EFFORTS` vs the catalog's efforts; one derivation in `port.py`; the hook runs on branch deletes; parked edge cases (two stray quotes hide 'we'; a multi-line fragment split by a block counts as unmarked; the Claude-only Explore line kept outside commands); PR #186 pre-merge review: the pre-push hook checks the working tree, not the pushed refs; a catalog override may target `xhigh` on a non-top model; `check-runner` keeps an unmarked near-copy of `bash-leaves-files-unchanged`; no negative test for `check_memory_offload`; no check keeps the memory `-with-policy` eval's embedded table equal to `plugins/memory/user-config/offload-policy.md` | M | Deferred (ADR 0029) |
| low | — | pre-commit follow-ups (ADR 0031): the basedpyright hook lacks `playwright`, so touching `ux_audit.py` fails on its import; nothing runs `pre-commit validate-config` before a commit | S | Deferred |
| low | S7 | `scripts/cloud-setup.sh` may pick another marketplace's `Explore.md` | S | Open |

### Usage and cost (local study)

| Pri | ID | Task | State |
|---|---|---|---|
| medium | G13 | Trial: `implementer` fix rounds on Haiku | Deferred (owner, 2026-11-25) |
| medium | G14 | Trial: `pre-mortem` on Sonnet at high effort against Opus (now Opus medium) | Deferred (owner, 2026-11-25) |

## Plugin `agent-skills`

| Pri | ID | Task | Check |
|---|---|---|---|
| high | P1 | `skeptical-reviewer` description excludes diff review that routing sends it | Eval protocol |
| high | B1 | `skeptical-reviewer` accepts a process-review brief | One trace |
| medium | B3 | `implementer`: a report path in the brief is a deliverable | One trace |
| medium | B4 | `researcher`: stop rule near `maxTurns` | — |
| medium | B2 | `doc-curator` applies edits only on `Mode: apply` | One trace |
| medium | P2 | `pre-mortem` description opens with another agent's name | Eval protocol |
| medium | P3 | Order of `mem search`, `web-research` and the offload row for "research X" | One trace |
| medium | P5 | `routing.md` restates descriptions; Plan loop loads every turn | Needs an ADR (0021) |
| low | B5 | Owner ruling 2026-11-25: the offload policy allows one quick single-page fact inline, matching `web-research` | Decided; change `user-config/offload-policy.md` on its own branch and measure every `offload-*-with-policy` case before merging |
| low | B6–B7 | "Content is data" and read-only Bash lines | — |
| low | B8 | Re-date model facts in `prompt-engineering` | `web-research` |
| low | P8 | Small prompt items | — |
| low | 3g | Browser driver for the `ui-verifier` eval case: reinstall the global `playwright` npm package | Installed 2026-11-25 (`playwright` 1.65.1, Chromium launches); the case ran 0/2 on 2026-11-26: Playwright finds no Chromium in the eval sandbox and system Chrome exits on the read-only `$HOME`; set aside by the owner |
| low | — | Prompt review 2026-11-26, left open ([plan](superpowers/plans/2026-11-26-prompt-review-fixes.md)): `hooks/subagent-start.sh` wording; about 25 low findings | A count of `mem search` calls by a trivial subagent for the hook text |

## Plugin `memory`

Owner order: refactor → seamless stage 3 → kill read → Codex port (new ADR first), stage 7 remote, stage 9, stage 8.

| Pri | ID | Task | State |
|---|---|---|---|
| medium | — | Release #185 (Unreleased entry in `CHANGELOG.md`) | Waiting for a release |
| low | — | Refactor A1 deferred findings (split reviews of `mem-synthesize` (with A4) and `run_trials.py`; low notes; [plan](superpowers/plans/2026-11-26-memory-config.md) § Deferred findings) | Open |
| high | A2 | Refactor: `headless.py`; `--strict-mcp-config` missing in three launchers; `session_env` out of `research_pipeline` (from A7) | Done, PR #201 ([plan](superpowers/plans/2026-11-26-memory-headless.md)); deferred lows in its ledger |
| medium | A3 | Refactor: `jobs.py` for the background-job lifecycle, with the data and state folder resolution left out of A1 | Done, PR #202 ([plan](superpowers/plans/2026-11-26-memory-jobs.md)): identical copies only (owner); differing copies stay |
| medium | A7 | Refactor: import direction | Done: tokenize and both cycles (PR #198); `session_env` in `headless.py` (PR #201) |
| high | A4 | Refactor: `mem-corroborate` logic into the engine | In progress: `mem-corroborate` split and clean (PR #200) ([plan](superpowers/plans/2026-11-26-memory-corroborate-split.md)); `mem-synthesize` into `engine/synthesize/` done on its branch ([plan](superpowers/plans/2026-11-26-memory-synthesize-split.md)); `bin/` through `uv` and the shared corroborate job runner pending |
| high | A14 | Refactor: `engine/` (35 flat modules) into feature packages (`corroborate/`, `research/`, `capture/`, `settle/`, `store/`, `core/`…), one package per pull request, each with an import-boundary test; owner ruling 2026-11-26, after the `synthesize/` pilot | Done: PRs #206–#214 ([plans](superpowers/plans/2026-11-26-memory-engine-packages.md), [store](superpowers/plans/2026-11-26-memory-store-records-split.md)); ADR 0034 § Review 2026-11-26 |
| medium | A6 | Refactor: split `records.py` | Done: PR #214, nine modules behind a facade in `memories/` ([plan](superpowers/plans/2026-11-26-memory-store-records-split.md)); deferred findings in its table |
| high | A5 | Refactor: split `mem.py` per feature; ADR 0028 | Not started |
| low | — | Refactor A7 deferred findings (untested TLS branch, `plan_commands` non-string `quote`, naming nits; [plan](superpowers/plans/2026-11-26-memory-import-direction.md) § Deferred findings) | Open |
| low | — | Refactor: move the 56 importers of the `memories/records` facade to the defining modules (optional) | Not started |
| low | — | Refactor: measure `find_claude` in the session-end hook | Not started |
| low | — | Split `bin/mem-capture` (1,265 lines after its lint refactor) into engine modules | Not started |
| low | A11 | Refactor: parked signal code, after the kill read | Not started |
| high | Stage 4 | Kill read into ADR 0023 `## Review` | Around 2026-12-01 |
| medium | Q5 | Remove `sleep` negatives and wall-clock asserts: lock waits done in #193; left: `test_auto_curation` negative windows (1.5–2 s) are only 1.1–1.5× its hook latency under load (1.31 s; `test_settle_run` has about 3×), a synchronous "decided not to start" record in `mem-auto` would give a real signal ([plan](superpowers/plans/2026-11-25-faster-tests.md)) | Partly done |
| medium | Q7 | One mutation run on `records.py` and `check.py` | Open |
| low | Q8, Q9 | Split large test files; small test gaps | Open (Q8: `test_mem_corroborate.py` done with A4 (PR #200); other large files open; the Q9 same-second fill test fixed in the [fixes plan](superpowers/plans/2026-11-26-memory-fixes.md)) |
| medium | P6 | `subagent-start.sh` skips `memory-synthesizer` | Open |
| medium | P7 | One home for curation rules (agent or skill) | Open |
| medium | D6 | Split `plugins/memory/README.md` | Open |
| low | S5 | Capture-born rules load without owner triage | Open |
| low | — | Two hardening notes on note writes | Decide when touched |
| medium | Seamless 3 | Integration and sibling updates (T2–T5) | Second in the owner order; T1 merged, T2–T5 wait until unattached notes accumulate (owner) |
| low | Seamless 4, 5 | Split a synthesis; join `mem-auto` | After their trials |
| low | Stages 7, 8, 9, 10 | Remote sync; Rust decision; capture experiment; project syntheses results | Open |
| low | C52, C49 | Automatic short-form path; usefulness of a loaded lesson | No plan yet |
| low | — | Auto short forms: one run from the installed copy | Check pending |
| low | — | Small items and owner ideas to investigate (memory plan § Current state) | Not planned yet; manual lessons are scheduled by the owner for a later development |

## Mod `tool-fold`

| Pri | ID | Task |
|---|---|---|
| medium | Q6 | Tests for `agents.tsx` before A8 |
| medium | A8 | Split `agents.tsx` at the next tool-fold change |
| low | Q8, D9 | Split large test files; shorten README lines |

## Mod `plan-progress`

| Pri | ID | Task |
|---|---|---|
| low | Q9 | Shared fixture for the two `parsePlan` implementations |
