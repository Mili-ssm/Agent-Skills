# agent-skills

Marketplace `mili-ssm` with four plugins, each installed on its own (ADR 0011): `agent-skills`, `memory` and two opt-in mods.

| Plugin | What | Docs |
|---|---|---|
| `agent-skills` | Specialist skills, agents and offload workers (below) | [Catalog](#catalog), [`plugins/agent-skills/`](plugins/agent-skills/) |
| `plan-progress` (mod) | While a plan exists: progress status line, card above the prompt, task toasts | [README](plugins/plan-progress/README.md) |
| `tool-fold` (mod) | Folds tool, skill and agent calls into one line each; running agents get a live card; Claude's own card per request: time, calls, skills, agents, context, session, Haiku activity and conclusion (ADR 0016) | [README](plugins/tool-fold/README.md) |
| `memory` | Notes and memories reachable from every repository and subagent: the `mem` command, a short start text, curation and syntheses (ADR 0023) | [README](plugins/memory/README.md) |

`tool-fold` makes offloading to Haiku/Sonnet and its cost visible (ADR 0010) and keeps tool output out of the way until asked for; `plan-progress` tracks Superpowers plans.

## agent-skills

Generic specialist skills and agents (architecture, QA, UX/UI, docs, requirements, security, performance) and cheap offload workers. [Superpowers](https://github.com/obra/superpowers) supplies the methods and the plan loop, and Playwright the browser; this plugin adds the specialist lenses and the agents that do the work ([boundary](docs/requirements.md#superpowers-boundary)). Personal plugin of its owner (ADR 0008).

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
| The `memory` plugin | Same commands with the name `memory`; set its `store` option to the folder of notes |

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
codex plugin add agent-skills@mili-ssm
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

**Claude Code:** nothing to paste for the offload table. The plugin's `SessionStart` hook prints it at session start, after `/clear` and after a compaction (implemented, ADR 0032; evals: no case dropped against the pasted table at 2 runs per case, too few to claim equivalence or a gain). It stays silent when the option `offload_policy` is `false` (`/plugin configure agent-skills@mili-ssm`) and when `~/.claude/CLAUDE.md` already holds the table, so users who pasted it need do nothing. Turn the option off if the table reaches the session another way (an `@import`, a project `CLAUDE.md`, account instructions), or it loads twice. Either way, paste the routing text from [`user-config/routing.md`](user-config/routing.md): a Claude Code user may paste the whole block below (the hook sees the pasted table's heading and stays silent, so nothing loads twice) or leave out its "Offload policy" section and let the hook load it. **Copilot CLI and Codex:** no hook parity; paste both files (below). Without the table, force a worker per task with `/agent-skills:offload <task>` (the table raised `check-runner` and `summarizer` delegation from 0–2/3 to 3/3, ADR 0010).

The cloud script turns the table hook off (`offload_policy: false`; `AGENT_SKILLS_OFFLOAD_HOOK=1` keeps it on), because the owner's account preferences already carry the table. It can also write the table for you: with `AGENT_SKILLS_OFFLOAD_POLICY=1` it writes it between two marker comments in `~/.claude/CLAUDE.md` and replaces that block on every run, so updates apply. It is off by default because account-level preferences may already carry the table, and a second copy costs context twice.

## Recommended prompt

Paste the block for your tool into your `CLAUDE.md`, `AGENTS.md` or Copilot instructions (Claude Code users may leave out the "Offload policy" section and let the hook load it, but must paste the routing text, ADR 0032): it holds the offload table and the routing table (which skill, agent or command for which need). Sources: [`offload-policy.md`](user-config/offload-policy.md), [`routing.md`](user-config/routing.md).

<!-- BEGIN generated: recommended-prompt -->

<details>
<summary>Claude Code</summary>

````markdown
## Offload policy (main conversation only)

Delegate before pulling large sources, logs or command output into this context, because every token here is the most expensive one. Subagents cannot dispatch subagents: they do this work themselves.

| Situation | Delegate to |
|---|---|
| Searching or reading more than 3 files, or an unfamiliar codebase | `Explore` |
| Running tests, lint, typecheck, a build or another read-only command that you expect to take over a minute or to print more than a screen of output (in the background while you keep working) | `agent-skills:check-runner` |
| Reading any file over ~200 lines (logs, docs, PDFs, large diffs, source) to answer from it, map it, or pull out a part you cannot locate with grep | `agent-skills:summarizer` |
| Any web search or web page | `agent-skills:researcher`, one per question, in parallel |
| Writing the code of a plan task (more than ~20 changed lines), even when it looks easy | `agent-skills:implementer`: write its brief, then review its diff instead of writing the code yourself |
| Mechanical lint/type/test fixes after a change | `agent-skills:fixer` |
| Verifying a changed web UI in a browser | `agent-skills:ui-verifier` |
| Before executing any plan, spec or design | `agent-skills:pre-mortem` |
| Before your final answer, whenever you or a worker (e.g. `implementer`) changed the project since its last review: code, docs, files, a deletion. The review is part of done, because the author is anchored on its own reasoning and a fresh context sees what it no longer does. Run it in the background with the checks, triage every finding yourself, verify medium/high ones, re-run it once after fixing (round 2 is the last) | `agent-skills:skeptical-reviewer` |

Keep inline: decisions, edits under ~20 lines, integrating results, reading a range you located with grep, and a short check with its output cut (`| tail`, `-q`), because a dispatch costs more than its few lines. A task whose design is still open is not delegated: settle it here, or ask the owner, then brief it.

A worker sees none of this conversation, so its brief carries what only this conversation knows:

1. **Goal** and acceptance criteria it can check itself: one outcome per brief.
2. **Scope**: the paths it owns, and what it must not touch.
3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
4. **Checks**: the commands that prove the result.

Name a file the worker can open (a committed plan task, a spec, a commit range) instead of restating it, and write out only what exists nowhere but here. Every worker already has its stop rule and its report format: state one only to change it. A brief to `Explore` still states a length, because that agent's report format is not ours on every tool.

State the what, the limits and the check, not each step: the worker reads the code and works out the how. Independent briefs run in parallel in one message, with disjoint paths.

Before you reply: if the project changed since `skeptical-reviewer` last ran and round 2 has not run, dispatch it now.

## Routing: which skill, agent or command for which need

Use skills and agents on your own initiative: the owner rarely names one. When a row below matches the work in front of you, load the skill or dispatch the agent, and say in one line, the first time in a task, which one and why. Skip the knowledge skills and the specialists for a question you can answer from what you have read and for an edit under ~20 lines that touches no contract, schema or input handling. The offload policy and the review rows below keep their own triggers, and a row's own condition still applies. This table and the offload policy decide who does the work; a skill of the [Superpowers](https://github.com/obra/superpowers) plugin loads when a row names it. The owner's manual entries to the same skills and agents (slash commands in Claude Code) never auto-trigger, and you cannot run them.

| Need | Use |
|---|---|
| Recover or clarify intent, requirements, implicit decisions | `intent-elicitation` skill, only while the intent is unclear, because it interviews the owner; `agent-skills:consistency-auditor` for contradictions and stale decisions |
| Plan a feature | `feature-briefing` skill when the plan needs evidence from several sources, or Superpowers `brainstorming` (only while the design is open) then `writing-plans`; then `agent-skills:pre-mortem` before executing |
| Blast radius of a significant change, migration, rollback | `change-impact` skill |
| Fix a defect | Lint, type, format or import errors, or tests broken by a rename or refactor: `agent-skills:fixer`, with no root-cause investigation. Any other defect, a test that fails on behavior, or the same error after 2 attempts: Superpowers `systematic-debugging`, then `test-driven-development` |
| Execute a plan | A code plan with `### Task N` headings: Superpowers `subagent-driven-development` as the loop, with this plugin's agents (see "Plan loop" below). Any other plan or work: `agent-skills:implementer` per task with a brief per the offload policy, `agent-skills:check-runner` to verify, `agent-skills:skeptical-reviewer` after the changes land |
| Writing, changing or briefing work on one of these | Load the skill first: `api-design` (an endpoint, route, webhook, status code or error format); `security-principles` (code that takes user input, uploads, auth, redirects or secrets); `qa-principles` (choosing which test cases to write); `observability` (logging, metrics, health checks or alerts); `refactoring` (restructuring with behavior unchanged); `docs-principles` (a README or docs rewrite); `decision-records` (a decision to record); `release-hygiene` (a version, changelog entry or tag); `prompt-engineering` (a prompt, skill, agent definition or CLAUDE.md); `ux-principles` (a page, form or user flow); `architecture-principles` (module boundaries or coupling). `agent-skills:implementer` does not load skills, so put the few rules that apply into its brief, not the skill text |
| A specialist question: an assessment that needs a fresh context, where a skill is for work you do yourself | The agent whose description matches: `agent-skills:architect` (the structure of a codebase, design or plan), `agent-skills:security-reviewer`, `agent-skills:performance-analyst` (something slow, or an optimization to verify), `agent-skills:qa-engineer` (test strategy or coverage gaps), `agent-skills:doc-curator` (a docs audit), `agent-skills:ux-reviewer` (how a UI looks and reads), `agent-skills:fact-checker` (a text against the sources it cites), `agent-skills:prompt-engineer` (a changed prompt, skill, agent definition or CLAUDE.md, even one file; or a trace). `agent-skills:architect` and `agent-skills:security-reviewer` cost the most: use them for work that spans several modules, or for a design, plan or security surface under review. `agent-skills:doc-curator`, `agent-skills:qa-engineer` and `agent-skills:performance-analyst` run in their read-only mode unless the owner asked for the edit (`apply`, `write`, `optimize`). Relay every finding of an agent in this row, dropping none, in the owner's reply format, then list the decisions it leaves to the owner |
| Full project assessment, when the owner asks to assess the whole project | `agent-skills:architect`, `agent-skills:qa-engineer`, `agent-skills:security-reviewer` and `agent-skills:doc-curator` in parallel |
| Facts from outside the repository | `web-research` skill |

### Plan loop

The Superpowers `subagent-driven-development` skill supplies the loop: the order, the ledger and one task at a time. This plugin's agents fill both of its subagent roles, so where the skill's text differs from the lines below, the lines apply:

- **Implementer**: `agent-skills:implementer`, dispatched with no model parameter: the agent file fixes its model, and this replaces the skill's rule to name a model at every dispatch. Its brief points to the task brief file, adds only what the offload policy's brief rule asks for and says: follow the task's test-then-code steps, commit this task locally, and write the full report (commands run, failing and passing output) to the report path. That file is a deliverable, not a temporary file, and may be long; the reply stays short.
- **Its result**: `DONE` with a non-empty "Open questions / risks" line counts as done with concerns; a stop for missing input counts as needing context; `BLOCKED — checkpoint` or `BLOCKED — turn budget` means the task is too big: split it.
- **Task reviewer**: `agent-skills:skeptical-reviewer`, also with no model parameter, which replaces the skill's mid-tier floor for reviewers, after each task's commit. Its brief adds the text of the task and asks what is missing, extra or misunderstood against it.
- **Verdicts are yours**: the reviewer returns doubts for you to verify, not a verdict, and your own spec and quality verdicts satisfy the skill's rule that both exist. A missing, extra or misunderstood item that you verified fails the spec check; a verified medium or high finding starts a fix round; low findings are deferred. You may reject a finding once you have verified it is wrong: record it in the ledger as a ruling.
- **Fixes**: a fresh `agent-skills:implementer` per fix round, briefed with the findings you verified. Review round 1 follows the task commit and round 2 reviews the fixes; this replaces the skill's five-round cap. Confirm the fixes of round 2 from their report and a run of `agent-skills:check-runner`, with no third review. A finding still open then goes to the skill's breaker: park it with a ruling, or rule on the smallest change that unblocks the later tasks.
- **End**: after the last task, several narrow `agent-skills:skeptical-reviewer` reviews in parallel replace the skill's whole-branch reviewer; they receive the deferred and parked lines of the ledger.

### Reviews and proof of done

| Situation | Do |
|---|---|
| Before a push, a pull request, a merge, a tag, or a commit on a branch that already has an upstream on the remote | `agent-skills:skeptical-reviewer` on `git status`, the staged diff and, for a pull request or merge, its file list; triage the findings before taking the step, because a step that looks done can be empty or partial. The exception is the implementer's task commits in the plan loop: review each one right after it |
| Before closing a task you ran against a plan, a skill, a checklist or the project's done criteria | `agent-skills:skeptical-reviewer` as a process review: pass the rules that applied and the steps you took, each with its evidence, and ask whether any step was skipped, misordered or claimed without evidence, because the author's own checklist misses what it forgot |
| A change with several parts | Several narrow reviews in parallel instead of one broad one, because the reviewer is cheap but weak. Each has one focus, its own paths, a concrete question and what to look for: the code, the diff or step itself, the docs against the code, architecture and organization |

Review brief: what changed as paths or a commit range, the intent in one line, rules that are not in `CLAUDE.md` or `AGENTS.md`, what is already verified, the round number and the findings already rejected. Stop after round 2: the offload rules to re-run the reviewer after fixing and before replying add no third round, so confirm the last fixes with `agent-skills:check-runner` and your own reading.

A PASS from `agent-skills:check-runner` is evidence when its report names the command and the result; read its `Not run:` line. Before a commit you make yourself, a push or a pull request, rerun yourself the single command that proves the acceptance criterion (the task's named test, or the build) and keep only its summary line.
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
| Running tests, lint, typecheck, a build or another read-only command that you expect to take over a minute or to print more than a screen of output (in the background while you keep working) | `check-runner` |
| Reading any file over ~200 lines (logs, docs, PDFs, large diffs, source) to answer from it, map it, or pull out a part you cannot locate with grep | `summarizer` |
| Any web search or web page | `researcher`, one per question, in parallel |
| Writing the code of a plan task (more than ~20 changed lines), even when it looks easy | `implementer`: write its brief, then review its diff instead of writing the code yourself |
| Mechanical lint/type/test fixes after a change | `fixer` |
| Verifying a changed web UI in a browser | `ui-verifier` |
| Before executing any plan, spec or design | `pre-mortem` |
| Before your final answer, whenever you or a worker (e.g. `implementer`) changed the project since its last review: code, docs, files, a deletion. The review is part of done, because the author is anchored on its own reasoning and a fresh context sees what it no longer does. Run it in the background with the checks, triage every finding yourself, verify medium/high ones, re-run it once after fixing (round 2 is the last) | `skeptical-reviewer` |

Keep inline: decisions, edits under ~20 lines, integrating results, reading a range you located with grep, and a short check with its output cut (`| tail`, `-q`), because a dispatch costs more than its few lines. A task whose design is still open is not delegated: settle it here, or ask the owner, then brief it.

A worker sees none of this conversation, so its brief carries what only this conversation knows:

1. **Goal** and acceptance criteria it can check itself: one outcome per brief.
2. **Scope**: the paths it owns, and what it must not touch.
3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
4. **Checks**: the commands that prove the result.

Name a file the worker can open (a committed plan task, a spec, a commit range) instead of restating it, and write out only what exists nowhere but here. Every worker already has its stop rule and its report format: state one only to change it. A brief to `explore` (built-in agent) still states a length, because that agent's report format is not ours on every tool.

State the what, the limits and the check, not each step: the worker reads the code and works out the how. Independent briefs run in parallel in one message, with disjoint paths.

Before you reply: if the project changed since `skeptical-reviewer` last ran and round 2 has not run, dispatch it now.

## Routing: which skill, agent or command for which need

Use skills and agents on your own initiative: the owner rarely names one. When a row below matches the work in front of you, load the skill or dispatch the agent, and say in one line, the first time in a task, which one and why. Skip the knowledge skills and the specialists for a question you can answer from what you have read and for an edit under ~20 lines that touches no contract, schema or input handling. The offload policy and the review rows below keep their own triggers, and a row's own condition still applies. This table and the offload policy decide who does the work; a skill of the [Superpowers](https://github.com/obra/superpowers) plugin loads when a row names it. The owner's manual entries to the same skills and agents (slash commands in Claude Code) never auto-trigger, and you cannot run them.

| Need | Use |
|---|---|
| Recover or clarify intent, requirements, implicit decisions | `intent-elicitation` skill, only while the intent is unclear, because it interviews the owner; `consistency-auditor` for contradictions and stale decisions |
| Plan a feature | `feature-briefing` skill when the plan needs evidence from several sources, or Superpowers `brainstorming` (only while the design is open) then `writing-plans`; then `pre-mortem` before executing |
| Blast radius of a significant change, migration, rollback | `change-impact` skill |
| Fix a defect | Lint, type, format or import errors, or tests broken by a rename or refactor: `fixer`, with no root-cause investigation. Any other defect, a test that fails on behavior, or the same error after 2 attempts: Superpowers `systematic-debugging`, then `test-driven-development` |
| Execute a plan | A code plan with `### Task N` headings: Superpowers `subagent-driven-development` as the loop, with this plugin's agents (see "Plan loop" below). Any other plan or work: `implementer` per task with a brief per the offload policy, `check-runner` to verify, `skeptical-reviewer` after the changes land |
| Writing, changing or briefing work on one of these | Load the skill first: `api-design` (an endpoint, route, webhook, status code or error format); `security-principles` (code that takes user input, uploads, auth, redirects or secrets); `qa-principles` (choosing which test cases to write); `observability` (logging, metrics, health checks or alerts); `refactoring` (restructuring with behavior unchanged); `docs-principles` (a README or docs rewrite); `decision-records` (a decision to record); `release-hygiene` (a version, changelog entry or tag); `prompt-engineering` (a prompt, skill, agent definition or CLAUDE.md); `ux-principles` (a page, form or user flow); `architecture-principles` (module boundaries or coupling). `implementer` does not load skills, so put the few rules that apply into its brief, not the skill text |
| A specialist question: an assessment that needs a fresh context, where a skill is for work you do yourself | The agent whose description matches: `architect` (the structure of a codebase, design or plan), `security-reviewer`, `performance-analyst` (something slow, or an optimization to verify), `qa-engineer` (test strategy or coverage gaps), `doc-curator` (a docs audit), `ux-reviewer` (how a UI looks and reads), `fact-checker` (a text against the sources it cites), `prompt-engineer` (a changed prompt, skill, agent definition or CLAUDE.md, even one file; or a trace). `architect` and `security-reviewer` cost the most: use them for work that spans several modules, or for a design, plan or security surface under review. `doc-curator`, `qa-engineer` and `performance-analyst` run in their read-only mode unless the owner asked for the edit (`apply`, `write`, `optimize`). Relay every finding of an agent in this row, dropping none, in the owner's reply format, then list the decisions it leaves to the owner |
| Full project assessment, when the owner asks to assess the whole project | `architect`, `qa-engineer`, `security-reviewer` and `doc-curator` in parallel |
| Facts from outside the repository | `web-research` skill |

### Plan loop

The Superpowers `subagent-driven-development` skill supplies the loop: the order, the ledger and one task at a time. This plugin's agents fill both of its subagent roles, so where the skill's text differs from the lines below, the lines apply:

- **Implementer**: `implementer`, dispatched with no model parameter: the agent file fixes its model, and this replaces the skill's rule to name a model at every dispatch. Its brief points to the task brief file, adds only what the offload policy's brief rule asks for and says: follow the task's test-then-code steps, commit this task locally, and write the full report (commands run, failing and passing output) to the report path. That file is a deliverable, not a temporary file, and may be long; the reply stays short.
- **Its result**: `DONE` with a non-empty "Open questions / risks" line counts as done with concerns; a stop for missing input counts as needing context; `BLOCKED — checkpoint` or `BLOCKED — turn budget` means the task is too big: split it.
- **Task reviewer**: `skeptical-reviewer`, also with no model parameter, which replaces the skill's mid-tier floor for reviewers, after each task's commit. Its brief adds the text of the task and asks what is missing, extra or misunderstood against it.
- **Verdicts are yours**: the reviewer returns doubts for you to verify, not a verdict, and your own spec and quality verdicts satisfy the skill's rule that both exist. A missing, extra or misunderstood item that you verified fails the spec check; a verified medium or high finding starts a fix round; low findings are deferred. You may reject a finding once you have verified it is wrong: record it in the ledger as a ruling.
- **Fixes**: a fresh `implementer` per fix round, briefed with the findings you verified. Review round 1 follows the task commit and round 2 reviews the fixes; this replaces the skill's five-round cap. Confirm the fixes of round 2 from their report and a run of `check-runner`, with no third review. A finding still open then goes to the skill's breaker: park it with a ruling, or rule on the smallest change that unblocks the later tasks.
- **End**: after the last task, several narrow `skeptical-reviewer` reviews in parallel replace the skill's whole-branch reviewer; they receive the deferred and parked lines of the ledger.

### Reviews and proof of done

| Situation | Do |
|---|---|
| Before a push, a pull request, a merge, a tag, or a commit on a branch that already has an upstream on the remote | `skeptical-reviewer` on `git status`, the staged diff and, for a pull request or merge, its file list; triage the findings before taking the step, because a step that looks done can be empty or partial. The exception is the implementer's task commits in the plan loop: review each one right after it |
| Before closing a task you ran against a plan, a skill, a checklist or the project's done criteria | `skeptical-reviewer` as a process review: pass the rules that applied and the steps you took, each with its evidence, and ask whether any step was skipped, misordered or claimed without evidence, because the author's own checklist misses what it forgot |
| A change with several parts | Several narrow reviews in parallel instead of one broad one, because the reviewer is cheap but weak. Each has one focus, its own paths, a concrete question and what to look for: the code, the diff or step itself, the docs against the code, architecture and organization |

Review brief: what changed as paths or a commit range, the intent in one line, rules that are not in `CLAUDE.md` or `AGENTS.md`, what is already verified, the round number and the findings already rejected. Stop after round 2: the offload rules to re-run the reviewer after fixing and before replying add no third round, so confirm the last fixes with `check-runner` and your own reading.

A PASS from `check-runner` is evidence when its report names the command and the result; read its `Not run:` line. Before a commit you make yourself, a push or a pull request, rerun yourself the single command that proves the acceptance criterion (the task's named test, or the build) and keep only its summary line.
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
| Running tests, lint, typecheck, a build or another read-only command that you expect to take over a minute or to print more than a screen of output (spawn it, keep working, and collect its result before your final answer) | `check-runner` |
| Reading any file over ~200 lines (logs, docs, PDFs, large diffs, source) to answer from it, map it, or pull out a part you cannot locate with grep | `summarizer` |
| Any web search or web page | `researcher`, one per question, in parallel |
| Writing the code of a plan task (more than ~20 changed lines), even when it looks easy | `implementer`: write its brief, then review its diff instead of writing the code yourself |
| Mechanical lint/type/test fixes after a change | `fixer` |
| Verifying a changed web UI in a browser | `ui-verifier` |
| Before executing any plan, spec or design | `pre-mortem` |
| Before your final answer, whenever you or a worker (e.g. `implementer`) changed the project since its last review: code, docs, files, a deletion. The review is part of done, because the author is anchored on its own reasoning and a fresh context sees what it no longer does. Spawn it together with the checks and collect its result before your final answer, triage every finding yourself, verify medium/high ones, re-run it once after fixing (round 2 is the last) | `skeptical-reviewer` |

Keep inline: decisions, edits under ~20 lines, integrating results, reading a range you located with grep, and a short check with its output cut (`| tail`, `-q`), because a dispatch costs more than its few lines. A task whose design is still open is not delegated: settle it here, or ask the owner, then brief it.

Spawn every worker with `fork_turns` set to `"none"`, because the default copies this whole conversation into the worker and makes its first request about four times larger. The worker then sees none of this conversation, so its brief carries what only this conversation knows:

1. **Goal** and acceptance criteria it can check itself: one outcome per brief.
2. **Scope**: the paths it owns, and what it must not touch.
3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
4. **Checks**: the commands that prove the result.

Name a file the worker can open (a committed plan task, a spec, a commit range) instead of restating it, and write out only what exists nowhere but here. Every worker already has its stop rule and its report format: state one only to change it. A brief to `explorer` (built-in role) still states a length, because that agent's report format is not ours on every tool.

State the what, the limits and the check, not each step: the worker reads the code and works out the how. Independent briefs run in parallel in one message, with disjoint paths.

Before you reply: if the project changed since `skeptical-reviewer` last ran and round 2 has not run, dispatch it now.

## Routing: which skill, agent or command for which need

Use skills and agents on your own initiative: the owner rarely names one. When a row below matches the work in front of you, load the skill or dispatch the agent, and say in one line, the first time in a task, which one and why. Skip the knowledge skills and the specialists for a question you can answer from what you have read and for an edit under ~20 lines that touches no contract, schema or input handling. The offload policy and the review rows below keep their own triggers, and a row's own condition still applies. This table and the offload policy decide who does the work; a skill of the [Superpowers](https://github.com/obra/superpowers) plugin loads when a row names it. The owner's manual skill mentions (`$name`) never auto-trigger, and you cannot run them.

| Need | Use |
|---|---|
| Recover or clarify intent, requirements, implicit decisions | `intent-elicitation` skill, only while the intent is unclear, because it interviews the owner; `consistency-auditor` for contradictions and stale decisions |
| Plan a feature | `feature-briefing` skill when the plan needs evidence from several sources, or Superpowers `brainstorming` (only while the design is open) then `writing-plans`; then `pre-mortem` before executing |
| Blast radius of a significant change, migration, rollback | `change-impact` skill |
| Fix a defect | Lint, type, format or import errors, or tests broken by a rename or refactor: `fixer`, with no root-cause investigation. Any other defect, a test that fails on behavior, or the same error after 2 attempts: Superpowers `systematic-debugging`, then `test-driven-development` |
| Execute a plan | A code plan with `### Task N` headings: Superpowers `subagent-driven-development` as the loop, with this plugin's agents (see "Plan loop" below). Any other plan or work: `implementer` per task with a brief per the offload policy, `check-runner` to verify, `skeptical-reviewer` after the changes land |
| Writing, changing or briefing work on one of these | Load the skill first: `api-design` (an endpoint, route, webhook, status code or error format); `security-principles` (code that takes user input, uploads, auth, redirects or secrets); `qa-principles` (choosing which test cases to write); `observability` (logging, metrics, health checks or alerts); `refactoring` (restructuring with behavior unchanged); `docs-principles` (a README or docs rewrite); `decision-records` (a decision to record); `release-hygiene` (a version, changelog entry or tag); `prompt-engineering` (a prompt, skill, agent definition or AGENTS.md); `ux-principles` (a page, form or user flow); `architecture-principles` (module boundaries or coupling). `implementer` does not load skills, so put the few rules that apply into its brief, not the skill text |
| A specialist question: an assessment that needs a fresh context, where a skill is for work you do yourself | The agent whose description matches: `architect` (the structure of a codebase, design or plan), `security-reviewer`, `performance-analyst` (something slow, or an optimization to verify), `qa-engineer` (test strategy or coverage gaps), `doc-curator` (a docs audit), `ux-reviewer` (how a UI looks and reads), `fact-checker` (a text against the sources it cites), `prompt-engineer` (a changed prompt, skill, agent definition or AGENTS.md, even one file; or a trace). `architect` and `security-reviewer` cost the most: use them for work that spans several modules, or for a design, plan or security surface under review. `doc-curator`, `qa-engineer` and `performance-analyst` run in their read-only mode unless the owner asked for the edit (`apply`, `write`, `optimize`). Relay every finding of an agent in this row, dropping none, in the owner's reply format, then list the decisions it leaves to the owner |
| Full project assessment, when the owner asks to assess the whole project | `architect`, `qa-engineer`, `security-reviewer` and `doc-curator` in parallel |
| Facts from outside the repository | `web-research` skill |

### Plan loop

The Superpowers `subagent-driven-development` skill supplies the loop: the order, the ledger and one task at a time. This plugin's agents fill both of its subagent roles, so where the skill's text differs from the lines below, the lines apply:

- **Implementer**: `implementer`, dispatched without overriding its model or effort: the agent's TOML fixes both, and this replaces the skill's rule to name a model at every dispatch. Its brief points to the task brief file, adds only what the offload policy's brief rule asks for and says: follow the task's test-then-code steps, commit this task locally, and write the full report (commands run, failing and passing output) to the report path. That file is a deliverable, not a temporary file, and may be long; the reply stays short.
- **Its result**: `DONE` with a non-empty "Open questions / risks" line counts as done with concerns; a stop for missing input counts as needing context; `BLOCKED — checkpoint` or `BLOCKED — turn budget` means the task is too big: split it.
- **Task reviewer**: `skeptical-reviewer`, also without overriding its model or effort (its TOML fixes both), which replaces the skill's mid-tier floor for reviewers, after each task's commit. Its brief adds the text of the task and asks what is missing, extra or misunderstood against it.
- **Verdicts are yours**: the reviewer returns doubts for you to verify, not a verdict, and your own spec and quality verdicts satisfy the skill's rule that both exist. A missing, extra or misunderstood item that you verified fails the spec check; a verified medium or high finding starts a fix round; low findings are deferred. You may reject a finding once you have verified it is wrong: record it in the ledger as a ruling.
- **Fixes**: a fresh `implementer` per fix round, briefed with the findings you verified. Review round 1 follows the task commit and round 2 reviews the fixes; this replaces the skill's five-round cap. Confirm the fixes of round 2 from their report and a run of `check-runner`, with no third review. A finding still open then goes to the skill's breaker: park it with a ruling, or rule on the smallest change that unblocks the later tasks.
- **End**: after the last task, several narrow `skeptical-reviewer` reviews in parallel replace the skill's whole-branch reviewer; they receive the deferred and parked lines of the ledger.

### Reviews and proof of done

| Situation | Do |
|---|---|
| Before a push, a pull request, a merge, a tag, or a commit on a branch that already has an upstream on the remote | `skeptical-reviewer` on `git status`, the staged diff and, for a pull request or merge, its file list; triage the findings before taking the step, because a step that looks done can be empty or partial. The exception is the implementer's task commits in the plan loop: review each one right after it |
| Before closing a task you ran against a plan, a skill, a checklist or the project's done criteria | `skeptical-reviewer` as a process review: pass the rules that applied and the steps you took, each with its evidence, and ask whether any step was skipped, misordered or claimed without evidence, because the author's own checklist misses what it forgot |
| A change with several parts | Several narrow reviews in parallel instead of one broad one, because the reviewer is cheap but weak. Each has one focus, its own paths, a concrete question and what to look for: the code, the diff or step itself, the docs against the code, architecture and organization |

Review brief: what changed as paths or a commit range, the intent in one line, rules that are not in `CLAUDE.md` or `AGENTS.md`, what is already verified, the round number and the findings already rejected. Stop after round 2: the offload rules to re-run the reviewer after fixing and before replying add no third round, so confirm the last fixes with `check-runner` and your own reading.

A PASS from `check-runner` is evidence when its report names the command and the result; read its `Not run:` line. Before a commit you make yourself, a push or a pull request, rerun yourself the single command that proves the acceptance criterion (the task's named test, or the build) and keep only its summary line.
````

</details>

<!-- END generated: recommended-prompt -->

## Other tools (Copilot, Codex)

`agent-skills` also installs in GitHub Copilot CLI and OpenAI Codex from generated copies under `ports/`; the mods stay Claude-only. Install steps are in [Install](#install); what maps to what and the limits: [docs/ports.md](docs/ports.md) (ADR 0015).

## Update

Each plugin has its own version and changelog (`plugins/<name>/CHANGELOG.md`); `main` holds only releases, so an update brings a released version, never work in progress (ADR 0027). License: [MIT](LICENSE).

| Method | Command |
|---|---|
| Automatic (recommended) | `/plugin` → Marketplaces → `mili-ssm` → Enable auto-update; it checks in interactive sessions and applies on the next session or `/reload-plugins` (the cloud script enables it) |
| Manual (shell) | `claude plugin marketplace update mili-ssm && claude plugin update agent-skills@mili-ssm` (same for each plugin), then `/reload-plugins` or a new session. `plugin update` alone does not refresh the marketplace copy |
| Manual (session) | `/plugin` → Marketplaces → `mili-ssm` → Update marketplace (refreshes and updates) |
| Copilot CLI | `copilot plugin marketplace update mili-ssm && copilot plugin update agent-skills@mili-ssm` |
| Codex | `codex plugin marketplace upgrade mili-ssm`, then copy the role files again ([Install](#install)) |

## Catalog

### Which entry point

| Entry point | Starts when | Use it for |
|---|---|---|
| Commands `/agent-skills:<name>` | You type one; they never auto-trigger | A specialist review or workflow when you decide |
| Skills | Their description matches the task, a bonus that can stay silent; force one with its command | Methods and knowledge applied while you work |
| Workers | The [offload policy](user-config/offload-policy.md) loads from the plugin's session start hook (ADR 0032) or is in your user-level `~/.claude/CLAUDE.md`, or you force one with `/agent-skills:offload <task>` | Reading, checks, browser verification, after-action review and bounded edits on Haiku/Sonnet: `check-runner`, `summarizer`, `researcher`, `implementer`, `fixer`, `ui-verifier`, `skeptical-reviewer` (plus user-scope `Explore`) |
| Superpowers | A row of the [routing table](user-config/routing.md) names its skill | Methods: brainstorming, plan writing, the plan loop, TDD, debugging, worktrees and branch finishing |

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
finishing-a-branch ◄── narrow skeptical-reviewer reviews ◄── subagent-driven-development loop
        │              (+ architect / security-reviewer     (per task: implementer ──► skeptical-reviewer)
        │                 / ux-reviewer when needed)
        └─► doc-curator + decision-records + release-hygiene
```

## Design

- Maintainer notes for agents (commands, generated files, ADR rules): [`CLAUDE.md`](CLAUDE.md) · Requirements: [`docs/requirements.md`](docs/requirements.md) · Decisions: [`docs/adr/`](docs/adr/) · Mods per surface (Desktop, VS Code, terminal): [`docs/mods-surfaces.md`](docs/mods-surfaces.md)
- Layout: one marketplace, each plugin in `plugins/<name>/`; the root keeps `docs/`, `scripts/`, the files you copy into user scope (`user-agents/`, `user-config/`) and the generated ports (`ports/`, ADR 0015).
- ADRs are cited by number; current status of each: `grep -n '^Status' docs/adr/*.md`.

## Develop

| Step | Command |
|---|---|
| Branch | Pull requests target `dev` (`gh pr create --base dev`); `main` holds only releases. An install that follows `dev` (`Mili-ssm/Agent-Skills#dev`; cloud: `AGENT_SKILLS_REF=dev`) still updates only when a version changes; to try unreleased work use `claude --plugin-dir plugins/<name>` |
| Validate structure and authoring rules | `python3 scripts/validate.py` and `claude plugin validate .` |
| Git hooks, once per clone: a commit lints, formats and type-checks its staged Python files; a push checks the pushed files and runs validate, the test suite and `claude plugin validate` (skips tools that are missing) | `uv tool install pre-commit && pre-commit install`; push checks only, without pre-commit: `git config core.hooksPath scripts/hooks` |
| Run the script tests | `uv run --with pytest pytest scripts/tests -q` |
| Lint and type-check the Python files your branch touched (each must be fully clean; [ADR 0031](docs/adr/0031-a-touched-python-file-passes-ruff-and-basedpyright.md)) | `pre-commit run --from-ref origin/dev --to-ref HEAD` |
| Regenerate the Copilot and Codex ports after changing agents, skills, commands or the offload policy | `python3 scripts/port.py` (`--check` verifies, `--report` prints the mapping) |
| Measure a description or prompt change before merging | `claude plugin eval plugins/agent-skills --ablation none --model sonnet -j 4 --runs 2 --max-cost-usd 5 --case '<glob>'`; which cases and when to rerun: [`CLAUDE.md` § Eval protocol](CLAUDE.md#eval-protocol-adr-0007-review-2026-10-30) |
| Validate and test a mod | `claude plugin validate plugins/<mod>` and `claude plugin test plugins/<mod>`; UI tests mount on every surface the site is raised on: `ToolUse` and the status line everywhere, `AbovePrompt` on terminal and desktop only (not VS Code) |
| Type-check a mod | `claude --plugin-dir plugins/<mod>` once (lays its types and tsconfig, git-ignored), then `tsc -p plugins/<mod>` |

### Release

1. On `dev`, for each plugin that changed since its last tag (`git log <name>-vX.Y.Z..dev -- plugins/<name>`; agent-skills also `ports/ user-config/ user-agents/`): pick the bump (breaking → major, feature → minor, fix → patch; under `0.y.z` a breaking change bumps the minor), set `version` in `plugins/<name>/.claude-plugin/plugin.json`, and turn `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD` above a new empty `[Unreleased]`.
2. `python3 scripts/port.py`, `python3 scripts/validate.py --release`, `claude plugin validate .`.
3. Pull request `dev` → `main` (`gh pr create --base main --head dev`), merged with a merge commit, not a squash, so `dev` can fast-forward to it; merging ships the release to everyone with auto-update.
4. Tag the merge commit for each released plugin: `git fetch origin && git tag -a <name>-vX.Y.Z -m "<name> X.Y.Z" origin/main && git push origin <name>-vX.Y.Z`.
5. Bring the merge commit back: `git switch dev && git merge --ff-only origin/main && git push origin dev`.

### Eval suites

In `plugins/agent-skills/evals/`:

- `trigger/`: one case per skill, plus `performance-analyst` and `pre-mortem`. A case passes when its skill, or the agent named in its grader, fires; `change-impact`, `intent-elicitation` and `ux-principles` accept only the skill, `performance-analyst` and `pre-mortem` only the agent.
- `no-trigger/`: five near-misses (a live bug, an email to shorten, a small flag, a TDD green step, a "why" about an idiom). A case passes when no plugin skill or agent fires; each grader names every skill and agent.
- `offload/`: `check-runner` and `summarizer` with and without the [offload policy](user-config/offload-policy.md), a verbatim-section case (passes by delegating to `summarizer` or by a bounded read), `implementer` and `ui-verifier` with it, and six `-with-hook` cases that twin the `-with-policy` ones (the table arrives from the plugin's hook, `EVAL_OFFLOAD_HOOK=on`, ADR 0032). A case passes when the worker is dispatched, its brief carries what only the conversation knew (the `implementer` case checks the decision with its reason, the off-limits file and the stop rule), the main conversation does none of the work inline, and the answer (or the file written) is right. Run it with `--scaffold --allow-tools Bash Edit Write` and a sandbox: `bubblewrap`, `socat`.
