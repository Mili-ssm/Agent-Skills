# Brief: judge the note links of one synthesis

Read-only on the store. `{UNITS_FILE}` lists the parts of the synthesis `{STORE}/syntheses/{SLUG}.md`: under each `## <part handle>`, numbered sentences as `<number> | <sentence> | <paths of the notes linked after it, or ->`, then a `Sources:` line. The paths are relative to `{STORE}/syntheses/`.

Do two things for every numbered sentence.

1. Say whether it states a finding: a fact, a figure, a result, or what a study or an author says. A sentence of reasoning (it starts with `Inference:`), a sentence that only connects two others, a heading-like label, or a remark such as "Confidence: low." is not a finding.
2. For each note linked after it, read that note (whole when a figure is at stake) and say whether the note supports the sentence as written: the same fact, and a figure in the same setting (table, model, dataset). Judge only the linked note: another note that would support the sentence does not make the link right.

Write the report to `{REPORT_FILE}` (with the Write tool), one line per sentence and one per link, in the order of `{UNITS_FILE}`:

U: <part handle> | <sentence number> | finding
U: <part handle> | <sentence number> | other
P: <part handle> | <sentence number> | <path of the linked note, copied exactly> | yes
P: <part handle> | <sentence number> | <path of the linked note, copied exactly> | no

The last line is exactly `COUNTS: units=<number of U lines> pairs=<number of P lines> no=<number of P lines that end in no>`. No verdict, no other text. Write no file but `{REPORT_FILE}`.

<example>
U: shape-of-forgetting | 1 | other
U: shape-of-forgetting | 2 | finding
P: shape-of-forgetting | 2 | ../knowledge/psychology/recall-falls-fastest-in-the-first-day.md | yes
U: shape-of-forgetting | 3 | finding
P: shape-of-forgetting | 3 | ../knowledge/psychology/spaced-review-beat-massed-review.md | no
COUNTS: units=3 pairs=2 no=1
</example>

Reply to the caller in under 3 lines: the report path and the counts. Never dispatch subagents.
