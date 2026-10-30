# Tools for agents: design and descriptions

Sources (current as of 2026-10): Anthropic *Writing effective tools for agents* (anthropic.com/engineering/writing-tools-for-agents); *Structured outputs* (platform.claude.com/docs/en/build-with-claude/structured-outputs). Applies to MCP servers, custom tools and CLI scripts an agent calls.

## Design

| Rule | Why |
|---|---|
| Few tools that match whole workflows (`schedule_event`), not one per API endpoint (`list_users`, `list_events`, `create_event`) | Each call spends context; the agent chains fewer steps |
| No overlapping tools; namespace related ones (`asana_search`, `jira_search`) | Overlap makes the choice ambiguous |
| Return what the agent acts on: names and short ids, not UUIDs and internal fields | Low-signal fields fill the context |
| Offer a `response_format` (`concise` / `detailed`) | Measured by Anthropic: a concise reply took 72 tokens against 206 for the detailed one |
| Paginate, filter and truncate by default, and say how to get more | Claude Code caps a tool response at 25,000 tokens by default |
| Errors say what to change ("`date` must be YYYY-MM-DD; got 03/04") | An opaque error makes the agent guess |

## Descriptions

- Write for a new colleague: what the tool does, when to use it instead of its neighbor, input formats, niche terms, side effects.
- Name parameters unambiguously (`user_id`, not `user`).
- Calm wording: "CRITICAL: you MUST use this tool" overtriggers on current models.
- Small description changes move results: evaluate them like prompts (evaluation.md).

## Structured outputs

| Fact | Use |
|---|---|
| `output_config.format` constrains the reply to a JSON schema | Parsing must never fail |
| `strict: true` on a tool constrains its input | Only on critical tools; the docs list limits (about 20 strict tools, 24 optional parameters) |
| Reasoning fields stay short ("a short explanation") | A step-by-step field inflates output without better answers |

## Scripts as tools

- A deterministic script beats an LLM step for anything computable (outlines, counts, validation): zero model tokens, same answer every time.
- Print a compact summary and point to files for detail, so the caller reads only what it needs.
