# Brief: fact-check one synthesis against its cited notes

Read-only on the store. Check the synthesis file `{STORE}/syntheses/{SLUG}.md` against the notes it cites. Each part ends with a `Sources:` line of relative links (from `syntheses/`, e.g. `../knowledge/<domain>/<file>.md`); resolve them inside `{STORE}` and read those notes (whole, not only their conclusion, when a figure is at stake).

The writer's rules: say nothing the cited notes do not support; keep a figure's exact origin (table, model, setting, dataset); keep a `low`-confidence claim a hypothesis; start every sentence of its own reasoning with `Inference:`; when notes disagree, give both.

For every part, check figures, comparisons, causal claims, and absolute statements ("no note…", "never", "always"). List every claim that is NOT supported: overstated, contradicted, not found in the cited notes, a hypothesis stated as fact, or reasoning not labeled `Inference:`.

Write the report to `{REPORT_FILE}` (with the Write tool) as a numbered list, one item per claim: the part heading; the synthesis sentence quoted; the verdict; the note passage quoted with its file; the replacement sentence. End the file with: claims checked, how many unsupported, and a verdict: keep as is / keep with fixes / rewrite. The very last line of the file is exactly `COUNTS: checked=<N> unsupported=<M>` (integers).

Reply to the caller in under 4 lines: the report path, the counts, the verdict. Never dispatch subagents.
