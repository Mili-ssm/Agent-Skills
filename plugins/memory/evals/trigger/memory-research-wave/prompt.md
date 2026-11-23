---
tags: [trigger]
runs: 2
max_turns: 8
timeout_seconds: 300
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill]
---

Research how three cloud vendors document their rate limiting, using several agents in parallel to read the documentation pages, and record what we find as notes in our memory store so we can rely on them later.
