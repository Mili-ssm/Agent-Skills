---
tags: [trigger]
runs: 3
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

We removed the deprecated /v1/export endpoint. Write the commit message and the changelog entry, and tell me which version number we should release.
