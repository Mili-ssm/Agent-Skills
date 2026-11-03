# Proactive Dispatch Wording + README Install and Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `skeptical-reviewer` proactive dispatch with a turn-end rule, and give the README collapsible install guides plus a generated "recommended prompt" for agents and skills.

**Architecture:** Wording lives in `user-config/offload-policy.md` (single copy) and the agent description; `scripts/port.py` already ports the policy and gains a README block generator from `user-config/` sources.

**Tech Stack:** Markdown, Python 3 (`scripts/port.py`, `scripts/validate.py`), `claude plugin eval`.

**Spec:** `docs/superpowers/specs/2026-11-04-dispatch-and-readme-design.md`

## Global Constraints
- Generated files never edited by hand (`ports/**`, `user-config/offload-policy.{copilot,codex}.md`, the README generated block).
- One commit per description change (CLAUDE.md).
- Eval protocol: description change → trigger cases naming the agent, its `offload-*` cases, every `neg-*`; `--runs 3` Sonnet main here (owner wants a clear before/after).
- Owner: no hooks; recommended prompt covers only agents and skills.

## Review Focus
- `neg-*` cases (trivial edits, small TDD step) must stay silent after the turn-end rule.
- The README block regenerates byte-identically (`port.py --check` clean twice).
- `<details>` renders on GitHub: blank line after `<summary>…</summary>`.
- Copilot/Codex tool names in the routing table match the ports (`$skill`, `@agent`…), as port.py already maps.
- Policy text change propagates to every `*-with-policy` case (validate.py check).

---

### Task 1: Turn-end dispatch wording (prompt-engineer draft → apply → measure)

**Files:** Modify `user-config/offload-policy.md`, `plugins/agent-skills/agents/skeptical-reviewer.md` (description only), the `*-with-policy` cases (verbatim policy), regenerated ports.

- [ ] Step 1: prompt-engineer drafts the row and description sentence for the anchor "before your final answer, if you or a worker changed ≥ 2 files or ≥ 20 lines in this task, dispatch `skeptical-reviewer` and wait for its report" (keep ≤ 1024 chars, ADR 0007 vocabulary).
- [ ] Step 2: apply; `python3 scripts/port.py`; `python3 scripts/validate.py` → OK.
- [ ] Step 3: evals `*skeptical-reviewer-*` and each `neg-*` at `--runs 3`; compare with the 2026-11-04 baseline.
- [ ] Step 4: if with-policy rises and no `neg-*` drops ≥ 2/6, commit (one commit for the description); record numbers in ADR 0017 `## Measurement 2026-11-04`. Otherwise revert and report.

### Task 2: README install guides and generated recommended prompt

**Files:** Modify `README.md`, `docs/ports.md`, `scripts/port.py`, `scripts/validate.py` (only if needed for the check); Create `user-config/routing.md`.

**Interfaces — Produces:** README markers `<!-- BEGIN generated: recommended-prompt -->` / `<!-- END generated: recommended-prompt -->`; `port.py` writes three `<details>` (Claude Code, GitHub Copilot CLI, OpenAI Codex), each the tool's offload policy + the routing table ported to that tool's names; `port.py --check` fails on a stale block.

- [ ] Step 1: `user-config/routing.md` — generic need → skill/agent/command table from the owner's routing section (no personal rules).
- [ ] Step 2: README `## Install` becomes three `<details>` blocks; Copilot/Codex install steps move from `docs/ports.md` (which links back).
- [ ] Step 3: port.py generator + `--check`; run twice, second run reports no change.
- [ ] Step 4: `python3 scripts/validate.py`, `claude plugin validate .` → OK; commit.
