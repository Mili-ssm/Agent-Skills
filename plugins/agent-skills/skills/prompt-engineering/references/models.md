# Writing for each model

As of 2026-10. Model behavior changes with each release: date every claim and re-measure after a model change. Sources: Anthropic *Prompting best practices* and its per-model pages (platform.claude.com, "Prompting Claude Haiku 5.5"); ADRs 0010, 0012 and 0013 of this repo.

## Haiku (cheap workers: reading, checks, search)

| Fact | Consequence |
|---|---|
| Default `effort` is `medium`; `low` skips searches and stops early. Measured by Anthropic: low → medium roughly halved early stops and more than doubled output tokens | Use `low` for bounded reading and checks with a clear end; use `medium` where finishing matters more than tokens (search, multi-step work) |
| Needs explicit completion criteria and more guidance than larger models | State "done means …" and the output format with an example |
| Searches better when given today's date and told its training data ends; a blanket "always search" made it search on half of the prompts that needed none (measured by Anthropic) | Give the date and when to search, not an order to always search |
| User-supplied text must not be placed inside a `tool_result` (Anthropic, Haiku 5.5 page) | Keep inputs in the user turn |

## Sonnet (implementation, fixes, reviews)

- Measured here (ADR 0012): a Sonnet main conversation did not delegate to a Sonnet implementer; delegation pays only when the worker is cheaper or the context is protected.

## Opus (main conversation, architecture, pre-mortems)

| Fact | Consequence |
|---|---|
| Proactive: tends to over-engineer and to act where it was asked to suggest | Add a scope guard; use the verb that matches the wanted action |
| Needs less explanation than Haiku | Cut steps it would take anyway; keep reasons and limits |
| Measured here (ADR 0012): delegated code 0/3 → 3/3 when its trigger row was rewritten (a ~20-line threshold, a review step, "even when it looks easy"); the phrase alone was not isolated | Name the case where the model's own judgment says "inline" |

## Every model

- Test each prompt with every model it targets; a prompt tuned on Opus can under-specify for Haiku.
- `effort` and adaptive thinking replace hand-tuned thinking budgets (prompt-rules.md).
