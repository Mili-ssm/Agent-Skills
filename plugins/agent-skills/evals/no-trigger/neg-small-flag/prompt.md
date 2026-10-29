---
tags: [no-trigger]
runs: 3
max_turns: 6
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

I want to add a `--dry-run` flag to my 40-line Python script that deletes old log files: with the flag it should only print what it would delete. How should I do it?
