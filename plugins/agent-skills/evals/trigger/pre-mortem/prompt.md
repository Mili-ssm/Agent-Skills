---
tags: [trigger]
runs: 2
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Here is my plan for next sprint. Before I start, stress-test it and tell me how it could fail:

1. Replace our hand-written auth with an OAuth provider.
2. Migrate all existing user passwords in one batch job on Friday night.
3. Delete the old auth tables once the job finishes.
4. Ship the new login page on Monday.
