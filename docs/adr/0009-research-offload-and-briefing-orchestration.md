# 0009 Research offload to Haiku; briefing orchestrated from the main thread

Status: accepted · Date: 2026-10-27

## Context

Web searching and page reading burn main-model tokens. Planning a feature needs several evidence sources (docs, code, requirements, external practice) contrasted before deciding. Claude Code subagents cannot dispatch other subagents or ask the user questions.

## Decision

- `researcher` subagent on `model: haiku` does all searching/reading for one question and returns a ≤ 300-word cited report; `web-research` skill defines the protocol (source hierarchy, output contract) and fans out parallel researchers.
- `feature-briefing` is a skill, not an agent: the main thread frames (Superpowers `brainstorming` if installed), dispatches researcher/consistency-auditor/specialists in parallel, decides with the owner, then runs `change-impact`, the plan and `pre-mortem`.
- Commands: `/agent-skills:research`, `/agent-skills:brief`.

## Alternatives

| Option | Rejected because |
|---|---|
| Planner/orchestrator as a subagent | Cannot spawn subagents nor interview the owner |
| Main model searches directly | Raw pages bloat the expensive context |

## Consequences

Research quality is bounded by Haiku; decisive facts may need one main-model check.

## Revisit if

Subagents gain nested dispatch, or Haiku research reports show frequent unsupported claims.
