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
