---
# The main conversation does not run the tests itself; subagent calls carry a parent_tool_use_id.
type: regex
target: trace
match: not_contains
pattern: '"name":"Bash"[^\n]*(unittest|pytest)[^\n]*"parent_tool_use_id":null'
---
