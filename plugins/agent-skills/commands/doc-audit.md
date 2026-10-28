---
description: Runs the doc-curator agent to verify docs against code and compress them; edits only with 'apply'.
argument-hint: [audit|apply] [paths]
disable-model-invocation: true
---

Dispatch the `agent-skills:doc-curator` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
