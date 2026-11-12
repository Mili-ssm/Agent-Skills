---
description: Runs the fact-checker agent to compare the claims of a document, or a list of claims, against the sources they cite; read-only.
argument-hint: [document or claims] [source files]
disable-model-invocation: true
---

Dispatch the `agent-skills:fact-checker` subagent with the task below instead of doing its work inline, because a fresh context is not anchored on the author's reading and returns only a report.

Task: $ARGUMENTS

- Brief it self-contained: the document or claims, the local source files and which claim rests on which, and how the text marks the author's own reasoning, because it starts without this conversation.
- A source available only as a URL: save a text copy of the page itself first (not a summary of it) and pass its path.
- No arguments: use the document written or discussed in this conversation and the sources it cites; say which you assumed.
- If it stops for a missing input (claims or a source), ask the owner for exactly that, then dispatch once more with it added.
- Relay its report in full, dropping no findings; then list the decisions it leaves to the owner, or say there are none.
