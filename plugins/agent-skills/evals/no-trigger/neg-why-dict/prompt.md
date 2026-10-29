---
tags: [no-trigger]
runs: 3
max_turns: 6
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Why would someone write the lookup like this instead of just using a list?

```python
users = {u.id: u for u in rows}
owner = users[order.owner_id]
```
