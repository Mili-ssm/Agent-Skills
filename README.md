# agent-skills

Marketplace `mili-ssm` with one plugin and opt-in mods, each installed on its own (ADR 0011):

| Plugin | What | Docs |
|---|---|---|
| `agent-skills` | Specialist skills, agents and offload workers (below) | [Catalog](#catalog), [`plugins/agent-skills/`](plugins/agent-skills/) |
| `plan-progress` (mod) | While a plan exists: progress status line, card above the prompt, task toasts | [README](plugins/plan-progress/README.md) |
| `tool-fold` (mod) | Folds tool, skill and agent calls into one line each; running agents get a live card; Claude's own card per request: time, calls, skills, agents, context, session, Haiku activity and conclusion (ADR 0016) | [README](plugins/tool-fold/README.md) |

`tool-fold` makes offloading to Haiku/Sonnet and its cost visible (ADR 0010); `plan-progress` tracks Superpowers plans; `tool-fold` also keeps tool output out of the way until asked for.

## agent-skills

Generic specialist skills and agents (architecture, QA, UX/UI, docs, requirements, security, performance) and cheap offload workers. [Superpowers](https://github.com/obra/superpowers) owns process and Playwright the browser; this plugin adds the specialist lenses and the workers ([boundary](docs/requirements.md#superpowers-boundary)). Personal plugin of its owner (ADR 0008).

## Install

<details>
<summary>Claude Code</summary>

| Where | How |
|---|---|
| Local session | `/plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Local shell | `claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills` |
| Cloud environment | Paste [`scripts/cloud-setup.sh`](scripts/cloud-setup.sh) as the environment's setup script (cloud sessions ignore plugins declared in a repo) |
| Desktop app (`/plugin` does not run there) | **+** next to the prompt box → Plugins → Add marketplace `Mili-ssm/Agent-Skills` → Add plugin; or install from a shell at user scope (above), which the app's local sessions also load |
| VS Code extension | Install from a shell at user scope (above): the extension runs Claude Code on the same `~/.claude` config |
| Older Claude Code | `/plugin marketplace add Mili-ssm/Agent-Skills`, then `/plugin install agent-skills@mili-ssm` |
| A mod | Same commands with the mod's name; in cloud set `AGENT_SKILLS_MODS="tool-fold plan-progress"` in the environment |

</details>

<details>
<summary>GitHub Copilot CLI</summary>

```bash
copilot plugin marketplace add Mili-ssm/Agent-Skills
```

```bash
copilot plugin install agent-skills@mili-ssm
```

Then add the prompt from [Recommended prompt](#recommended-prompt) (its GitHub Copilot CLI section) to `~/.copilot/copilot-instructions.md` (or `$COPILOT_HOME/copilot-instructions.md`); the files are also [`offload-policy.copilot.md`](user-config/offload-policy.copilot.md) and [`routing.copilot.md`](user-config/routing.copilot.md).

</details>

<details>
<summary>OpenAI Codex</summary>

```bash
codex plugin marketplace add Mili-ssm/Agent-Skills
```

```bash
codex plugin install agent-skills@mili-ssm
```

Codex plugins cannot carry agents, so copy the role files from the installed plugin:

```bash
mkdir -p ~/.codex/agents && cp ~/.codex/plugins/cache/mili-ssm/agent-skills/local/agents/*.toml ~/.codex/agents/
```

Then add the prompt from [Recommended prompt](#recommended-prompt) (its OpenAI Codex section) to `~/.codex/AGENTS.md`; the files are also [`offload-policy.codex.md`](user-config/offload-policy.codex.md) and [`routing.codex.md`](user-config/routing.codex.md). Repeat the role-file copy after each plugin update.

</details>

## Offload setup (ADR 0010)

The cloud script does this; locally run it once:

```bash
# Explore on Haiku (overrides the built-in, which uses the main model)
mkdir -p ~/.claude/agents && cp user-agents/Explore.md ~/.claude/agents/
# Subagents without their own model run on Sonnet
# add to ~/.claude/settings.json: "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}
```

Then add the offload table to `~/.claude/CLAUDE.md`: copy it from [`user-config/offload-policy.md`](user-config/offload-policy.md) (single source, ADR 0012). In evals it raised `check-runner` and `summarizer` delegation from 0–2/3 to 3/3 (ADR 0010); without it, force a worker per task with `/agent-skills:offload <task>`.

The cloud script can write the table for you: with `AGENT_SKILLS_OFFLOAD_POLICY=1` it writes it between two marker comments in `~/.claude/CLAUDE.md` and replaces that block on every run, so updates apply. It is off by default because account-level preferences may already carry the table, and a second copy costs context twice.

## Recommended prompt

Paste the block for your tool into your `CLAUDE.md`, `AGENTS.md` or Copilot instructions: it holds the offload table and the routing table (which skill, agent or command for which need). Sources: [`offload-policy.md`](user-config/offload-policy.md), [`routing.md`](user-config/routing.md).

<!-- BEGIN generated: recommended-prompt -->

<details>
<summary>Claude Code</summary>

````markdown
## Offload policy (main conversation only)

Delegate before pulling large sources, logs or command output into this context, because every token here is the most expensive one. Subagents cannot dispatch subagents: they do this work themselves.

| Situation | Delegate to |
|---|---|
| Searching or reading more than 3 files, or an unfamiliar codebase | `Explore` |
| Running tests, lint, typecheck, a build or another long read-only command (in the background while you keep working) | `agent-skills:check-runner` |
| Reading any file over ~200 lines (logs, docs, PDFs, large diffs, source) to answer from it, map it, or pull out a part you cannot locate with grep | `agent-skills:summarizer` |
| Any web search or web page | `agent-skills:researcher`, one per question, in parallel |
| Writing the code of a plan task (more than ~20 changed lines), even when it looks easy | `agent-skills:implementer`: write its brief, then review its diff instead of writing the code yourself |
| Mechanical lint/type/test fixes after a change | `agent-skills:fixer` |
| Verifying a changed web UI in a browser | `agent-skills:ui-verifier` |
| Before executing any plan, spec or design | `agent-skills:pre-mortem` |
| Before your final answer, whenever you or a worker (e.g. `implementer`) changed the project since its last review: code, docs, files, a deletion. The review is part of done, because the author is anchored on its own reasoning and a fresh context sees what it no longer does. Run it in the background with the checks, triage every finding yourself, verify medium/high ones, re-run it after fixing | `agent-skills:skeptical-reviewer` |

Keep inline: decisions, edits under ~20 lines, integrating results, and reading a range you located with grep. A task whose design is still open is not delegated: settle it here, or ask the owner, then brief it.

A worker sees none of this conversation, so its brief carries everything it needs:

1. **Goal** and acceptance criteria it can check itself.
2. **Scope**: the paths it owns, and what it must not touch.
3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
4. **Checks**: the commands that prove the result.
5. **Stop rule**: when the brief does not fit what it finds, it stops and reports the gap instead of improvising.
6. **Report**: format and max length.

State the what, the limits and the check, not each step: the worker reads the code and works out the how. Independent briefs run in parallel in one message, with disjoint paths.

Before you reply: if the project changed since `skeptical-reviewer` last ran, dispatch it now.

## Routing: which skill, agent or command for which need

Pick by the need; Superpowers entries are skills of the [Superpowers](https://github.com/obra/superpowers) plugin. Commands never auto-trigger: run them when the need appears.

| Need | Use |
|---|---|
| Recover or clarify intent, requirements, implicit decisions | `intent-elicitation` skill; `agent-skills:consistency-auditor` (`/agent-skills:consistency-audit`) for contradictions and stale decisions |
| Plan a feature | `/agent-skills:brief <feature>` (`feature-briefing` skill), or Superpowers `brainstorming` then `writing-plans`; then `agent-skills:pre-mortem` (`/agent-skills:premortem`) before executing |
| Blast radius of a significant change, migration, rollback | `change-impact` skill |
| Fix a defect | Superpowers `systematic-debugging`, then `test-driven-development` |
| Execute a plan | `agent-skills:implementer` per task, `agent-skills:check-runner` to verify, `agent-skills:skeptical-reviewer` after the changes land |
| Architecture, security, performance | `/agent-skills:arch-review`, `/agent-skills:security-audit`, `/agent-skills:perf-review`; their skills `architecture-principles`, `security-principles`, `observability` load on their own |
| Tests and docs | `/agent-skills:qa-review`, `/agent-skills:doc-audit`; skills `qa-principles`, `docs-principles` |
| Facts from outside the repository | `/agent-skills:research <questions>` (`web-research` skill) |
| Check a text against the sources it cites | `/agent-skills:fact-check <document> <sources>` (`agent-skills:fact-checker`) |
| API contracts | `api-design` skill |
| Prompts, skills, agent definitions, CLAUDE.md | `prompt-engineering` skill |
| UX and UI | `ux-principles` skill; `/agent-skills:ux-design` for a new feature, `/agent-skills:ux-review <url>` for an audit, `agent-skills:ui-verifier` for a changed page |
| Decisions, refactoring, releases | `decision-records`, `refactoring`, `release-hygiene` skills |
| Force a worker for a task | `/agent-skills:offload <task>` |
````

</details>

<details>
<summary>GitHub Copilot CLI</summary>

````markdown
## Offload policy (main conversation only)

Delegate before pulling large sources, logs or command output into this context, because every token here is the most expensive one. Subagents cannot dispatch subagents: they do this work themselves.

| Situation | Delegate to |
|---|---|
| Searching or reading more than 3 files, or an unfamiliar codebase | `explore` (built-in agent) |
| Running tests, lint, typecheck, a build or another long read-only command (in the background while you keep working) | `check-runner` |
| Reading any file over ~200 lines (logs, docs, PDFs, large diffs, source) to answer from it, map it, or pull out a part you cannot locate with grep | `summarizer` |
| Any web search or web page | `researcher`, one per question, in parallel |
| Writing the code of a plan task (more than ~20 changed lines), even when it looks easy | `implementer`: write its brief, then review its diff instead of writing the code yourself |
| Mechanical lint/type/test fixes after a change | `fixer` |
| Verifying a changed web UI in a browser | `ui-verifier` |
| Before executing any plan, spec or design | `pre-mortem` |
| Before your final answer, whenever you or a worker (e.g. `implementer`) changed the project since its last review: code, docs, files, a deletion. The review is part of done, because the author is anchored on its own reasoning and a fresh context sees what it no longer does. Run it in the background with the checks, triage every finding yourself, verify medium/high ones, re-run it after fixing | `skeptical-reviewer` |

Keep inline: decisions, edits under ~20 lines, integrating results, and reading a range you located with grep. A task whose design is still open is not delegated: settle it here, or ask the owner, then brief it.

A worker sees none of this conversation, so its brief carries everything it needs:

1. **Goal** and acceptance criteria it can check itself.
2. **Scope**: the paths it owns, and what it must not touch.
3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
4. **Checks**: the commands that prove the result.
5. **Stop rule**: when the brief does not fit what it finds, it stops and reports the gap instead of improvising.
6. **Report**: format and max length.

State the what, the limits and the check, not each step: the worker reads the code and works out the how. Independent briefs run in parallel in one message, with disjoint paths.

Before you reply: if the project changed since `skeptical-reviewer` last ran, dispatch it now.

## Routing: which skill, agent or command for which need

Pick by the need; Superpowers entries are skills of the [Superpowers](https://github.com/obra/superpowers) plugin. Commands never auto-trigger: run them when the need appears.

| Need | Use |
|---|---|
| Recover or clarify intent, requirements, implicit decisions | `intent-elicitation` skill; `consistency-auditor` (`/consistency-audit`) for contradictions and stale decisions |
| Plan a feature | `/brief <feature>` (`feature-briefing` skill), or Superpowers `brainstorming` then `writing-plans`; then `pre-mortem` (`/premortem`) before executing |
| Blast radius of a significant change, migration, rollback | `change-impact` skill |
| Fix a defect | Superpowers `systematic-debugging`, then `test-driven-development` |
| Execute a plan | `implementer` per task, `check-runner` to verify, `skeptical-reviewer` after the changes land |
| Architecture, security, performance | `/arch-review`, `/security-audit`, `/perf-review`; their skills `architecture-principles`, `security-principles`, `observability` load on their own |
| Tests and docs | `/qa-review`, `/doc-audit`; skills `qa-principles`, `docs-principles` |
| Facts from outside the repository | `/research <questions>` (`web-research` skill) |
| Check a text against the sources it cites | `/fact-check <document> <sources>` (`fact-checker`) |
| API contracts | `api-design` skill |
| Prompts, skills, agent definitions, CLAUDE.md | `prompt-engineering` skill |
| UX and UI | `ux-principles` skill; `/ux-design` for a new feature, `/ux-review <url>` for an audit, `ui-verifier` for a changed page |
| Decisions, refactoring, releases | `decision-records`, `refactoring`, `release-hygiene` skills |
| Force a worker for a task | `/offload <task>` |
````

</details>

<details>
<summary>OpenAI Codex</summary>

````markdown
## Offload policy (main conversation only)

Delegate before pulling large sources, logs or command output into this context, because every token here is the most expensive one. Subagents cannot dispatch subagents: they do this work themselves.

| Situation | Delegate to |
|---|---|
| Searching or reading more than 3 files, or an unfamiliar codebase | `explorer` (built-in role) |
| Running tests, lint, typecheck, a build or another long read-only command (in the background while you keep working) | `check-runner` |
| Reading any file over ~200 lines (logs, docs, PDFs, large diffs, source) to answer from it, map it, or pull out a part you cannot locate with grep | `summarizer` |
| Any web search or web page | `researcher`, one per question, in parallel |
| Writing the code of a plan task (more than ~20 changed lines), even when it looks easy | `implementer`: write its brief, then review its diff instead of writing the code yourself |
| Mechanical lint/type/test fixes after a change | `fixer` |
| Verifying a changed web UI in a browser | `ui-verifier` |
| Before executing any plan, spec or design | `pre-mortem` |
| Before your final answer, whenever you or a worker (e.g. `implementer`) changed the project since its last review: code, docs, files, a deletion. The review is part of done, because the author is anchored on its own reasoning and a fresh context sees what it no longer does. Run it in the background with the checks, triage every finding yourself, verify medium/high ones, re-run it after fixing | `skeptical-reviewer` |

Keep inline: decisions, edits under ~20 lines, integrating results, and reading a range you located with grep. A task whose design is still open is not delegated: settle it here, or ask the owner, then brief it.

A worker sees none of this conversation, so its brief carries everything it needs:

1. **Goal** and acceptance criteria it can check itself.
2. **Scope**: the paths it owns, and what it must not touch.
3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
4. **Checks**: the commands that prove the result.
5. **Stop rule**: when the brief does not fit what it finds, it stops and reports the gap instead of improvising.
6. **Report**: format and max length.

State the what, the limits and the check, not each step: the worker reads the code and works out the how. Independent briefs run in parallel in one message, with disjoint paths.

Before you reply: if the project changed since `skeptical-reviewer` last ran, dispatch it now.

## Routing: which skill, agent or command for which need

Pick by the need; Superpowers entries are skills of the [Superpowers](https://github.com/obra/superpowers) plugin. Commands never auto-trigger: run them when the need appears.

| Need | Use |
|---|---|
| Recover or clarify intent, requirements, implicit decisions | `intent-elicitation` skill; `consistency-auditor` (`/agent-skills:consistency-audit`) for contradictions and stale decisions |
| Plan a feature | `/agent-skills:brief <feature>` (`feature-briefing` skill), or Superpowers `brainstorming` then `writing-plans`; then `pre-mortem` (`/agent-skills:premortem`) before executing |
| Blast radius of a significant change, migration, rollback | `change-impact` skill |
| Fix a defect | Superpowers `systematic-debugging`, then `test-driven-development` |
| Execute a plan | `implementer` per task, `check-runner` to verify, `skeptical-reviewer` after the changes land |
| Architecture, security, performance | `/agent-skills:arch-review`, `/agent-skills:security-audit`, `/agent-skills:perf-review`; their skills `architecture-principles`, `security-principles`, `observability` load on their own |
| Tests and docs | `/agent-skills:qa-review`, `/agent-skills:doc-audit`; skills `qa-principles`, `docs-principles` |
| Facts from outside the repository | `/agent-skills:research <questions>` (`web-research` skill) |
| Check a text against the sources it cites | `/agent-skills:fact-check <document> <sources>` (`fact-checker`) |
| API contracts | `api-design` skill |
| Prompts, skills, agent definitions, CLAUDE.md | `prompt-engineering` skill |
| UX and UI | `ux-principles` skill; `/agent-skills:ux-design` for a new feature, `/agent-skills:ux-review <url>` for an audit, `ui-verifier` for a changed page |
| Decisions, refactoring, releases | `decision-records`, `refactoring`, `release-hygiene` skills |
| Force a worker for a task | `/agent-skills:offload <task>` |
````

</details>

<!-- END generated: recommended-prompt -->

## Other tools (Copilot, Codex)

`agent-skills` also installs in GitHub Copilot CLI and OpenAI Codex from generated copies under `ports/`; the mods stay Claude-only. Install steps are in [Install](#install); what maps to what and the limits: [docs/ports.md](docs/ports.md) (ADR 0015).

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
| Workers | The [offload policy](user-config/offload-policy.md) is in your user-level `~/.claude/CLAUDE.md`, or you force one with `/agent-skills:offload <task>` | Reading, checks, browser verification, after-action review and bounded edits on Haiku/Sonnet: `check-runner`, `summarizer`, `researcher`, `implementer`, `fixer`, `ui-verifier`, `skeptical-reviewer` (plus user-scope `Explore`) |
| Superpowers | Its own triggers | Process: brainstorming, plans, TDD, debugging, review. This plugin adds the specialist lenses |

### Agents (fresh context, return a report)

| Agent | Use when | Preloads | Model | Writes? |
|---|---|---|---|---|
| `architect` | Assess/review/propose architecture | architecture-principles, decision-records | opus | no |
| `qa-engineer` | Test strategy, gaps, case design, flaky tests, mutation | qa-principles | sonnet | when asked |
| `ux-reviewer` | Design consultant: visual quality, usability and accessibility audit with screenshots/axe, or a critique of a spec before it is built | ux-principles | sonnet | no |
| `doc-curator` | Documentation specialist: verify docs against code, organize and compress them | docs-principles, decision-records, prompt-engineering | sonnet | when asked |
| `fact-checker` | Check the claims of a text against the sources it cites: one verdict per claim with the source passage and a replacement | — | sonnet | no |
| `prompt-engineer` | Review prompts, skills, agents, tool descriptions and CLAUDE.md for LLM behavior; rewrites with the check that measures each | prompt-engineering | sonnet | no |
| `consistency-auditor` | Infer intent; find contradictions, stale/implicit decisions | decision-records | sonnet | no |
| `security-reviewer` | Source→sink review, threat model | security-principles | opus | no |
| `pre-mortem` | Attack a plan before execution | — | opus | no |
| `skeptical-reviewer` | Review a finished action (code, docs, layout, deletion, image description); hedged findings ranked by improvement, to be verified by the caller | — | haiku | no |
| `researcher` | Offloaded web research, one question, cited | web-research | haiku | no |
| `check-runner` | Run tests/lint/typecheck/build or another long read-only command; return failures, the result or the last lines verbatim | — | haiku | no |
| `summarizer` | Read long logs/docs/PDFs/diffs/source; answer one question, outline with line ranges, or extract verbatim | — | haiku | no |
| `implementer` | Apply one bounded plan task with acceptance | — | sonnet | yes |
| `fixer` | Loop on mechanical lint/type/test fixes | — | sonnet | yes |
| `ui-verifier` | QA engineer for interfaces: verify that a changed web UI works in a browser (Playwright), pass/fail per flow, desktop and mobile | — | sonnet | no |
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
| `docs-principles` | Knowledge | Repository docs: Diátaxis, density, compression with metrics |
| `prompt-engineering` | Knowledge + script | Text LLMs act on (prompts, skills, agents, briefs, tools, CLAUDE.md), per-model notes, eval practice, agent-run repos; `outline.py` (file map with line ranges, zero model tokens) |
| `architecture-principles` | Knowledge | Principles, software laws, patterns, smells, evaluation |
| `qa-principles` | Knowledge | Test design, strategy, test quality |
| `ux-principles` | Knowledge + script | Heuristics, laws, WCAG, visual system, `ux_audit.py` |
| `security-principles` | Knowledge | STRIDE, OWASP/ASVS, language specifics |
| `api-design` | Knowledge | HTTP/JSON/hypermedia contracts |
| `observability` | Knowledge | Logs, metrics, traces, SLOs |
| `release-hygiene` | Knowledge | Commits, SemVer, changelog, releases |

### Commands (explicit, user-only)

Every skill is also invocable as `/agent-skills:<skill>`. Specialist agents get commands, which never auto-trigger and cost no context per turn; workers are forced with `/agent-skills:offload`:

| Command | Runs |
|---|---|
| `/agent-skills:ux-design <feature>` | `ux-principles` design workflow → spec + Playwright acceptance checks |
| `/agent-skills:ux-review <url>` | `ux-reviewer` |
| `/agent-skills:arch-review [mode] [scope]` | `architect` |
| `/agent-skills:qa-review [mode] [scope]` | `qa-engineer` |
| `/agent-skills:security-audit [mode] [scope]` | `security-reviewer` |
| `/agent-skills:doc-audit [audit\|apply] [paths]` | `doc-curator` |
| `/agent-skills:prompt-review [paths] [models] [symptom]` | `prompt-engineer` |
| `/agent-skills:fact-check [document or claims] [sources]` | `fact-checker` |
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

- Maintainer notes for agents (commands, generated files, ADR rules): [`CLAUDE.md`](CLAUDE.md) · Requirements: [`docs/requirements.md`](docs/requirements.md) · Decisions: [`docs/adr/`](docs/adr/) · Mods per surface (Desktop, VS Code, terminal): [`docs/mods-surfaces.md`](docs/mods-surfaces.md)
- Layout: one marketplace, each plugin in `plugins/<name>/`; the root keeps `docs/`, `scripts/`, the files you copy into user scope (`user-agents/`, `user-config/`) and the generated ports (`ports/`, ADR 0015).
- ADRs are cited by number; 0008 supersedes 0005.

## Develop

| Step | Command |
|---|---|
| Validate structure and authoring rules | `python3 scripts/validate.py` and `claude plugin validate .` |
| Regenerate the Copilot and Codex ports after changing agents, skills, commands or the offload policy | `python3 scripts/port.py` (`--check` verifies, `--report` prints the mapping) |
| Measure a description or prompt change before merging | `claude plugin eval plugins/agent-skills --ablation none --model sonnet -j 4 --runs 2 --case '<glob>'`; which cases and when to rerun: [`CLAUDE.md` § Eval protocol](CLAUDE.md#eval-protocol-adr-0007-review-2026-10-30) |
| Validate and test a mod | `claude plugin validate plugins/<mod>` and `claude plugin test plugins/<mod>`; UI tests mount on every surface the site is raised on: `ToolUse` and the status line everywhere, `AbovePrompt` on terminal and desktop only (not VS Code) |
| Type-check a mod | `claude --plugin-dir plugins/<mod>` once (lays its types and tsconfig, git-ignored), then `tsc -p plugins/<mod>` |

### Eval suites

In `plugins/agent-skills/evals/`:

- `trigger/`: one case per skill, plus `performance-analyst` and `pre-mortem`. A case passes when its skill, or the agent named in its grader, fires; `change-impact`, `intent-elicitation` and `ux-principles` accept only the skill, `performance-analyst` and `pre-mortem` only the agent.
- `no-trigger/`: five near-misses (a live bug, an email to shorten, a small flag, a TDD green step, a "why" about an idiom). A case passes when no plugin skill or agent fires; each grader names every skill and agent.
- `offload/`: `check-runner` and `summarizer` with and without the [offload policy](user-config/offload-policy.md), a verbatim-section case (passes by delegating to `summarizer` or by a bounded read), `implementer` and `ui-verifier` with it. A case passes when the worker is dispatched, its brief carries what only the conversation knew (the `implementer` case checks the decision with its reason, the off-limits file and the stop rule), the main conversation does none of the work inline, and the answer (or the file written) is right. Run it with `--scaffold --allow-tools Bash Edit Write` and a sandbox: `bubblewrap`, `socat`.
