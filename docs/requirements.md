# Requirements

Current as of 2026-10-27. Source: owner conversation and `intent-elicitation` interview. A flipped requirement needs a PR + ADR.

## Context

| Item | Value |
|---|---|
| Owner stack | Python, Rust; fullstack FastAPI + htmx, minimal JS |
| Runtime | Claude Code (local and cloud) with Superpowers and Playwright (CLI/MCP plugin and Python library) |
| Repo role | Plugin of generic skills/agents complementing both |
| Audience | Owner only for now; no license (ADR 0008) |

## Functional

| ID | Requirement |
|---|---|
| R1 | Skills and agents shall state generic methods; Python, Rust and htmx may appear as examples and tooling, and owner preferences (minimal JS, progressive enhancement) shall be labeled as configurable defaults. Stack-specific skills are deferred. |
| R2 | Specialist agents (architecture, QA, UX/UI, docs, security, performance) shall justify each finding with a named principle, pattern, law or standard. |
| R3 | Docs work shall remove every sentence that is derivable from code or duplicated elsewhere, while keeping rationale, constraints and gotchas. |
| R4 | When intent is unclear, the plugin shall infer it from code and docs, interview the owner until each high-impact finding is resolved or explicitly deferred, and rate stale decisions with the staleness rubric; for projects, features and significant changes. |
| R5 | The plugin shall complement Superpowers and not duplicate its process skills (table below). |

## Non-functional

| ID | Requirement |
|---|---|
| N1 | `SKILL.md` ≤ 150 lines, agent ≤ 120 lines; detail in `references/` one level deep, `## Contents` above 100 lines. |
| N2 | Descriptions: third person, what it does, then "Use when…" with the user's likely terms, ≤ 1024 chars. |
| N3 | Ratings use levels with written criteria, never invented percentages. |
| N4 | Findings carry evidence (`file:line`, command output, screenshot). |
| N5 | `scripts/validate.py` passes before every commit (not yet enforced by CI or hook). |
| N6 | Description or prompt changes are measured with `claude plugin eval` (trigger + no-trigger cases) against the previous version. |
| N7 | Reviewer agents are read-only via `disallowedTools`, not via prompt text. |
| N8 | Every agent and the UX design workflow have an explicit user-only command; auto-triggering is a bonus. |

## Superpowers boundary

| Superpowers owns | This repo adds |
|---|---|
| `brainstorming` (new designs) | `intent-elicitation` + `consistency-auditor` (existing code/docs) |
| `writing-plans` / `executing-plans` | `change-impact` (before the plan), `pre-mortem` (attacks the plan) |
| `test-driven-development` (when to test) | `qa-engineer` / `qa-principles` (what to test, test quality) |
| `requesting-code-review` (general) | `architect`, `security-reviewer`, `ux-reviewer` (specialist lenses) |
| `systematic-debugging` | `performance-analyst` (measured optimization) |
| `writing-skills` (authoring process, TDD for skills) | `prompt-authoring.md`: Claude-specific wording, description and eval rules it does not cover |

## Out of scope (now)

- Stack skills: `htmx-fastapi-hypermedia`, `htmx-e2e-playwright`, `python-project`, `rust-project`, `pyo3-maturin`.
- Hooks and CI (would enforce N5).

## Open questions

| Item | Revisit trigger |
|---|---|
| Rename skills to one naming pattern (gerunds) | Next breaking reorganization (ADR 0007) |
| Extract `performance-principles` from `performance-analyst` | A second consumer of that catalog appears |
