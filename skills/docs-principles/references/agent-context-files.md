# Agent context files (CLAUDE.md, AGENTS.md, skills)

## Evidence

*Evaluating AGENTS.md* (Gloaguen et al., ETH Zürich / LogicStar, ICLR 2026, arXiv:2602.11988): context files tended to **lower** task success and raised cost >20%; LLM-generated files were worse than developer-written ones; files helped mainly when they supplied information the agent could not discover. Authors recommend describing only minimal requirements.

## Include

| Content | Example |
|---|---|
| Non-discoverable commands | `uv run pytest -m "not slow"`, required env vars |
| Conventions that contradict defaults | "Errors return HTML fragments, not JSON" |
| Hard constraints | "No new JS files; htmx attributes only" |
| Gotchas that cost time | "Tests need Postgres on :5433, not :5432" |
| Pointers | "Decisions: docs/adr/" |

## Exclude

- Architecture tours, directory listings, tech-stack summaries (discoverable).
- Generic advice ("write clean code", "add tests").
- Duplicates of README or ADR content.
- Instructions that trigger broad exploration without need ("always read all files first").

## Skills specifically

- `description` is paid every turn: one sentence, trigger-first, concrete keywords.
- `SKILL.md` = index + process; detail in `references/`.
- Test that the skill triggers and changes behavior (Superpowers `writing-skills`).

## Audit questions

1. Could the agent find this in < 2 tool calls? → remove.
2. Has this line ever changed agent behavior? Unknown → test or remove.
3. Is it still true today? → verify against code.
