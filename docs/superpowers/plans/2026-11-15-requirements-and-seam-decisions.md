# Requirements review and seam decisions

Goal: record the owner's decisions of 2026-11-15 so that requirements, ADRs, the routing text and the seams document agree, and the two plugins give one instruction per task. No agent, skill or command file changes; `user-config/offload-policy.md` stays byte-identical because the offload evals embed it.

## Decisions taken by the owner (intent-elicitation, 2026-11-15)

| # | Decision | Seams |
|---|---|---|
| 1 | Eight goals are functional and hard (G1-G8 below); a requirement row is hard only when it restates a goal; every other requirement, threshold, model choice and ADR is a soft means with a revisit condition | all |
| 2 | An approved code plan runs in the Superpowers `subagent-driven-development` loop (order, ledger, one task at a time), with `implementer` as its implementer and `skeptical-reviewer` as its task reviewer; the review brief adds the plan task (missing, extra, misunderstood) | E1, E2, E3, P3, R1 |
| 3 | After the last task, several narrow `skeptical-reviewer` reviews replace the loop's whole-branch review | R1 |
| 4 | Inside the loop `implementer` commits each task locally and the review follows; "review before" applies to push, PR, merge, tag and commits on a branch that already has an upstream on the remote | E1 |
| 5 | Test-first: a plan task carries its own test-then-code steps; outside a plan `implementer` keeps "see it fail when feasible" | D4 |
| 6 | A `check-runner` PASS is evidence when the report names the command and its result; the main conversation reruns the decisive check before a commit, push or PR | R3 |
| 7 | Mechanical fixes (lint, types, format, imports) go to `fixer` without a root-cause investigation; the same error after 2 attempts, or a test failing on behavior, goes to Superpowers `systematic-debugging` | D2 |
| 8 | The routing tables decide who does the work; a Superpowers skill loads when a table names it | A1 |
| 9 | N6 is soft: descriptions and the offload table are measured; other changes may ship unmeasured with a written kill criterion. Nothing is re-measured for the new main model until a measured text changes | none |
| 10 | The repository is the single source of the user-level rules: the review rows that exist only in the owner's CLAUDE.md move into `user-config/routing.md` (not into `offload-policy.md`) | R1, R3 |
| 11 | The repository is public on purpose; ADR 0008 gets a review note; a license stays an open question | none |
| 12 | No Superpowers skill is blocked in settings | none |

Goals: G1 the main conversation decides and cheaper models read, run and write bounded code. G2 nothing is called done without evidence and a fresh-context review. G3 long work survives a compaction and the owner can see where it is. G4 intent is recovered before a broad change. G5 each specialist finding cites a principle and evidence. G6 documentation is dense: the why, no duplicates. G7 the two plugins give no contradictory instruction for one task. G8 current performance does not get worse.

## Pre-mortem amendments (2026-11-15)

| Finding | Outcome |
|---|---|
| The loop expects a commit, a report file, status words, two verdicts and up to five fix rounds that the two agents do not provide | Six bridging lines in `routing.md` "Plan loop" say who supplies each |
| The skill tells the main conversation to name a model at every dispatch | Both role lines say "without a model override" |
| `task-brief` needs `### Task N` headings | The "Execute a plan" row limits the loop to plans with those headings |
| "Shared branch" was undefined | Written as "a branch that exists on the remote" |
| Seam IDs R1 and R3 collide with requirement IDs | ADRs write "seam R1", "seam R3" |
| Deleting decided seam rows would drop evidence that pull request #113 carries | Rows stay; the index gains a Status column |
| The routing change ships unmeasured | Kill criteria in ADR 0019; N6 reworded by ADR 0020 |
| `validate.py` does not parse `requirements.md` | IDs counted with grep |

## Tasks

- [x] Pre-mortem on this plan; amendments folded in. Check: its findings are listed here with their outcome.
- [x] `docs/requirements.md`: goals G1-G8, each R and N classified (functional or technical, hard or soft, revisit condition), R5 and N6 reworded, boundary table rewritten, date updated. Check: every existing ID survives (`grep -c` of R1-R5, N1-N11); `python3 scripts/validate.py` passes.
- [x] ADRs 0019 (plan loop and seam rulings), 0020 (goals and means, N6), 0021 (single source of user-level rules); review notes on 0008, 0010, 0017; status lines updated on every amended ADR. Check: `grep -n '^Status' docs/adr/*.md` shows each amendment on both sides.
- [x] `user-config/routing.md`: plan and execution rows, defect row, order line, review and proof-of-done section; ports and README block regenerated. Check: `python3 scripts/port.py --check` passes; `git diff --stat user-config/offload-policy.md` is empty.
- [x] README and maintainer notes: boundary sentences, workflow diagram, mod count. Check: no sentence says Superpowers owns execution or general review.
- [x] `docs/superpowers-seams.md`: decided seams are marked in the index with the ADR and keep their rows; summary and open questions updated. Check: 9 decided and 16 open rows; summary counts match.
- [x] Proposal for the owner's user-level CLAUDE.md updated (outside this repository; the real file is not edited). Check: its offload section equals `user-config/offload-policy.md`.
- [ ] Reviews: prompt review of `routing.md`, narrow reviews of the diff, a process review; findings triaged. Check: round 2 at most.
- [ ] Commit, push and pull request based on `docs/superpowers-seams`; not merged. Check: `gh pr view --json files` matches `git diff --stat`.
