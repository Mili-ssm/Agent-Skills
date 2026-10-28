---
description: Runs the architect agent on a scope, design or goal and returns its C4 map, findings, options and ADR drafts.
argument-hint: [assess|review|propose] [scope or goal]
disable-model-invocation: true
---

Dispatch the `agent-skills:architect` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
