# Writing for each model

As of 2026-11 (Claude 5.5 models). Model behavior changes with each release: date every claim and re-measure after a model change. Sources: Anthropic *Prompting best practices*, its per-model pages ("Prompting Claude Haiku 5.5", "Prompting Claude Sonnet 5.5"), *Effort* and *Optimizing for cost and intelligence* (platform.claude.com, read 2026-11-12); ADRs 0010, 0012, 0013 and 0018 of this repo.

## Haiku (cheap workers: reading, checks, search)

| Fact | Consequence |
|---|---|
| Default `effort` is `medium`; `low` skips searches and stops early. Measured by Anthropic: low → medium roughly halved early stops and more than doubled output tokens | Use `low` for bounded reading and checks with a clear end; use `medium` where finishing matters more than tokens (search, multi-step work) |
| Needs explicit completion criteria and more guidance than larger models | State "done means …" and the output format with an example |
| Searches better when given today's date and told its training data ends; a blanket "always search" made it search on half of the prompts that needed none (measured by Anthropic) | Give the date and when to search, not an order to always search |
| User-supplied text must not be placed inside a `tool_result` (Anthropic, Haiku 5.5 page) | Keep inputs in the user turn |
| Priced 20× below Sonnet per token up to 100k prompt tokens (5× above). Measured by Anthropic on a defect-search benchmark (130 planted defects, 10 runs): F1 0.58 at `medium` against Sonnet's 0.76 at `high`, for a quarter of the cost | Suits work whose output the caller can check; as a reviewer it is a cheap second reader, not the only gate for defects |

## Sonnet (implementation, fixes, reviews)

- Measured here (ADR 0012): a Sonnet main conversation did not delegate to a Sonnet implementer; delegation pays only when the worker is cheaper or the context is protected.
- Effort (Anthropic): for agentic coding and multistep tool use, `medium` for well-specified tasks and `high` for harder or longer ones; measured on a SWE-bench Pro subset, `medium` scored about 7 points below `high`. At `low` it can skip verifying a change; at `low` and `medium` on long tasks it is more likely to stop and check in before finishing, so a subagent that cannot ask needs "done means …".

## Opus (main conversation, architecture, pre-mortems)

| Fact | Consequence |
|---|---|
| Proactive: tends to over-engineer and to act where it was asked to suggest | Add a scope guard; use the verb that matches the wanted action |
| Needs less explanation than Haiku | Cut steps it would take anyway; keep reasons and limits |
| Effort, measured by Anthropic on the defect-search benchmark: `low` F1 0.49 (below Haiku), `medium` 0.83, `high` 0.85, at about $38, $200 and $236 a run | Never run a judgment agent on Opus `low`; `high` over `medium` buys about 2 points for about 18% more |
| Measured here (ADR 0012): delegated code 0/3 → 3/3 when its trigger row was rewritten (a ~20-line threshold, a review step, "even when it looks easy"); the phrase alone was not isolated | Name the case where the model's own judgment says "inline" |

## Every model

- Test each prompt with every model it targets; a prompt tuned on Opus can under-specify for Haiku.
- `effort` and adaptive thinking replace hand-tuned thinking budgets (prompt-rules.md).
