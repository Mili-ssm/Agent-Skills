---
# Passes if the reviewer is dispatched at any point in the trace, including after an implementer run.
type: regex
target: trace
pattern: 'subagent_type\W{1,8}(agent-skills:)?skeptical-reviewer\b'
---
