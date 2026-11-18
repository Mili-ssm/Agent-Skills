# Brief: fact-check one synthesis against its cited notes

Read-only on the store. Check the synthesis file `{STORE}/syntheses/{SLUG}.md` against the notes it cites. Each part ends with a `Sources:` line of relative links (from `syntheses/`, e.g. `../knowledge/<domain>/<file>.md`); resolve them inside `{STORE}` and read those notes (whole, not only their conclusion, when a figure is at stake).

`{UNITS_FILE}` lists every part's sentences with a number and the notes linked after each (its references). Check a sentence against its references first. A sentence that states a finding and has no reference, or whose references do not support it while another source of the part does, is a reference problem, not an unsupported claim: write a `REF:` line for it and no claim line, because a later step deletes every sentence listed as a claim. A sentence is an unsupported claim only when no source of the part supports it as written; a sentence that a source supports but that overstates it or moves a figure to another setting is a claim, not a reference problem.

If `{PARTS}` is given, check only those parts, and in them only the sentences the fixer's report lists as changed; do not re-check the rest.

The writer's rules: say nothing the cited notes do not support; keep a figure's exact origin (table, model, setting, dataset); keep a `low`-confidence claim a hypothesis; start every sentence of its own reasoning with `Inference:`; when notes disagree, give both.

For every part, look first for the three kinds that recur: a figure moved to another table, model or setting; reasoning not labeled `Inference:`; an absolute statement ("no note...", "never", "always"). Then check comparisons and causal claims. For an absolute statement run `mem search "<its subject>"` and read any note it names, cited or not; one contradicting note makes the claim unsupported. List every claim that NO source of the part supports as written: overstated against the source that comes closest, contradicted, found in no source of the part, a hypothesis stated as fact, or reasoning not labeled `Inference:`.

Write the report to `{REPORT_FILE}` (with the Write tool), one line per unsupported claim: `<part handle: the part's heading in lower case with hyphens (e.g. `shape-of-forgetting`), not its line range> | <first 8 words of the sentence> | <kind> | <note path> | <replacement sentence>`, where kind is figure-origin, unlabeled-inference, absolute or overstated. A replacement sentence carries no links: the fixer keeps the links that follow the sentence.

After the claim lines, one line per reference problem, with the sentence number and the paths copied exactly from `{UNITS_FILE}`: `REF: <part handle> | <sentence number> | missing | <path of the source that supports it>` for a finding with no reference, or `REF: <part handle> | <sentence number> | wrong <path of the reference that does not support it> | <path of the source that does, or none>`.

The last two lines of the file are exactly `PARTS: <handles, not headings, of the parts with an unsupported claim, comma-separated; nothing after the colon when there is none>` and `COUNTS: checked=<N> unsupported=<M>` (integers). `checked` counts every sentence you examined; `unsupported` counts the claim lines only, never the `REF:` lines. With no unsupported claim, write no claim line and still write the `REF:` lines, `PARTS:` and `COUNTS:`. No verdict. Write no file but `{REPORT_FILE}`.

<example>
shape-of-forgetting | Spaced review always beats massed practice in every | absolute | ../knowledge/psychology/spaced-review-beat-massed-review.md | Spaced review beat massed practice in the one trial the note reports.
REF: shape-of-forgetting | 4 | missing | ../knowledge/psychology/recall-falls-fastest-in-the-first-day.md
REF: shape-of-forgetting | 7 | wrong ../knowledge/psychology/recall-falls-fastest-in-the-first-day.md | ../knowledge/psychology/spaced-review-beat-massed-review.md
REF: spacing | 2 | wrong ../knowledge/psychology/spaced-review-beat-massed-review.md | none
PARTS: shape-of-forgetting
COUNTS: checked=31 unsupported=1
</example>

Reply to the caller in under 4 lines: the report path, the counts. Never dispatch subagents.
