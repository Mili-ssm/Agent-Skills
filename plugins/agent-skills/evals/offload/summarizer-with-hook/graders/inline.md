---
# The main conversation does not read the long log itself.
type: regex
target: trace
match: not_contains
pattern: '"name":"Read"[^\n]*(build\.log)[^\n]*"parent_tool_use_id":null'
---
