---
tags: [trigger]
runs: 2
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Is this endpoint safe?

@app.post("/import")
def import_cfg(req):
    cfg = yaml.load(req.body)
    db.execute(f"SELECT * FROM users WHERE name = '{cfg['name']}'")
    return redirect(req.args.get("next"))
