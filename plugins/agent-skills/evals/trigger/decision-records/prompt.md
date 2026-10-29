---
tags: [trigger]
runs: 3
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

We decided to move from SQLite to Postgres because production will run 3 replicas. Write this decision up properly so future devs know why.
