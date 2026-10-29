---
tags: [trigger]
runs: 3
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Our FastAPI endpoint `/reports` got slow after last week's release: p95 latency went from 120 ms to 900 ms under the same traffic. Find out why and what we should change.
