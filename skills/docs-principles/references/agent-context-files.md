# Agent context files (CLAUDE.md, AGENTS.md)

## Evidence

*Evaluating AGENTS.md* (Gloaguen et al., ETH Zürich / LogicStar, ICLR 2026, arXiv:2602.11988): context files tended to **lower** task success and raised cost > 20%; LLM-generated files did worse than developer-written ones; files helped mainly when they supplied information the agent could not discover. The authors recommend minimal requirements only.

## Include

| Content | Example |
|---|---|
| Non-discoverable commands | `uv run pytest -m "not slow"`, required env vars |
| Conventions that contradict defaults | "Errors return HTML fragments, not JSON" |
| Hard constraints | "No new JS files; htmx attributes only" |
| Costly gotchas | "Tests need Postgres on :5433, not :5432" |
| Pointers | "Decisions: docs/adr/" |

## Leave out

- Architecture tours, directory listings, stack summaries: the agent discovers them in a few tool calls.
- Generic advice ("write clean code", "add tests"): already the model's default.
- Copies of README or ADR content: they drift.
- Blanket exploration orders ("always read all files first"): they inflate cost without raising success.

## Audit questions

1. Could the agent find this in < 2 tool calls? → remove.
2. Has this line ever changed agent behavior? Unknown → test or remove.
3. Is it still true? → verify against code.

Skill and subagent files follow [prompt-authoring.md](prompt-authoring.md).
