# frozen-main

Control texts of the synthesis trial (`../run_trials.py`, arm M): the writer brief, the checker and fixer briefs and
the `memory-synthesis` skill exactly as they were on `main` at commit `7d190a1`, so arm M runs the pipeline as it was
before inline references and arm R runs the current one on the same store copy.

| File | Taken from `main` |
|---|---|
| `writer-brief.md` | `plugins/memory/evals/synthesis/writer-brief.md` |
| `checker-brief.md` | `plugins/memory/engine/synth_briefs/checker-brief.md` (also the judge's brief, for every arm) |
| `fixer-brief.md` | `plugins/memory/engine/synth_briefs/fixer-brief.md` |
| `SKILL.md` | `plugins/memory/skills/memory-synthesis/SKILL.md` |

One change: in `fixer-brief.md` the command that copies a part, `mem show s:{SLUG}#<handle>`, has ` --stored`, because
`mem show` now prints references as labels and `mem synthesis edit` refuses text written from that form.
Do not edit these files otherwise: the comparison depends on them staying as they were.
