---
tags: [no-trigger]
runs: 3
max_turns: 6
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

I am doing TDD and this test is red, as expected:

```python
def test_total_applies_discount():
    assert total([10, 10], discount=0.5) == 10
```

Write the minimal implementation of `total(prices, discount=0.0)` that makes it pass.
