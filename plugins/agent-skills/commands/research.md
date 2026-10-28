---
description: Offloads web research on one or more concrete questions to parallel researcher subagents (Haiku) and returns cited findings.
argument-hint: <question(s)>
disable-model-invocation: true
---

Load the `agent-skills:web-research` skill. Split the request into independent questions and dispatch one `agent-skills:researcher` subagent per question in parallel: $ARGUMENTS

Then reconcile their findings and answer with citations.
