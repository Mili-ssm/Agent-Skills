# Diátaxis (Procida)

Four documentation types answering four needs. Mixing them is the most common structural defect.

| Type | Orientation | Reader state | Form | Anti-pattern |
|---|---|---|---|---|
| Tutorial | Learning | Newcomer, studying | Guided lesson with guaranteed success | Explaining theory mid-lesson; offering choices |
| How-to | Task | Competent, working | Numbered steps toward a goal | Teaching basics; covering every variant |
| Reference | Information | Working, looking up | Dry, complete, structured like the code | Opinions, tutorials inside API docs |
| Explanation | Understanding | Studying, reflecting | Discursive: context, why, alternatives | Step-by-step instructions |

## Mapping to repo artifacts

| Artifact | Type |
|---|---|
| README quickstart | Tutorial (short) |
| `docs/how-to/*`, runbooks | How-to |
| API docs, CLI `--help`, config tables, docstrings | Reference |
| ADRs, architecture overview | Explanation |
| CLAUDE.md / AGENTS.md | Reference (commands, conventions) |

## Diagnostic questions

- Is the reader doing or studying? (how-to/tutorial vs. reference/explanation)
- Would removing this paragraph break the reader's task? If no and it is not explanation → cut or move.
