---
# The main conversation does not drive the browser itself.
type: regex
target: trace
match: not_contains
pattern: '"name":"(Bash|mcp__[a-z_]*playwright[a-z_]*)"[^\n]*(playwright|chromium|browser_)[^\n]*"parent_tool_use_id":null'
---
