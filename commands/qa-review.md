---
description: Runs the qa-engineer agent to assess a test suite, design test cases, root-cause flaky tests or run mutation testing.
argument-hint: [assess|design|flaky|strength] [scope]
disable-model-invocation: true
---

Dispatch the `agent-skills:qa-engineer` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
