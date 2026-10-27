# agent-skills

Generic specialist skills and agents for Claude Code. Complements [Superpowers](https://github.com/obra/superpowers) (process) and Playwright (browser): adds professional lenses — architecture, QA, UX/UI, docs, requirements, security, performance.

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

| Agent | Use when | Preloads | Model |
|---|---|---|---|
| `architect` | Assess/review/propose architecture | architecture-principles, decision-records | opus |
| `qa-engineer` | Test strategy, gaps, case design, flaky tests, mutation | qa-principles | sonnet |
| `ux-reviewer` | Usability + accessibility audit with screenshots/axe | ux-principles | sonnet |
| `doc-curator` | Verify and compress documentation | docs-principles, decision-records | sonnet |
| `consistency-auditor` | Infer intent; find contradictions, stale/implicit decisions | decision-records | opus |
| `security-reviewer` | Source→sink review, threat model | security-principles | opus |
| `pre-mortem` | Attack a plan before execution | — | opus |
| `performance-analyst` | Measure, profile, optimize | — | sonnet |

### Skills

| Skill | Kind | Use when |
|---|---|---|
| `intent-elicitation` | Workflow (interactive) | Intent/requirements unclear; interviews owner, records answers |
| `change-impact` | Workflow | Before a significant change: blast radius, migration, rollback |
| `refactoring` | Workflow | Behavior-preserving restructuring |
| `decision-records` | Knowledge | ADRs and staleness rubric |
| `docs-principles` | Knowledge | Writing/reviewing docs, CLAUDE.md, skills |
| `architecture-principles` | Knowledge | Principles, patterns, smells, evaluation |
| `qa-principles` | Knowledge | Test design, strategy, test quality |
| `ux-principles` | Knowledge + script | Heuristics, laws, WCAG, visual system, `ux_audit.py` |
| `security-principles` | Knowledge | STRIDE, OWASP/ASVS, language specifics |
| `api-design` | Knowledge | HTTP/JSON/hypermedia contracts |
| `observability` | Knowledge | Logs, metrics, traces, SLOs |
| `release-hygiene` | Knowledge | Commits, SemVer, changelog, releases |

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
- Knowledge in skills, roles in agents (ADR 0001); dense English, budgets enforced (ADR 0002); interactive work in skills (ADR 0003); rubrics, not percentages (ADR 0004).
- Validate before committing: `python3 scripts/validate.py` (and `claude plugin validate .`).
