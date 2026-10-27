# 0001 Knowledge in skills, roles in agents

Status: accepted · Date: 2026-10-27

## Context

Specialist agents need large principle catalogs (SOLID, ISTQB, Nielsen…). Embedding them per agent bloats context and duplicates content; the main conversation also benefits from the same catalogs.

## Decision

- Catalogs live in knowledge skills (`*-principles`, `decision-records`) with a short index in `SKILL.md` and detail in `references/`.
- Agents hold only role, process and output format. They preload knowledge skills via the `skills:` frontmatter and, as fallback, invoke them with the `Skill` tool.

## Alternatives

| Option | Rejected because |
|---|---|
| Catalog inside each agent | Duplication; always-loaded tokens |
| Skills only, no agents | Loses fresh-context independent review |

## Consequences

- One edit updates every consumer of a catalog.
- Agents depend on skill names staying stable.

## Review 2026-10-27

Claude Code 2.1.311: plugin installed from GitHub; `agent-skills:doc-curator` reported `docs-principles` and `decision-records` preloaded and quoted `docs-principles` verbatim. Bare names resolve inside the plugin.

## Revisit if

A Claude Code release stops resolving bare skill names for plugin agents (missing skills are skipped with a debug-log warning).
