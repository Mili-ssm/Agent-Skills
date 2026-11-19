# Brief: fact-check one synthesis against its cited notes

Read-only on the store. Check the synthesis file `{STORE}/syntheses/{SLUG}.md` against the notes it cites. Each part ends with a `Sources:` line of relative links (from `syntheses/`, e.g. `../knowledge/<domain>/<file>.md`); resolve them inside `{STORE}` and read those notes (whole, not only their conclusion, when a figure is at stake).

If `{PARTS}` is given, check only those parts, and in them only the sentences the fixer's report lists as changed; do not re-check the rest.

The writer's rules: say nothing the cited notes do not support; keep a figure's exact origin (table, model, setting, dataset); keep a `low`-confidence claim a hypothesis; start every sentence of its own reasoning with `Inference:`; when notes disagree, give both.

For every part, look first for the three kinds that recur: a figure moved to another table, model or setting; reasoning not labeled `Inference:`; an absolute statement ("no note...", "never", "always"). Then check comparisons and causal claims. For an absolute statement run `mem search "<its subject>"` and read any note it names, cited or not; one contradicting note makes the claim unsupported. List every claim that is NOT supported: overstated, contradicted, not found in the cited notes, a hypothesis stated as fact, or reasoning not labeled `Inference:`.

Write the report to `{REPORT_FILE}` (with the Write tool), one line per unsupported claim: `<part handle: the part's heading in lower case with hyphens (e.g. `shape-of-forgetting`), not its line range> | <first 8 words of the sentence> | <kind> | <note path> | <replacement sentence>`, where kind is figure-origin, unlabeled-inference, absolute or overstated. When no claim is unsupported, write only the COUNTS line. The last two lines of the file are exactly `PARTS: <handles, not headings, of the parts with an unsupported claim, comma-separated>` and `COUNTS: checked=<N> unsupported=<M>` (integers). No verdict. Write no file but `{REPORT_FILE}`.

Reply to the caller in under 4 lines: the report path, the counts. Never dispatch subagents.
