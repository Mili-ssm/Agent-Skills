---
tags: [trigger]
runs: 3
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Our support subagent keeps ignoring this rule and still answers billing questions itself. How should I rewrite it so Claude actually follows it?

IMPORTANT!!! You MUST NEVER answer billing questions. NEVER. If in doubt, ALWAYS escalate.
