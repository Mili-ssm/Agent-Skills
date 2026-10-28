# agent-skills

Marketplace `mili-ssm` with one plugin and opt-in mods, each installed on its own (ADR 0011):

| Plugin | What | Folder |
|---|---|---|
| `agent-skills` | Specialist skills and agents (below) | [`plugins/agent-skills/`](plugins/agent-skills/) |
| `agents-pane` (mod) | Side pane: subagents with type, model, status, duration, per-model tally; `/agents-pane` reopens it | [`plugins/agents-pane/`](plugins/agents-pane/) |
| `status-model` (mod) | Status line: `opus-5-5 │ 1 running │ last: researcher → haiku-5-5 ✓ 12s` | [`plugins/status-model/`](plugins/status-model/) |
| `usage-band` (mod) | Band above the prompt: last answer's duration and tokens per model (subagents included), session totals; `/usage-band` shows it after Hide | [`plugins/usage-band/`](plugins/usage-band/) |
| `plan-progress` (mod) | Side pane: active plan (`docs/superpowers/plans/`, `docs/plans/`, `plans/`), progress bar, current task, steps per task, toast per finished task; `/plan-progress [path\|auto]` | [`plugins/plan-progress/`](plugins/plan-progress/) |

`agents-pane`, `status-model` and `usage-band` make offloading to Haiku/Sonnet and its cost visible (ADR 0010); `plan-progress` tracks Superpowers plans.

## agent-skills

Generic specialist skills and agents for Claude Code. Complements [Superpowers](https://github.com/obra/superpowers) (process) and Playwright (browser): adds professional lenses — architecture, QA, UX/UI, docs, requirements, security, performance. Personal plugin of its owner (ADR 0008).

## Install

| Where | How |
|---|---|
| Local session | `/plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Local shell | `claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Cloud environment | Paste [`scripts/cloud-setup.sh`](scripts/cloud-setup.sh) as the environment's setup script (cloud sessions ignore plugins declared in a repo) |
| Older Claude Code | `/plugin marketplace add Mili-ssm/Agent-Skills`, then `/plugin install agent-skills@mili-ssm` |
| A mod | Same commands with the mod's name; in cloud set `AGENT_SKILLS_MODS="agents-pane status-model usage-band plan-progress"` in the environment |

## Offload setup (ADR 0010)

The cloud script does this; locally run it once:

```bash
# Explore on Haiku (overrides the built-in, which uses the main model)
mkdir -p ~/.claude/agents && cp user-agents/Explore.md ~/.claude/agents/
# Subagents without their own model run on Sonnet
# add to ~/.claude/settings.json: "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}
```

Then add the offload trigger table to `~/.claude/CLAUDE.md`: in evals it raised worker delegation from 0–2/3 to 3/3.

## Update

No pinned version (ADR 0006): every commit on the default branch is a new version.

| Method | Command |
|---|---|
| Manual (shell) | `claude plugin marketplace update mili-ssm && claude plugin update agent-skills@mili-ssm` (same for each mod), then `/reload-plugins` or a new session. `plugin update` alone does not refresh the marketplace copy |
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
| `consistency-auditor` | Infer intent; find contradictions, stale/implicit decisions | decision-records | sonnet | no |
| `security-reviewer` | Source→sink review, threat model | security-principles | opus | no |
| `pre-mortem` | Attack a plan before execution | — | opus | no |
| `researcher` | Offloaded web research, one question, cited | web-research | haiku | no |
| `check-runner` | Run tests/lint/typecheck/build; return failures only | — | haiku | no |
| `summarizer` | Read long logs/docs/PDFs/diffs; answer one question | — | haiku | no |
| `implementer` | Apply one bounded plan task with acceptance | — | sonnet | yes |
| `fixer` | Loop on mechanical lint/type/test fixes | — | sonnet | yes |
| `performance-analyst` | Measure, profile, optimize | — | sonnet | when asked |

### Skills

| Skill | Kind | Use when |
|---|---|---|
| `intent-elicitation` | Workflow (interactive) | Intent/requirements unclear; interviews owner, records answers |
| `feature-briefing` | Workflow (orchestrator) | Plan a new feature: brainstorm → parallel evidence → decision → plan → pre-mortem |
| `web-research` | Workflow | Fan out cheap researchers; get cited findings |
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
| `/agent-skills:research <question>` | parallel `researcher` (Haiku) |
| `/agent-skills:brief <feature>` | `feature-briefing` workflow |
| `/agent-skills:offload <task>` | Cheapest suitable worker |

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
- Layout: one marketplace, each plugin in `plugins/<name>/`.
- ADRs: knowledge in skills, roles in agents (0001) · dense English (0002) · interactive work in skills (0003) · rubrics, not percentages (0004) · track commits (0006) · Anthropic authoring conventions + evals (0007) · install paths and audience (0008, supersedes 0005) · research offload + briefing orchestration (0009) · cheap offload workers (0010) · marketplace with independent mods (0011).

## Develop

| Step | Command |
|---|---|
| Validate structure and authoring rules | `python3 scripts/validate.py` and `claude plugin validate .` |
| Measure triggering (before/after any description or prompt change) | `claude plugin eval plugins/agent-skills --ablation none --model sonnet -j 4` |
| Validate and test a mod | `claude plugin validate plugins/<mod>` and `claude plugin test plugins/<mod>` |
| Type-check a mod | `claude --plugin-dir plugins/<mod>` once (lays its types and tsconfig, git-ignored), then `tsc -p plugins/<mod>` |

`plugins/agent-skills/evals/trigger/*` expect the matching skill (or the agent that preloads it) to fire; `evals/no-trigger/*` expect no plugin skill or agent. `evals/offload/*` expect delegation to a worker (need `--scaffold --allow-tools Bash` and a sandbox: `bubblewrap`, `socat`).
