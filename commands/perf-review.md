---
description: Runs the performance-analyst agent to baseline, profile and report measured improvements; optimizes only when asked.
argument-hint: <target: endpoint, command or page> [metric/target]
disable-model-invocation: true
---

Dispatch the `agent-skills:performance-analyst` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
