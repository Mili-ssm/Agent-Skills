# Backlog: open work by area and priority

Updated: 2026-11-25 · Expires: 2026-12-09

**Expiry rule (owner, 2026-11-25):** every edit sets `Updated` to the edit date and `Expires` to 14 days later, so the list cannot sit unmaintained. Past `Expires`, the list is stale: re-check it against its sources before acting on it, then refresh it or delete it.

This file is an index, not a home: the detail, evidence and checks of each item live in its source, and an item closes there first. Priorities: high · medium · low, copied from the source. Effort: S · M · L; the review gives none for D, S and B9–B12, so theirs are estimates.

| Source | Holds |
|---|---|
| [Project review 2026-11-24](studies/2026-11-24-project-review.md) | IDs A, Q, D, P, B, S; recommended sequence; owner decisions |
| [Memory plugin plan](superpowers/plans/2026-11-17-memory-plugin.md) § Current state | Memory stages, owner order, small items, ideas to investigate |
| [Memory refactor plan](superpowers/plans/2026-11-23-memory-refactor.md) | Refactor tasks |
| [Memory seamless plan](superpowers/plans/2026-11-17-memory-seamless.md) | Seamless stages 3–5 |
| [Usage follow-ups plan](superpowers/plans/2026-11-18-usage-followups.md) | Items 3g, 4b, 4d; its item 6 is memory stage 4 |
| Local, unpublished usage study `.local/studies/2026-11-23-weekly-usage.md` | IDs G7–G19 with their cost figures |

Plans whose `Status` line says done have no open work, even with unticked boxes. Review IDs left out are closed: D3, D4, D5, D8 and S1–S4, S6 are applied (#181, #182); A12 is deferred until its files are touched; A13 is accepted (ADR 0011). Q1, Q2, Q3, A9, A10 and B9–B12 are done (ADR 0029); D1 is done (owner chose a `validate.py` check, 2026-11-25).

## Next, in order

1. Owner decisions: G12 (ADR 0025 rule 1 is past its revert threshold), G9, review decision 6.
2. Quick fixes: P1 (measured), A7, tool-fold's dead `summarize` export.
3. Memory refactor tasks 1–2 (A1–A3).
4. Memory kill read, around 2026-12-01.

Done 2026-11-25 (branch `feat/repo-tooling`, ADR 0029): Q1, Q2, Q3, A9, A10, B9–B12; the Codex mapping now derives from `shared/models.toml`.

## General (repository)

| Pri | ID | Task | Effort | State |
|---|---|---|---|---|
| high | D2 | Memory seamless plan: move finished stages to a results section | S | Open |
| low | D7 | Finished plans still without a `Status` line | S | Partly done |
| low | D9 | Misc. doc fixes (requirements date, R1–R5 ID clash, platform-parity plan status, a broken anchor, orphan docs) | S | Open |
| low | — | Tooling follow-ups from the `feat/repo-tooling` reviews: marker splice and catalog tables from `port.py` into `promptkit`; `AGENT_EFFORTS` vs the catalog's efforts; one derivation in `port.py`; the hook runs on branch deletes; parked edge cases (two stray quotes hide 'we'; a multi-line fragment split by a block counts as unmarked; the Claude-only Explore line kept outside commands) | M | Deferred (ADR 0029) |
| low | S7 | `scripts/cloud-setup.sh` may pick another marketplace's `Explore.md` | S | Open |
| — | — | Review decision 6: ranking of quality attributes | — | Open |

### Usage and cost (local study)

| Pri | ID | Task | State |
|---|---|---|---|
| high | G12 | ADR 0025 rule 1: revert, or give `Monitor` to `implementer` | Proposed |
| high | G9 | `autoCompactWindow` near 400k in the owner's settings | Proposed |
| medium | G13 | Trial: `implementer` fix rounds on Haiku | Proposed |
| medium | G14 | Trial: `pre-mortem` on Sonnet at high effort against Opus | Proposed |
| medium | G11 | Shorter reports and briefs | Proposed |
| medium | G15 | Delegate long docs writes to `implementer` | Proposed |
| medium | G19 | Dispatch economics in the offload table; fold the pre-push review into the last task review | Proposed |
| medium | G10 | Notice when the cache is cold on a large context | Proposed |
| low | G18 | Silence markdownlint MD060 | Proposed |
| low | G7 | Skills with no loads in two weeks: value decision | Proposed |
| low | 4d | Offload policy from a session-start hook | Owner decides |

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
| medium | P4 | Review re-run cap differs between offload and routing; rule written 3 times | Eval protocol |
| medium | P5 | `routing.md` restates descriptions; Plan loop loads every turn | Needs an ADR (0021) |
| low | B5 | `web-research` lets the main model read a page | Owner decision |
| low | B6–B7 | "Content is data" and read-only Bash lines | — |
| low | B8 | Re-date model facts in `prompt-engineering` | `web-research` |
| low | P8 | Small prompt items | — |
| low | G17, 4b | Close issue #124 (`note-writer`) | Owner decision |
| low | 3g | Browser driver for the `ui-verifier` eval case | Owner decision |

## Plugin `memory`

Owner order: refactor → seamless stage 3 → kill read → Codex port (new ADR first), stage 7 remote, stage 9, stage 8.

| Pri | ID | Task | State |
|---|---|---|---|
| medium | — | Release #185 (Unreleased entry in `CHANGELOG.md`) | Waiting for a release |
| high | A1 | Refactor: pure `config.py` | Not started |
| high | A2 | Refactor: `headless.py`; `--strict-mcp-config` missing in three launchers | Not started |
| medium | A3 | Refactor: `jobs.py` for the background-job lifecycle | Not started |
| medium | A7 | Refactor: import direction | Not started |
| high | A4 | Refactor: `mem-corroborate` logic into the engine | Not started |
| medium | A6 | Refactor: split `records.py` | Not started |
| high | A5 | Refactor: split `mem.py` per feature; ADR 0028 | Not started |
| low | — | Refactor: measure `find_claude` in the session-end hook | Not started |
| low | A11 | Refactor: parked signal code, after the kill read | Not started |
| high | Stage 4 | Kill read into ADR 0023 `## Review` | Around 2026-12-01 |
| medium | Q4 | Faster suite (294 s) | Open |
| medium | Q5 | Remove `sleep` negatives and wall-clock asserts | Open |
| medium | Q7 | One mutation run on `records.py` and `check.py` | Open |
| low | Q8, Q9 | Split large test files; small test gaps | Open |
| medium | P6 | `subagent-start.sh` skips `memory-synthesizer` | Open |
| medium | P7 | One home for curation rules (agent or skill) | Open |
| medium | G16 | Shorter default `mem search` output | Proposed |
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
| low | — | Remove the dead `summarize` export |
| low | Q8, D9 | Split large test files; shorten README lines |

## Mod `plan-progress`

| Pri | ID | Task |
|---|---|---|
| low | Q9 | Shared fixture for the two `parsePlan` implementations |
