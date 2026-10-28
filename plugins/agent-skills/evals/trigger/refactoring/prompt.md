---
tags: [trigger]
runs: 2
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

I want to restructure this function without changing what it does. Where do I start?

def process(o):
    t = 0
    for i in o['items']:
        if i['type'] == 'book':
            t += i['price'] * 0.9
        elif i['type'] == 'food':
            t += i['price'] * 1.05
        else:
            t += i['price'] * 1.21
    if o['customer']['vip']:
        t = t * 0.95
    print('total', t)
    return t
