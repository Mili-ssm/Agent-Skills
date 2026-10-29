---
type: regex
target: trace
match: not_contains
pattern: '\"skill\W{1,8}(agent-skills:)?(api-design|architecture-principles|change-impact|decision-records|docs-principles|feature-briefing|intent-elicitation|observability|qa-principles|refactoring|release-hygiene|security-principles|ux-principles|web-research)\b|subagent_type\W{1,8}(agent-skills:)?(architect|check-runner|consistency-auditor|doc-curator|fixer|implementer|performance-analyst|pre-mortem|qa-engineer|researcher|security-reviewer|summarizer|ui-verifier|ux-reviewer)\b'
---
