---
tags: [trigger]
runs: 2
max_turns: 12
timeout_seconds: 600
plugins: ["../../.."]
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Review this signup form for usability and accessibility:

<form>
  <input placeholder="Email">
  <input type="password" placeholder="Password">
  <div onclick="submit()" style="color:#aaa">Sign up</div>
</form>
