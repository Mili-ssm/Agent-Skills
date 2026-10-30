---
name: "research"
description: "Offloads web research on one or more concrete questions to parallel researcher subagents and returns cited findings."
argument-hint: "<question(s)>"
disable-model-invocation: true
---

Load the `agent-skills:web-research` skill and follow its workflow for: <the arguments the user gave with this command; empty if none>

If no question was given, ask for it in one question first. Take at most 5 questions; merge related ones first, and ask which matter most only if more than 5 remain.
