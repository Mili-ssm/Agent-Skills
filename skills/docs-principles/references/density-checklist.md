# Density checklist

Apply per paragraph. Each "yes" → cut, merge or move.

| # | Check | Action |
|---|---|---|
| 1 | Restates what code, types, signature or `--help` already say? | Cut; link if needed |
| 2 | Repeats a fact stated elsewhere in docs? | Keep one source, link |
| 3 | Restates the heading above it? | Cut sentence |
| 4 | Contains filler ("simply", "easily", "powerful", "it is important to note")? | Delete words |
| 5 | Hedges without information ("might possibly", "in some cases")? | State condition or cut |
| 6 | Prose listing ≥ 3 parallel items or options? | Convert to list/table |
| 7 | Prose comparing ≥ 2 things on ≥ 2 attributes? | Convert to table |
| 8 | Multiple examples showing the same point? | Keep the best one |
| 9 | Describes history ("we used to…") without current relevance? | Move to ADR or cut |
| 10 | Unverifiable or stale claim (path, command, version)? | Verify or delete |
| 11 | Mixed Diátaxis types in one section? | Split |
| 12 | Long setup prose that a script/Makefile target could replace? | Replace with command |

## Keep (never cut for brevity)

- Rationale, constraints, rejected alternatives.
- Gotchas and non-obvious behavior (the most valuable docs per token).
- Exact commands, versions, env vars.
- Security and data-loss warnings.

## Density heuristics

- Target ≥ 1 non-derivable fact per sentence.
- A section a newcomer would skip twice is a candidate for deletion.
- If a doc grows, ask what can be removed in the same change.
