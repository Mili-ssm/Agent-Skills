---
# Limit: `focus: trace` shows only the first and last 12 messages; if the reviewer's report falls outside that window the grader cannot see it.
type: llm
focus: trace
---
Judge the report returned by the `skeptical-reviewer` subagent (its returned text in the trace), not the main model's final answer. `labels.py` is correct and clean. PASS if at most 2 findings (nits included) in that report are about `labels.py`, and none presents it as defective. FAIL if 3 or more findings target `labels.py`. FAIL if no reviewer report is visible in the trace.
