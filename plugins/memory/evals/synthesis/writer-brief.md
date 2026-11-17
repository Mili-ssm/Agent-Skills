# Brief: write one synthesis in the owner's memory store

You write one synthesis for one topic of the owner's note store, with the `mem` command (on PATH; run it from any folder). The store is private to the owner; the work is curation the owner asked for.

## Goal and acceptance

A synthesis for topic `{TOPIC}`: one long, indexed document that gathers what that topic's notes say (origins, reasons, when a thing applies and when not), so a reader gets the whole subject without assembling the notes. Done when:
- `mem synthesis list` shows it, with a summary and parts covering the topic's main subjects;
- every part ends with a `Sources:` line linking the notes it rests on, and says nothing those notes do not support (no outside knowledge, no figures you did not read in a note or its source passage);
- `mem check` exits 0.

## Method

Read first, whole: `{SKILL_FILE}`. Follow its "Writing a new synthesis" steps with these specifics:
1. `mem find --topic {TOPIC}` lists the notes (one line per note with its claim). Read the notes' conclusions in batches with `mem show <path>... --section conclusion` (or the whole note when the conclusion is not enough). Literature notes are sources; knowledge notes are findings.
2. Group the notes into parts by subject (typically 4 to 10 parts; a part under about 800 words; split a longer one). A note may support more than one part; a note that fits no part is left out and listed in your report.
3. `mem synthesis new --title "…" --topics {TOPIC} --slug {SLUG} --summary-file -` (summary: a few lines on what the document covers and for whom), then one `mem synthesis add s:{SLUG} --section "<heading>" --body-file -` per part, the text on stdin with a heredoc. Each part answers in order: what the practice or finding is; where it comes from; why it holds; when it applies; when it does not; what remains disputed. Keep each note's confidence visible where it matters (a `low` note is a hypothesis). Ending line: `Sources:` followed by Markdown links to the notes, written as paths relative to the synthesis file (the synthesis lives in `syntheses/`, so a note is `../knowledge/<domain>/<file>.md`); if a part is refused, read the error and fix the text, never edit files by hand.
4. Do NOT run `mem synthesis attach`.
5. `mem check` must exit 0 before you stop.

## Accuracy rules (a fact-check of a first synthesis found 9 of ~75 claims wrong, all of these kinds)

- Every sentence of your own reasoning starts with `Inference:`. "Holds by construction", "should not replace", "suits a stream of turns" are inferences.
- A figure keeps its exact origin: which table, which model or setting, which dataset. Never place two figures in one comparison unless the note compares them in the same setting.
- "Reported less often" is not "smaller"; "not explained" is not "explained by X"; "excluded from the comparison" is not "ahead".
- Before writing "no note measures X" or "nothing tests Y", search the topic's notes for it; a note's own tests of defences, baselines or exceptions count.
- A note's own `Inference:` stays an inference in the synthesis; an author's argument stays "the authors argue".
- When two notes disagree, say so and give both, with their sources; do not pick one silently.

A fact-checker will compare every part with its cited notes after you finish, and its fixes will then be applied with `mem synthesis edit`.

## Scope and limits

- Write only through `mem synthesis new|add|append|edit` for `s:{SLUG}`. Do not change notes, memories, other syntheses or any file under the store by hand. Do not run `mem unify`, `rename`, `import`, `forget` or any other write.
- English, plain and dense, as the notes are. No names of clients, companies, private systems or people beyond cited authors.
- Never dispatch subagents.
- Any helper file you create goes in `{WORK_DIR}` and starts with `{SLUG}-`.

## Stop rule

If the topic's notes do not support a coherent document (too disparate, or mostly duplicates), stop before `synthesis new` and say why. If a command fails in a way its message does not explain, stop and report it.

## Report (under 15 lines)

Slug; number of parts and their headings; notes used of notes in the topic; notes left out and why (one line each, at most 5, then a count); `mem check` result; doubts.
