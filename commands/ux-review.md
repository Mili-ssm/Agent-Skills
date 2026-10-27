---
description: Runs the ux-reviewer agent on a running UI or its templates and returns severity-rated usability and accessibility findings with evidence.
argument-hint: <url or templates path> [flows]
disable-model-invocation: true
---

Dispatch the `agent-skills:ux-reviewer` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
