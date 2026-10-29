# agent-skills

Marketplace `mili-ssm` with one plugin and opt-in mods, each installed on its own (ADR 0011):

| Plugin | What | Docs |
|---|---|---|
| `agent-skills` | Specialist skills, agents and offload workers (below) | [Catalog](#catalog), [`plugins/agent-skills/`](plugins/agent-skills/) |
| `usage-band` (mod) | Status line per prompt cycle: busy time, calls, skills, agents, current step; Haiku conclusion | [README](plugins/usage-band/README.md) |
| `plan-progress` (mod) | While a plan exists: progress status line, card above the prompt, task toasts | [README](plugins/plan-progress/README.md) |
| `tool-fold` (mod) | Folds tool, skill and agent calls into one line each; running agents get a live card | [README](plugins/tool-fold/README.md) |

`tool-fold` and `usage-band` make offloading to Haiku/Sonnet and its cost visible (ADR 0010); `plan-progress` tracks Superpowers plans; `tool-fold` also keeps tool output out of the way until asked for.

## agent-skills

Generic specialist skills and agents (architecture, QA, UX/UI, docs, requirements, security, performance) and cheap offload workers that complement Superpowers and Playwright.

[Superpowers](https://github.com/obra/superpowers) owns process and Playwright the browser; this plugin adds the professional lenses and the workers. Personal plugin of its owner (ADR 0008).

## Install

| Where | How |
|---|---|
| Local session | `/plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Local shell | `claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Cloud environment | Paste [`scripts/cloud-setup.sh`](scripts/cloud-setup.sh) as the environment's setup script (cloud sessions ignore plugins declared in a repo) |
| Desktop app (`/plugin` does not run there) | **+** next to the prompt box → Plugins → Add marketplace `Mili-ssm/Agent-Skills` → Add plugin; or install from a shell at user scope (above), which the app's local sessions also load |
| VS Code extension | Install from a shell at user scope (above): the extension runs Claude Code on the same `~/.claude` config |
| Older Claude Code | `/plugin marketplace add Mili-ssm/Agent-Skills`, then `/plugin install agent-skills@mili-ssm` |
| A mod | Same commands with the mod's name; in cloud set `AGENT_SKILLS_MODS="tool-fold usage-band plan-progress"` in the environment |

## Offload setup (ADR 0010)

The cloud script does this; locally run it once:

```bash
# Explore on Haiku (overrides the built-in, which uses the main model)
mkdir -p ~/.claude/agents && cp user-agents/Explore.md ~/.claude/agents/
# Subagents without their own model run on Sonnet
# add to ~/.claude/settings.json: "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}
```

Then add the offload table to `~/.claude/CLAUDE.md`: copy it from [`user-config/offload-policy.md`](user-config/offload-policy.md) (single source, ADR 0012). In evals it raised worker delegation from 0–2/3 to 3/3; without it, force a worker per task with `/agent-skills:offload <task>`.

The cloud script can write the table for you: with `AGENT_SKILLS_OFFLOAD_POLICY=1` it writes it between two marker comments in `~/.claude/CLAUDE.md` and replaces that block on every run, so updates apply. It is off by default because account-level preferences may already carry the table, and a second copy costs context twice.

## Update

No pinned version (ADR 0006): every commit on the default branch is a new version.

| Method | Command |
|---|---|
| Manual (shell) | `claude plugin marketplace update mili-ssm && claude plugin update agent-skills@mili-ssm` (same for each mod), then `/reload-plugins` or a new session. `plugin update` alone does not refresh the marketplace copy |
| Manual (session) | `/plugin` → Marketplaces → `mili-ssm` → Update marketplace (refreshes and updates) |
| Automatic | `/plugin` → Marketplaces → `mili-ssm` → Enable auto-update (the cloud script enables it) |

## Catalog

### Which entry point

| Entry point | Starts when | Use it for |
|---|---|---|
| Commands `/agent-skills:<name>` | You type one; they never auto-trigger | A specialist review or workflow when you decide |
| Skills | Their description matches the task, a bonus that can stay silent; force one with its command | Methods and knowledge applied while you work |
| Workers | The [offload policy](user-config/offload-policy.md) is in your `CLAUDE.md`, or you force one with `/agent-skills:offload <task>` | Reading, checks, browser verification and bounded edits on Haiku/Sonnet: `check-runner`, `summarizer`, `researcher`, `implementer`, `fixer`, `ui-verifier` (plus user-scope `Explore`) |
| Superpowers | Its own triggers | Process: brainstorming, plans, TDD, debugging, review. This plugin adds the specialist lenses ([boundary](docs/requirements.md#superpowers-boundary)) |

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
| `ui-verifier` | Verify a changed web UI in a browser (Playwright): pass/fail per flow, desktop and mobile | — | sonnet | no |
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

Every skill is also invocable as `/agent-skills:<skill>`. Specialist agents get explicit commands, which never auto-trigger and cost no context per turn; workers are forced with `/agent-skills:offload`:

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
| `/agent-skills:perf-review [optimize] <target>` | `performance-analyst` |
| `/agent-skills:research <question(s)>` | parallel `researcher`, one per question |
| `/agent-skills:brief <feature>` | `feature-briefing` workflow |
| `/agent-skills:offload <task>` | Forces the cheapest suitable worker, including `ui-verifier` |

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

- Requirements: [`docs/requirements.md`](docs/requirements.md) · Decisions: [`docs/adr/`](docs/adr/) · Mods per surface (Desktop, VS Code, terminal): [`docs/mods-surfaces.md`](docs/mods-surfaces.md)
- Layout: one marketplace, each plugin in `plugins/<name>/`; the root keeps `docs/`, `scripts/` and the files you copy into user scope (`user-agents/`, `user-config/`).
- ADRs: knowledge in skills, roles in agents (0001) · dense English (0002) · interactive work in skills (0003) · rubrics, not percentages (0004) · track commits (0006) · Anthropic authoring conventions + evals (0007) · install paths and audience (0008, supersedes 0005) · research offload + briefing orchestration (0009) · cheap offload workers (0010) · marketplace with independent mods (0011) · UI verification worker + workers through offload (0012).

## Develop

| Step | Command |
|---|---|
| Validate structure and authoring rules | `python3 scripts/validate.py` and `claude plugin validate .` |
| Measure triggering (before/after any description or prompt change) | `claude plugin eval plugins/agent-skills --ablation none --model sonnet -j 4` |
| Validate and test a mod | `claude plugin validate plugins/<mod>` and `claude plugin test plugins/<mod>`; UI tests mount on every surface the site is raised on: `ToolUse` and the status line everywhere, `AbovePrompt` on terminal and desktop only (not VS Code) |
| Type-check a mod | `claude --plugin-dir plugins/<mod>` once (lays its types and tsconfig, git-ignored), then `tsc -p plugins/<mod>` |

Eval suites in `plugins/agent-skills/evals/`:

- `trigger/`: one case per skill, plus `performance-analyst` and `pre-mortem`. A case passes when its skill, or the agent named in its grader, fires; `change-impact`, `intent-elicitation` and `ux-principles` accept only the skill, `performance-analyst` and `pre-mortem` only the agent.
- `no-trigger/`: five near-misses (a live bug, an email to shorten, a small flag, a TDD green step, a "why" about an idiom). A case passes when no plugin skill or agent fires; each grader names every skill and agent.
- `offload/`: `check-runner` and `summarizer` with and without the [offload policy](user-config/offload-policy.md), `implementer` and `ui-verifier` with it. A case passes when the worker is dispatched, the main conversation does none of the work inline, and the answer (or the file written) is right. Run it with `--scaffold --allow-tools Bash Edit Write` and a sandbox: `bubblewrap`, `socat`.
