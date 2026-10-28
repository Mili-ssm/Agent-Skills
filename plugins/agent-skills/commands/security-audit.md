---
description: Runs the security-reviewer agent for a source-to-sink review, STRIDE threat model or design review.
argument-hint: [review|threat-model|design] [scope]
disable-model-invocation: true
---

Dispatch the `agent-skills:security-reviewer` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
