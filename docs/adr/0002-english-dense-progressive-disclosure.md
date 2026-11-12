# 0002 English, dense, progressive disclosure

Status: accepted · Date: 2026-10-27

## Context

Context files that restate discoverable information lower agent success and raise cost >20% (Gloaguen et al., *Evaluating AGENTS.md*, ICLR 2026, arXiv:2602.11988). Skill descriptions are paid on every turn.

## Decision

- Skill/agent content in English (fewer tokens, matches model training and tool vocabulary). Interviews follow the owner's language (`intent-elicitation`); the owner's Spanish is an authoring preference of this repo, not plugin behavior.
- Budgets per N1 (`docs/requirements.md`); tables over prose; one concept per section.
- `SKILL.md` = index + process; `references/*.md` = detail read only when needed.

## Alternatives

| Option | Rejected because |
|---|---|
| Spanish content | More tokens; tool and model vocabulary is English |
| Long single-file skills | Every token loads on trigger; partial reads miss content |

## Consequences

- Owner reviews English content.
- `scripts/validate.py` enforces budgets.

## Revisit if

Owner prefers Spanish content, or trigger evals (ADR 0007) regress after a density change.

## Review 2026-11-12

The Context sentence on *Evaluating AGENTS.md* is stronger than the paper (arXiv:2602.11988 v3, a preprint): context files did not significantly change task success and raised cost by 20–23% (LLM-generated) or up to 19% (developer-written). The Decision stands on the cost finding; `context-files.md` now states the result (ADR 0018).
