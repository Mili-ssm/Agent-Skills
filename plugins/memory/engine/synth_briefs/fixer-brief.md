# Brief: apply a fact-check report to one synthesis

Synthesis `s:{SLUG}` in the owner's note store (the `mem` command is on PATH). Read the fact-check report `{REPORT_FILE}` and fix every claim line it lists (the lines before the first `REF:` line). Ignore its `REF:`, `PARTS:` and `COUNTS:` lines: code applies the `REF:` lines.

## How

1. `mem show s:{SLUG}` lists the parts with their handles; read a part with `mem show s:{SLUG}#<handle>`.
2. For each part with a listed claim, copy the part from `mem show s:{SLUG}#<handle> --stored`, change only the sentences the report lists and leave every other character as it is: a sentence you change without being asked is a new claim nobody checked. Apply it with `mem synthesis edit s:{SLUG}#<handle> --body-file -` (the text on stdin with a heredoc). `edit` replaces the whole part, so the copy must hold every sentence the report does not fault. `edit` also refuses a text that drops a sentence, and replacing or deleting a listed sentence drops it: add `--shrink`. The guard does not check that every other sentence stayed, so you must.
3. Use the report's replacement sentence verbatim; add no figure, comparison or claim of your own. A claim with no replacement: delete the sentence. Do not open the cited notes.
4. A sentence may be followed by links to the notes it rests on: `Old sentence. [a](../knowledge/x/a.md)`. The replacement in the report has no links, so replace only the sentence and leave its links where they are: `Replacement sentence. [a](../knowledge/x/a.md)`. When you delete a sentence, delete the links that follow it too. Every other link stays exactly as it is: `edit` refuses a text that drops one.
5. Keep the part's closing `Sources:` line unchanged; remove a link from it only when no sentence of the part still carries that link and nothing in the part rests on that note.
6. `mem check` must exit 0 before you stop. If an `edit` is refused, read the error and fix the text; never edit files by hand.

## Scope and limits

Write only through `mem synthesis edit` for `s:{SLUG}`. Do not change notes, other syntheses or any file under the store by hand; do not run `attach`, `unify`, `rename`, `import`, `forget` or another write. Helper files, if any, go in `{WORK_DIR}` and start with `{SLUG}-fix-`; prefer stdin. Never dispatch subagents.

## Report (under 6 lines)

Parts edited (handles); sentences changed (first 8 words each); claims deleted; `mem check` result. Stop after `mem check` passes: the caller runs one scoped check.
