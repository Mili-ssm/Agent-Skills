# 0017 Skeptical after-action reviewer, Codex pair for Haiku medium

Status: accepted · Date: 2026-11-03 · Amends 0007, 0010, 0012, 0014

## Context

`pre-mortem` stress-tests plans before the work; nothing reviews what an action just produced before it is delivered. Tests cover correctness, so the weak spots that owners or users find later are quality ones: needless complexity, a wrong data structure, a design or UX/UI pattern violated, poor organization, unclear names or text. Research 2026-11-03: self-correction without external feedback degrades (arXiv 2310.01798); tool-checked critique helps (CRITIC, arXiv 2305.11738); critics hallucinate bugs (CriticGPT, arXiv 2407.00215); judges are biased (arXiv 2306.05685, 2410.21819). Design: `docs/superpowers/specs/2026-11-03-skeptical-reviewer-design.md`.

## Decision

- Renamed 2026-11-03 from `untrusted-reviewer` to `skeptical-reviewer`: "untrusted" read as the opposite of the intent, a reviewer that distrusts the work.
- New seventh worker `skeptical-reviewer` (Haiku, effort medium, read-only, `maxTurns` 20, `omitClaudeMd: true`, `Skill` to load at most one existing skill). Its report is untrusted: hedged wording, evidence per finding, never an approval; the caller triages, verifies medium and high findings, and skims low ones.
- Focus (owner refinement): quality of what is about to be delivered, ranked by how much fixing it would improve the delivery, then by confidence; obvious bugs are listed with the rest; nits ≤ 5.
- Trigger: at least ~20 changed lines or 2 files, or any deletion; also a doc section or an image description. Dispatched in the background with `check-runner`. The brief carries the round number and the findings already rejected; the reviewer stops at round 2; a report about files changed after dispatch is stale.
- Coupled edits: `WORKERS` in `validate.py`, "seven workers" in CLAUDE.md, offload row and policy row, the `*-with-policy` cases (verbatim policy), the `neg-*` graders that name every agent, README catalog and Workers cell. ADR 0007 and 0010's "Use proactively" exception now covers seven workers; 0012's single-copy policy gains a row.
- Codex pair: `("haiku", "medium")` becomes `("gpt-6-luna", "low")` in `scripts/port.py` (owner, 2026-11-03). The change is global, so it also moves `researcher`'s Codex port to luna low. ADR 0014's early-stop risk (low effort stopping early) is watched. It is its own commit (`port.py`, `docs/ports.md`, regenerated `ports/`).
- Evals (owner exception to N6, 2026-11-03): only the new agent's cases run, `offload/skeptical-reviewer-with-policy` (dispatch after a ~60-line module across two files) and `offload/skeptical-reviewer-quality` (a working module with a list scanned inside a loop where a set fits, plus a clean file). The existing `neg-*` and other `*-with-policy` suites are not re-run by owner decision, although the new description and policy row could move them (the eval protocol lists every `neg-*` for an agent description): **unmeasured** for those suites, with the kill criterion below. Budget per glob `--max-cost-usd 5`. The quality case grades the main model's relay of the report and the trace, not the subagent's report itself.

## Alternatives

| Option | Rejected because |
|---|---|
| Hook after every Edit/Write | Reviews half-done edits, costs more, adds a moving part |
| Worker plus a new checklist skill | More context per cheap call; existing skills already cover each domain |
| Bug-hunt focus | Tests cover correctness; critics hallucinate bugs; the owner wants early quality alerts |
| Keep luna medium for Haiku medium | The owner accepted luna low for cost |

## Consequences

- One more row in the offload table: every session loads a few more tokens, and the main model may dispatch too often (watch the trace).
- Reviewer findings can be wrong or anchoring; the triage rule and hedged wording limit that cost, they do not remove it.
- `researcher` on Codex runs at luna low; it may stop before searching.

## Revisit if

Measured numbers for the two cases exist (record them in `## Measurement YYYY-MM-DD`), a model change alters Haiku's routing, or the reviewer's false-positive rate in real use makes the owner stop reading its reports.

### Kill criteria

| Signal | Action |
|---|---|
| Any routing oddity in traces (an unrelated agent fires, or a skill stops firing) | Run the `neg-*` suite and compare with the ADR 0007 records |
| `skeptical-reviewer-with-policy` dispatch ≤ 1/3 with a Sonnet main | Re-plan: hook or Stop reminder |
| Quality case misses the seeded point in ≥ 2/6 runs, or > 2 findings on the clean file | Raise effort or re-plan |
| More than 2 dispatches per change in a trace | Tighten the trigger floor |
| `researcher` on Codex returns without searching | Pin it to its own Codex pair |
