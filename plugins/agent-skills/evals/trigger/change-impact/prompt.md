---
tags: [trigger]
runs: 3
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

I want to rename the user_id column to account_id across our service, its database and its public API. What will this affect and how should we roll it out safely?
