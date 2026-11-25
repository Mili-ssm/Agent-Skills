# Requirements

Current as of 2026-11-15. Source: owner conversations and `intent-elicitation` interviews (2026-10-27, 2026-11-15). Goals are hard: one changes only by the owner's decision, with a PR and an ADR. A row marked hard restates a goal and changes with it; every other row is a means and is soft: its "Reopen when" column names what would reopen it (ADR 0020).

## Context

| Item | Value |
|---|---|
| Owner stack | Python, Rust; fullstack FastAPI + htmx, minimal JS |
| Runtime | Claude Code (local and cloud) with Superpowers and Playwright (CLI/MCP plugin and Python library) |
| Repo role | Marketplace: a plugin of generic skills and agents that works with both, a memory plugin (ADR 0023), opt-in UI mods (ADR 0011) and generated Copilot/Codex ports of the skills-and-agents plugin (ADR 0015) |
| Audience | Public: the owner and fewer than ten other users (2026-11-19); MIT license; releases from `main` with a version and changelog per plugin (ADR 0027); paths users rely on are a contract (ADR 0026) |

## Goals (functional, hard)

| ID | Goal |
|---|---|
| G1 | The main conversation decides, integrates and talks to the owner; reading, running checks, browser verification and bounded code go to cheaper models. |
| G2 | Nothing is reported as done without evidence of the result and a review by a fresh context. |
| G3 | Work longer than one context survives a compaction, and the owner can see where it stands. |
| G4 | Before a broad or hard-to-reverse change, intent is recovered from code and docs and confirmed with the owner. |
| G5 | Each specialist finding cites a named principle, pattern, law or standard, and its evidence. |
| G6 | Documentation keeps rationale, constraints and gotchas, and drops what is derivable or duplicated. |
| G7 | For one task, this plugin and Superpowers give one instruction, never two that contradict. |
| G8 | A change to the plugin does not make the owner's current results worse. |

## Functional

Kind: functional (states a goal) or technical (a chosen means); hard or soft as defined above.

| ID | Requirement | Serves | Kind | Reopen when |
|---|---|---|---|---|
| R1 | Skills and agents shall state generic methods; Python, Rust and htmx may appear as examples and tooling, and owner preferences (minimal JS, progressive enhancement) shall be labeled as configurable defaults. Stack-specific skills are deferred. | none stated | technical, soft | Others use the plugin, or a stack skill leaves "Out of scope" |
| R2 | Specialist agents (architecture, QA, UX/UI, docs, security, performance) shall justify each finding with a named principle, pattern, law or standard. | G5 | functional, hard | — |
| R3 | Docs work shall remove every sentence that is derivable from code or duplicated elsewhere, while keeping rationale, constraints and gotchas. | G6 | functional, hard | — |
| R4 | When intent is unclear, the plugin shall infer it from code and docs, interview the owner until each high-impact finding is resolved or explicitly deferred, and rate stale decisions with the staleness rubric; for projects, features and significant changes. | G4 | functional, hard | — |
| R5 | Where this plugin and Superpowers cover the same task, the routing text shall name the one that applies and what the other contributes (table below, ADR 0019). | G7 | functional, hard; the table is technical, soft | A Superpowers update changes a skill the table names |
| R6 | The model shall load this plugin's skills and dispatch its agents when the task matches, without the owner naming them; the skills that interview the owner and the two costliest agents, `architect` and `security-reviewer`, keep a narrower trigger (ADR 0022). | none stated | functional, soft (owner preference, 2026-11-15) | The owner makes it a goal, or unasked dispatches raise cost |

## Non-functional

| ID | Requirement | Serves | Kind | Reopen when |
|---|---|---|---|---|
| N1 | `SKILL.md` ≤ 150 lines, agent ≤ 120 lines; detail in `references/` one level deep, `## Contents` above 100 lines. | G1 | technical, soft | A measured case shows a longer file is followed as well |
| N2 | Descriptions: third person, what it does, then "Use when…" with the user's likely terms, ≤ 1024 chars; quoted user phrases are not the description speaking (straight or curly double quotes, at most 60 characters, no `.`, `!` or `?` inside; `QUOTED` in `scripts/validate.py`). | G8 | technical, soft | Trigger evals regress after a model change (ADR 0007) |
| N3 | Ratings use levels with written criteria, never invented percentages. | G5 | technical, soft | Calibrated data exists (ADR 0004) |
| N4 | Findings carry evidence (`file:line`, command output, screenshot). | G2, G5 | functional, hard | — |
| N5 | `scripts/validate.py` passes before every commit (no CI; owner, 2026-11-24). An opt-in local `pre-push` hook runs it (CLAUDE.md § Commands). | G8 | technical, soft | The plugins have a reasonable number of users (owner, 2026-11-19: CI waits until then; GitHub Actions on standard runners costs no minutes in a public repository) |
| N6 | Changes to a skill or agent `description` and to `user-config/offload-policy.md` are measured with `claude plugin eval` (trigger and no-trigger cases) against the previous version. Any other prompt change may ship labeled unmeasured, with a kill criterion in its ADR. | G8 | technical, soft | An unmeasured change is reverted for regressing in use |
| N7 | Agents whose description says "Read-only" block Edit, Write and NotebookEdit via `disallowedTools`, not via prompt text. | G2 | technical, soft | The platform offers a stronger read-only mode |
| N8 | Every specialist agent and the UX design workflow have an explicit user-only command; workers are forced with `/agent-skills:offload` (ADR 0012); auto-triggering is a bonus. | G8 | technical, soft | A command needs maintenance, or the owner starts typing them (kept unused, owner 2026-11-15, ADR 0022) |
| N9 | Reading, checks, browser verification and bounded implementation shall be offloadable to Haiku/Sonnet workers; delegation is measured with `evals/offload`. | G1 | functional, hard; the model names are technical, soft | Model tiers or prices change |
| N10 | A worker's brief carries what only the main conversation knows: goal and acceptance, scope and what not to touch, decisions with their reasons, checks, a stop rule, report bounds; tasks with open design are not delegated (ADR 0013). Measured on the `implementer` offload case. | G1, G8 | technical, soft | Subagents can see the conversation or ask the owner |
| N11 | Navigation of long files costs no model tokens to compute: `outline.py` prints line ranges on demand and nothing stores line numbers; `summarizer` returns answers, outlines or verbatim extracts and `check-runner` runs any long read-only command, so raw text stays out of the main context (ADR 0014). | G1 | technical, soft | The harness provides outlines natively |

## Superpowers boundary

Decided 2026-11-15 (ADR 0019); it applies R5. Evidence, the seams still open and how to recheck after a Superpowers update: [superpowers-seams.md](superpowers-seams.md). The text that steers a session is `user-config/routing.md`.

| Need | Superpowers supplies | This repo supplies |
|---|---|---|
| New design | `brainstorming` | `intent-elicitation` + `consistency-auditor` for existing code and docs; `feature-briefing` for evidence, options and the decision |
| Plan | `writing-plans`, the only plan writer | `change-impact` before the plan, `pre-mortem` after it, `plan-progress` to show it |
| Plan execution | `subagent-driven-development` as the loop: order, ledger, one task at a time | `implementer` and `skeptical-reviewer` in its two subagent roles; `check-runner` |
| Review | `receiving-code-review` (how to treat findings) | `skeptical-reviewer` after every change; `architect`, `security-reviewer`, `ux-reviewer`, `qa-engineer`, `doc-curator` as specialist lenses; `fact-checker` |
| Proof of done | `verification-before-completion` (the principle) | `check-runner` and `ui-verifier` produce the evidence; a PASS that names its command and result counts |
| Defects | `systematic-debugging` (root cause) | `fixer` for mechanical errors; `performance-analyst` for measured optimization |
| Tests | `test-driven-development` (when to test) | `qa-engineer` / `qa-principles` (what to test, test quality) |
| Branch work | `using-git-worktrees`, `finishing-a-development-branch` | `release-hygiene` |
| Authoring | `writing-skills` (process, TDD for skills) | `prompt-engineering`: Claude-specific wording, description, tool, per-model and eval rules it does not cover |

No routing row names `executing-plans`, `requesting-code-review` or `dispatching-parallel-agents`: this repo's agents cover their work. They stay installed and are not blocked (owner, 2026-11-15).

## Out of scope (now)

- Stack skills: `htmx-fastapi-hypermedia`, `htmx-e2e-playwright`, `python-project`, `rust-project`, `pyo3-maturin`.
- CI (would enforce N5); a mandatory git hook (the pre-push hook is opt-in).

## Open questions

| Item | Revisit trigger |
|---|---|
| Rename skills to one naming pattern (gerunds) | Next breaking reorganization (ADR 0007) |
| Extract `performance-principles` from `performance-analyst` | A second consumer of that catalog appears |
| Re-measure trigger and offload figures with the current main model | A measured text changes (ADR 0020) |

Closed 2026-11-19: the license (MIT, ADR 0027); `plan-progress`'s dependency on the plan format, now stated in its README; the `Explore` override, installed at the owner's user scope.
