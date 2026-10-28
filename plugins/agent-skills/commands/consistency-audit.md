---
description: Runs the consistency-auditor agent to find contradictions, ambiguities and stale decisions between code and docs.
argument-hint: [project|feature|change] [scope]
disable-model-invocation: true
---

Dispatch the `agent-skills:consistency-auditor` subagent with this task: $ARGUMENTS

If no arguments were given, ask for the scope in one question first. When the subagent returns, relay its report unchanged, then list the decisions it says belong to the owner.
