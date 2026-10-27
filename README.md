# agent-skills

Generic specialist skills and agents for Claude Code. Complements [Superpowers](https://github.com/obra/superpowers) (process) and Playwright (browser): adds professional lenses — architecture, QA, UX/UI, docs, requirements, security, performance. Personal plugin of its owner (ADR 0008).

## Install

| Where | How |
|---|---|
| Local session | `/plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Local shell | `claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Cloud environment | Paste [`scripts/cloud-setup.sh`](scripts/cloud-setup.sh) as the environment's setup script (cloud sessions ignore plugins declared in a repo) |
| Older Claude Code | `/plugin marketplace add Mili-ssm/Agent-Skills`, then `/plugin install agent-skills@mili-ssm` |

## Update

No pinned version (ADR 0006): every commit on the default branch is a new version.

| Method | Command |
|---|---|
| Manual (shell) | `claude plugin marketplace update mili-ssm && claude plugin update agent-skills@mili-ssm`, then `/reload-plugins` or a new session. `plugin update` alone does not refresh the marketplace copy |
| Manual (session) | `/plugin` → Marketplaces → `mili-ssm` → Update marketplace (refreshes and updates) |
| Automatic | `/plugin` → Marketplaces → `mili-ssm` → Enable auto-update (the cloud script enables it) |

## Catalog

### Agents (fresh context, return a report)

| Agent | Use when | Preloads | Model | Writes? |
|---|---|---|---|---|
| `architect` | Assess/review/propose architecture | architecture-principles, decision-records | opus | no |
| `qa-engineer` | Test strategy, gaps, case design, flaky tests, mutation | qa-principles | sonnet | when asked |
| `ux-reviewer` | Usability + accessibility audit with screenshots/axe | ux-principles | sonnet | no |
| `doc-curator` | Verify and compress docs and prompts | docs-principles, decision-records | sonnet | when asked |
| `consistency-auditor` | Infer intent; find contradictions, stale/implicit decisions | decision-records | opus | no |
| `security-reviewer` | Source→sink review, threat model | security-principles | opus | no |
| `pre-mortem` | Attack a plan before execution | — | opus | no |
| `performance-analyst` | Measure, profile, optimize | — | sonnet | when asked |

### Skills

| Skill | Kind | Use when |
|---|---|---|
| `intent-elicitation` | Workflow (interactive) | Intent/requirements unclear; interviews owner, records answers |
| `change-impact` | Workflow | Before a significant change: blast radius, migration, rollback |
| `refactoring` | Workflow | Behavior-preserving restructuring |
| `decision-records` | Knowledge | ADRs and staleness rubric |
| `docs-principles` | Knowledge | Docs, CLAUDE.md, skills and prompts (incl. Anthropic authoring guidance) |
| `architecture-principles` | Knowledge | Principles, software laws, patterns, smells, evaluation |
| `qa-principles` | Knowledge | Test design, strategy, test quality |
| `ux-principles` | Knowledge + script | Heuristics, laws, WCAG, visual system, `ux_audit.py` |
| `security-principles` | Knowledge | STRIDE, OWASP/ASVS, language specifics |
| `api-design` | Knowledge | HTTP/JSON/hypermedia contracts |
| `observability` | Knowledge | Logs, metrics, traces, SLOs |
| `release-hygiene` | Knowledge | Commits, SemVer, changelog, releases |

### Commands (explicit, user-only)

Every skill is also invocable as `/agent-skills:<skill>`. Agents get explicit commands, which never auto-trigger and cost no context per turn:

| Command | Runs |
|---|---|
| `/agent-skills:ux-design <feature>` | `ux-principles` design workflow → spec + Playwright acceptance checks |
| `/agent-skills:ux-review <url>` | `ux-reviewer` |
| `/agent-skills:arch-review [mode] [scope]` | `architect` |
| `/agent-skills:qa-review [mode] [scope]` | `qa-engineer` |
| `/agent-skills:security-audit [mode] [scope]` | `security-reviewer` |
| `/agent-skills:doc-audit [audit\|apply] [paths]` | `doc-curator` |
| `/agent-skills:consistency-audit [mode] [scope]` | `consistency-auditor` |
| `/agent-skills:premortem [plan]` | `pre-mortem` |
| `/agent-skills:perf-review <target>` | `performance-analyst` |

## Workflow with Superpowers

```text
intent-elicitation ──► brainstorming ──► change-impact ──► writing-plans ──► pre-mortem
   (consistency-auditor)                                                        │
                                                                                ▼
finishing-a-branch ◄── security-reviewer / ux-reviewer / architect ◄── executing (TDD + qa-engineer)
        │
        └─► doc-curator + decision-records + release-hygiene
```

## Design

- Requirements: [`docs/requirements.md`](docs/requirements.md) · Decisions: [`docs/adr/`](docs/adr/)
- ADRs: knowledge in skills, roles in agents (0001) · dense English (0002) · interactive work in skills (0003) · rubrics, not percentages (0004) · track commits (0006) · Anthropic authoring conventions + evals (0007) · install paths and audience (0008, supersedes 0005).

## Develop

| Step | Command |
|---|---|
| Validate structure and authoring rules | `python3 scripts/validate.py` and `claude plugin validate .` |
| Measure triggering (before/after any description or prompt change) | `claude plugin eval . --ablation none --model sonnet -j 4` |

`evals/trigger/*` expect the matching skill (or the agent that preloads it) to fire; `evals/no-trigger/*` expect no plugin skill or agent.
