---
name: memory-synthesis
description: Writes and maintains a synthesis with the `mem` command - one long, indexed document that gathers what many notes and sources say on a subject (origins, reasons, when it applies and when not), from which short notes are drawn as recalls of its parts. Use when the owner asks for a compendium, an overview, a guide or "everything we know" on a subject, when a subject has gathered many notes, when `mem curate --notes` lists a topic without a synthesis, or or when a curation pass lists notes to attach to an existing one; load it before writing so the document grows one cited part at a time and is never rewritten whole.
---

# Synthesis

**Core rule:** a synthesis is the long-term version, a note is the quick recall of one of its parts. The synthesis holds origins, reasons, and when a thing applies and when it does not; the note holds the one sentence someone needs while working. Notes are written freely as they come; building a synthesis, and joining a note to one, is curation work done afterwards.

A synthesis is third-hand knowledge (source, note, synthesis): every part says what it rests on, and nothing in it is firmer than its sources.

## Reading

- A search prints notes first; a line under `-- syntheses (extended versions) --` names a part that goes deeper.
- A note that belongs to a synthesis shows `part of: s:<handle>#<section>`: open that part with `mem show s:<handle>#<section>` when the note is not enough.
- `mem show s:<handle>` prints the outline with line ranges, not the whole document: read the one part you need.

## Writing a new synthesis

Worth it when a subject has many notes that a reader would have to assemble (the curation queue says so at eight), or when the owner asks. Not for a subject with two or three notes.

1. Gather: `mem find --topic <id>` and `mem search "<subject>" --links`; read the conclusions with `mem show <handle>... --section conclusion`, and a source's passages only where a part needs a figure.
2. `mem synthesis new --title "…" --topics <id> --slug <slug> --summary-file -`: the summary is a few lines saying what the document covers and for whom.
3. One part per call: `mem synthesis add s:<slug> --section "<heading>" --body-file -`. A part answers, in this order: what the practice or finding is; where it comes from; why it holds; when it applies; when it does not; what remains disputed. It ends with a line `Sources:` linking the notes it rests on (or a URL, or `experience <date>` for what comes from work).
4. Keep a part under about 800 words; split a longer one.
5. `mem check` must pass before you stop.

Write from the notes and sources you read in this session, not from memory: a part with nothing to cite is a part to leave out.

## Joining notes to a synthesis (curation)

`mem curate --notes` lists the notes on a subject that has a synthesis and are not part of it yet. For each: add what the note says to the right part (`append`, or `add` for a new part, with the note among its sources), then `mem synthesis attach <note> s:<slug>#<section>`. A note that does not belong to the subject is left as it is.

When you are writing new knowledge and its part at the same time, one call writes both:

```
mem synthesis add s:<slug> --section "<heading>" --body-file part.md \
    --note-slug <claim-as-a-file-name> --note-claim "<one sentence>" --note-body-file note.md \
    --confidence medium --level intermediate
```

- New material for an existing part: `mem synthesis append s:<slug>#<section> --body-file -`. It adds to the end of the part; it does not retype it.
- A correction: `mem synthesis edit s:<slug>#<section> --body-file -`. It refuses a text that loses much of the part or one of its links; `--shrink` only when the loss is meant.
- `mem new knowledge` on a covered topic writes the note and names the synthesis that covers it; attaching it is for the next curation pass.
- Never edit a file under `syntheses/` by hand, and never replace a whole document: use the commands, which keep an undo (`mem restore s:<slug>`).

## Keeping notes and parts in step

`mem curate --notes` lists notes that are older than their part. Rewrite such a note from the part (`mem show s:<slug>#<section>`), keeping it to the short recall. When a note and its part disagree, the part and its sources decide.
