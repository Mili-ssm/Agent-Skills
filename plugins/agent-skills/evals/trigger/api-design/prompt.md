---
tags: [trigger]
runs: 2
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Design the HTTP endpoints for creating and cancelling orders in our service. Mobile clients retry requests on flaky networks.
