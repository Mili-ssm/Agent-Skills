---
# The main conversation never reads the whole runbook: it delegates, or reads only the range it located.
type: regex
target: trace
match: not_contains
pattern: '("name":"Read","input":\{"file_path":"[^"]*runbook\.md"\}|"command":"cat [^"]*runbook\.md")[^\n]*"parent_tool_use_id":null'
---
