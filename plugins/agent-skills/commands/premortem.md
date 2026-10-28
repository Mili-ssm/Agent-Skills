---
description: Runs the pre-mortem agent on a plan or spec before execution and returns failure stories, risks, amendments and kill criteria.
argument-hint: [plan path]
disable-model-invocation: true
---

Dispatch the `agent-skills:pre-mortem` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
