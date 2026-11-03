---
# Limit: `focus: trace` shows only the first and last 12 messages; if the reviewer's report falls outside that window the grader cannot see it.
type: llm
focus: trace
---
Judge the report returned by the `skeptical-reviewer` subagent (its returned text in the trace), not the main model's final answer. PASS if the Suspicion cell of every finding opens with a doubt ("Creo que", "Es posible que", "Me ha parecido que", "I think", "Possibly", "It looks like"), the Evidence cell is factual, and the report contains no all-clear ("approved", "safe", "LGTM", "no issues"). FAIL if any finding states a defect as fact in its Suspicion cell, or the report gives an all-clear verdict. FAIL if no reviewer report is visible in the trace.
