# Brief: apply a fact-check report to one synthesis

Synthesis `s:{SLUG}` in the owner's note store (the `mem` command is on PATH). Read the fact-check report `{REPORT_FILE}` and fix every claim it lists as not supported. Read `{SKILL_FILE}` first for the rules of editing a synthesis.

## How

1. `mem show s:{SLUG}` lists the parts with their handles; read a part with `mem show s:{SLUG}#<handle>`.
2. For each part with a listed claim, write the part's whole corrected text and apply it with `mem synthesis edit s:{SLUG}#<handle> --body-file -` (the text on stdin with a heredoc). `edit` replaces the whole part, so keep every sentence the report does not fault. Add `--shrink` only when the fix legitimately leaves fewer words or links than before.
3. Use the report's replacement sentence when it is right; check it against the cited note when in doubt. A sentence of your own reasoning starts with `Inference:`. If a claim cannot be fixed from the cited notes, delete the claim.
4. Keep the part's closing `Sources:` line with its links, unless a link is no longer supported by anything in the part.
5. `mem check` must exit 0 before you stop. If an `edit` is refused, read the error and fix the text; never edit files by hand.

## Scope and limits

Write only through `mem synthesis edit` for `s:{SLUG}`. Do not change notes, other syntheses or any file under the store by hand; do not run `attach`, `unify`, `rename`, `import`, `forget` or another write. Helper files go in `{WORK_DIR}`. Never dispatch subagents.

## Report (under 6 lines)

Parts edited; claims fixed; claims left and why; `mem check` result.
