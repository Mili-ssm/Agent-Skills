# Diátaxis (Procida)

Four documentation types for four reader needs. Mixing them is the most common structural defect.

| Type | Orientation | Reader state | Form | Anti-pattern |
|---|---|---|---|---|
| Tutorial | Learning | Newcomer, studying | Guided lesson with guaranteed success | Theory mid-lesson; offering choices |
| How-to | Task | Competent, working | Numbered steps to a goal | Teaching basics; covering every variant |
| Reference | Information | Working, looking up | Dry, complete, shaped like the code | Opinions or tutorials inside API docs |
| Explanation | Understanding | Studying, reflecting | Context, why, alternatives | Step-by-step instructions |

## Mapping to repo artifacts

| Artifact | Type |
|---|---|
| README quickstart | Tutorial (short) |
| `docs/how-to/*`, runbooks | How-to |
| API docs, CLI `--help`, config tables, docstrings | Reference |
| ADRs, architecture overview | Explanation |
| CLAUDE.md / AGENTS.md | Reference: commands, conventions, constraints, gotchas |

## Diagnostic questions

- Is the reader doing or studying? (how-to/tutorial vs. reference/explanation)
- Would removing this paragraph break the reader's task? If not, and it is not explanation, cut or move it.
