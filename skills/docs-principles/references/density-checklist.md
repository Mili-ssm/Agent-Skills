# Density checklist

Apply per paragraph. Each "yes" → cut, merge or move.

| # | Check | Action |
|---|---|---|
| 1 | Restates code, types, signatures or `--help`? | Cut; link if needed |
| 2 | Repeats a fact stated elsewhere? | Keep one source, link |
| 3 | Restates its heading? | Cut the sentence |
| 4 | Filler ("simply", "easily", "powerful", "it is important to note")? | Delete the words |
| 5 | Hedge without a condition ("might possibly", "in some cases")? | State the condition or cut |
| 6 | Prose listing ≥ 3 parallel items? | List or table |
| 7 | Prose comparing ≥ 2 things on ≥ 2 attributes? | Table |
| 8 | Several examples of one point? | Keep the best |
| 9 | History without current relevance? | Move to an ADR or cut |
| 10 | Unverifiable or stale path, command, version? | Verify or delete |
| 11 | Mixed Diátaxis types in one section? | Split |
| 12 | Setup prose a script/Makefile target could replace? | Replace with the command |
| 13 | Explains a concept the reader (or model) already knows? | Cut; keep only the project-specific twist |

## Keep, even when long

- Rationale, constraints, rejected alternatives.
- Gotchas and non-obvious behavior: the highest value per token.
- Exact commands, versions, env vars.
- Security and data-loss warnings.

## Heuristics

- Target ≥ 1 non-derivable fact per sentence.
- A section a newcomer skips twice is a deletion candidate.
- When a doc grows, remove something in the same change.
