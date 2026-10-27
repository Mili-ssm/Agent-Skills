# Requirements

Current as of 2026-10-27. Source: owner conversation. Change via PR + ADR when a requirement flips.

## Context

| Item | Value |
|---|---|
| Owner stack | Python, Rust; fullstack FastAPI + htmx, minimal JS |
| Runtime | Claude Code (cloud) with Superpowers + Playwright installed |
| Repo role | Plugin of generic skills/agents complementing both |

## Functional

| ID | Requirement |
|---|---|
| R1 | Skills/agents are stack-agnostic; stack-specific ones are deferred (see Out of scope). |
| R2 | Specialist agents (architecture, QA, UX/UI, docs, security) cite recognized principles, patterns and terminology, and justify findings with them. |
| R3 | Docs work optimizes for concision and semantic density; bloat is a defect, not a style choice. |
| R4 | Intent work infers intent from code + docs, interviews the owner until no material ambiguity remains, and flags ambiguous, inconsistent and stale decisions with a revisit rating. Applies to whole projects, features and significant changes. |
| R5 | Complement Superpowers; never duplicate its process skills (table below). |

## Non-functional

| ID | Requirement |
|---|---|
| N1 | `SKILL.md` ≤ 150 lines, agent ≤ 120 lines; detail lives in `references/`, loaded on demand. |
| N2 | Every description states its trigger ("Use when…"). |
| N3 | No fabricated precision: rubrics (low/medium/high + evidence), never invented percentages. |
| N4 | Findings carry evidence (`file:line`, command output, screenshot). |
| N5 | `scripts/validate.py` passes before every commit. |

## Superpowers boundary

| Superpowers owns | This repo adds |
|---|---|
| `brainstorming` (new designs) | `intent-elicitation` + `consistency-auditor` (existing code/docs) |
| `writing-plans` / `executing-plans` | `pre-mortem` (attacks the plan before execution) |
| `test-driven-development` (when to test) | `qa-engineer` (what to test, test quality) |
| `requesting-code-review` (general) | `architect`, `security-reviewer`, `ux-reviewer` (specialist lenses) |
| `systematic-debugging` | `performance-analyst` (measured optimization) |
| `writing-skills` | Used to author this repo |

## Out of scope (now)

- Stack skills: `htmx-fastapi-hypermedia`, `htmx-e2e-playwright`, `python-project`, `rust-project`, `pyo3-maturin`.
- Hooks (ruff/cargo formatting, JS budget guard).
