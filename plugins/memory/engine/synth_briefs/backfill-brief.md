# Brief: say which note supports each sentence of one synthesis

Read-only. `{UNITS_FILE}` lists the parts of synthesis `s:{SLUG}`: under each `## <part handle>`, numbered sentences as `<number> | <sentence> | <notes already linked after it, or ->`, then a `Sources:` line with the notes the part rests on. `{NOTES_FILE}` gives the file of each of those notes.

For every sentence that states a finding (a fact, a figure, a result, what a study or an author says), find the note among that part's `Sources:` that supports it, and answer one line:

<part handle> | <sentence number> | <the note's path exactly as on the Sources: line>

Rules:
- Read a note whole before you link a sentence to it; when a figure is at stake, the figure must be in that note, in the same setting (table, model, dataset).
- A sentence that rests on two notes: one line per note.
- A finding that no note of its part's `Sources:` supports: `<part handle> | <sentence number> | none`. Do not pick the nearest note instead: a wrong link is worse than none, because later steps trust it.
- A sentence that states no finding gets no line: reasoning (`Inference:`), a connecting sentence, a closing remark such as "Confidence: low.".
- A sentence that already has the note linked after it gets no line for that note.
- Only paths that stand on that part's `Sources:` line. Never a path from another part.
- When no sentence gets a line, answer the single word `nothing`.

Your whole answer is these lines, one per line, nothing before or after them: no heading, no code fence, no comment. Never dispatch subagents.

<example>
forgetting-curve | 3 | ../knowledge/psychology/recall-falls-fastest-in-the-first-day.md
forgetting-curve | 4 | ../knowledge/psychology/recall-falls-fastest-in-the-first-day.md
forgetting-curve | 4 | ../literature/psychology/1885-author-on-memory.md
forgetting-curve | 7 | none
spacing | 2 | ../knowledge/psychology/spaced-review-beat-massed-review.md
</example>
