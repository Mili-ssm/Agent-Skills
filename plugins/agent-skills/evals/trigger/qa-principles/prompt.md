---
tags: [trigger]
runs: 3
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Which test cases should I write for this function?

def discount(total: float, coupon: str | None, is_member: bool) -> float:
    if total <= 0:
        raise ValueError("total must be positive")
    pct = 0
    if coupon == "SAVE10":
        pct += 10
    if is_member and total >= 100:
        pct += 5
    return round(total * (1 - min(pct, 12) / 100), 2)
