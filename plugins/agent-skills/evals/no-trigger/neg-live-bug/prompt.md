---
tags: [no-trigger]
runs: 3
max_turns: 6
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Since this morning my FastAPI endpoint `/profile` returns 500. The log shows `KeyError: 'user_id'` raised in `get_profile`. What is the quickest way to find the cause?
