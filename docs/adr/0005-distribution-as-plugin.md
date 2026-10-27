# 0005 Distribute as a Claude Code plugin

Status: accepted · Date: 2026-10-27

## Context

Owner uses ephemeral cloud environments; manual copying per session is error-prone.

## Decision

Repo root is both a plugin (`.claude-plugin/plugin.json`, `skills/`, `agents/`) and a single-plugin marketplace (`.claude-plugin/marketplace.json`). Manual copy to `~/.claude/{skills,agents}` remains supported.

## Consequences

- One install command per environment.
- Plugin skills may be namespaced (`agent-skills:<name>`); see ADR 0001 revisit trigger.

## Revisit if

Install fails in the cloud environment, or a multi-plugin split (e.g. stack skills) is needed.
