---
tags: [trigger]
runs: 2
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Our Python service mixes domain logic with SQLAlchemy queries and HTTP handling in every module. Changing one business rule touches five files. How should we restructure the architecture?
