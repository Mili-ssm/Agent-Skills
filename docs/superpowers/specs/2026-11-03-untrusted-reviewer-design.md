# untrusted-reviewer: cheap after-action reviewer

Status: proposed · Date: 2026-11-03

## Intent
The complement of `pre-mortem`: pre-mortem stress-tests plans before work (Opus); `untrusted-reviewer` reviews each reviewable action during the work (cheapest model), so the main model and its workers correct themselves step by step before delivering. Its report is untrusted by design: the main model triages every finding, verifies it itself or re-asks, and re-runs the reviewer after a fix.

## Goals · non-goals · anti-goals
- Goals: flag likely defects in what an action just changed — code (bugs, leaks, needless complexity, smells, missed optimizations), docs (owner's style rules, organization, spelling), file/folder layout against the project's conventions, image descriptions against the image and context; in hedged wording.
- Non-goals: fixing anything; approving anything; replacing tests, `/code-review`, `qa-engineer`, `doc-curator` or `security-reviewer` audits; PR or commit review.
- Anti-goals: confident wording that anchors other models; findings without evidence; nit floods; review loops that never end.

## Approach (owner picked A)
| | Approach | Trade-off |
|---|---|---|
| **A** | Worker agent + offload-policy row; the main model dispatches it after each reviewable action, in the background, in parallel with `check-runner` | Fits ADR 0007/0012/0013; needs eval measurement |
| B | A mod hook after every Edit/Write | Reviews half-done edits, costly, another moving part |
| C | A + a new skill holding per-domain checklists | Cleaner split, more context per cheap call |

A, reusing existing skills on demand (owner: supplementary skills only if they complement and do not overlap). No new skill in this change.

## Decisions
- Name `untrusted-reviewer`; read-only (Read, Grep, Glob, Bash for read-only commands; Skill for on-demand loading); `omitClaudeMd: true` like other read-only agents.
- Model Haiku, effort medium. Codex: the global pair (haiku, medium) becomes (gpt-6-luna, low) (owner, 2026-11-03; it also moves `researcher`'s Codex port to luna low, accepted).
- Seventh worker: `WORKERS` in `validate.py`, "Use proactively", `maxTurns`, row in `commands/offload.md`, row in `user-config/offload-policy.md`; ADR amending 0007 and 0012.
- Trigger: after an action that can and should be reviewed (several files created, a function or module written or changed, a doc section written, a deletion, an image described), not after trivial edits; dispatched in parallel with the checks; re-dispatched after the main model changes the same files again; stop after 2 rounds on the same change or when only nits remain.
- Brief from the main model: what changed (paths or the diff), the intent of the action, the owner's rules that apply (e.g. style A–D), what is already verified.
- Process: read the change and its immediate context; verify each suspicion with a tool (read, grep, a read-only command) before reporting (CRITIC, Huang et al.); load at most one matching existing skill when the change is in its domain (`refactoring`, `docs-principles`, `qa-principles`, `security-principles`, `ux-principles`, `prompt-engineering`).
- Report: findings ranked, each with category, severity `low | medium | high`, confidence, evidence (`file:line` quote or command output) and a suggested check; nits capped at 5; hedged wording ("creo", "es posible", "me ha parecido", "podría") in Spanish when the owner's language is Spanish, plain hedges in English otherwise; never "approved", never "safe".

## Evidence
Research 2026-11-03: self-correction without external feedback degrades (arXiv 2310.01798); tool-checked critique helps (CRITIC, arXiv 2305.11738); critics hallucinate bugs, humans+critic fewer (CriticGPT, arXiv 2407.00215); judge biases (arXiv 2306.05685, 2410.21819); Anthropic Code Review: find→verify, Normal/Nit/Pre-existing, nit cap, never approves (code.claude.com/docs/en/code-review-customize). Gap: no measured per-action vs per-diff comparison; no published re-review stop rule.

## Paradigm applied to this change
Research, pre-mortem and prompt-engineer review before writing; after implementing, the new agent reviews its own files and the main model triages its report.

## Left to the builder
Exact prompt (prompt-engineer draft), description wording (measured with the eval protocol: new `trigger/`/`offload-*` cases plus every `neg-*`), README catalog row, ports regenerated.

## Prompt draft (prompt-engineer, 2026-11-03)
Frontmatter: haiku · medium · tools Read, Grep, Glob, Bash, Skill · disallowedTools Edit, Write, NotebookEdit · maxTurns 20 · omitClaudeMd true. Body: inputs from the brief (stop if no paths or diff); read CLAUDE.md and nearest README for conventions; process read → checklist per change kind (code, docs, file/folder layout, deletion, image description) → verify each suspicion with a tool (unverified → drop or confidence `low` + what was not checked) → at most one skill; rules: hedge every finding (Spanish/English examples), never "approved/safe/LGTM/no issues", only what the change touched (`pre-existing` otherwise), nits ≤ 5 last, read-only commands only, stop after ~16 tool rounds; output ≤ 40 lines, table `# · Category · Severity · Confidence · Where · Evidence · Suggested check`, `Nits`, `Not checked`, one example.

## Amendments (pre-mortem, 2026-11-03) — required
| # | Amendment |
|---|---|
| A1 | Trigger floor: ≥ ~20 changed lines or ≥ 2 files, or any deletion (keeps `neg-tdd-green`-style single-function steps out) |
| A2 | Evals: `offload/untrusted-reviewer-with-policy` (dispatch after a ~60-line module) and a seeded-defect case (1 real bug + 1 clean file; bug found, ≤ 2 findings on the clean file) |
| A3 | Brief carries the round number and already-rejected findings; the reviewer stops at round 2 |
| A4 | A report about files changed after dispatch is stale: drop it, or re-dispatch once if under round 2 |
| A5 | Confidence uses `low | medium | high`; the main model verifies medium and high, skims low |
| A6 | The Codex pair change is its own commit, with ADR 0014 `## Review` and `docs/ports.md` / `port.py` comment updated |
| A7 | Coupled edits: `WORKERS`, CLAUDE.md "six" → "seven", neg graders naming every agent, `*-with-policy` cases embedding the policy verbatim, `commands/offload.md`, README catalog and Workers cell, `port.py`, `validate.py`; ADR amends 0007, 0010, 0012 |
| A8 | Eval budget per glob `--max-cost-usd 5`, recorded in the ADR |
| A9 | Description excludes PR/commit review and audits (qa-engineer, doc-curator, security-reviewer) |

## Kill criteria
Any `neg-*` drops ≥ 2/6 vs its record → revert the description commit; `with-policy` dispatch ≤ 1/3 with a Sonnet main → re-plan (hook or Stop reminder); seeded-defect bug missed ≥ 2/6 or > 2 false positives on the clean file → raise effort or re-plan; > 2 dispatches per change in a trace → tighten trigger; `researcher` on Codex returns without searching → pin it to its own Codex pair.
