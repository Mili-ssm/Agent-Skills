# Brief: write one synthesis in the owner's memory store

You write one synthesis for one topic of the owner's note store, with the `mem` command (on PATH; run it from any folder). The store is private to the owner; the work is curation the owner asked for.

## Goal and acceptance

A synthesis for topic `{TOPIC}`: one long, indexed document that gathers what that topic's notes say (origins, reasons, when a thing applies and when not), so a reader gets the whole subject without assembling the notes. Done when:
- `mem synthesis list` shows it, with a summary and parts covering the topic's main subjects;
- every part ends with a `Sources:` line linking the notes it rests on, and says nothing those notes do not support (no outside knowledge, no figures you did not read in a note or its source passage);
- `mem check` exits 0.

Stop rule: reply `STOP: <reason>` and write nothing when `mem find --topic {TOPIC}` lists fewer than 5 notes, or when, after reading the conclusions, you cannot name 4 parts that each rest on 2 notes. A command that fails with an error you cannot act on: reply `STOP: <command and message>`.

## Method

Read `{SKILL_FILE}`, section "Writing a new synthesis", and follow it with these specifics:
1. `mem find --topic {TOPIC}` lists the notes. Read the conclusions in batches with `mem show <path>... --section conclusion` (the whole note when a figure is at stake). Literature notes are sources; knowledge notes are findings.
2. 4 to 10 parts. A note may support more than one part; a note that fits no part is left out and listed in your report.
3. `--slug {SLUG}`, `--topics {TOPIC}`. If a part is refused, read the error and fix the text, never edit files by hand. Do NOT run `mem synthesis attach`.

## Accuracy rules

The "Accuracy" section of {SKILL_FILE} applies to every part. A fact-checker compares every part with its cited notes after you finish, and its fixes are applied with mem synthesis edit.

## Scope and limits

- Write only through `mem synthesis new|add|append|edit` for `s:{SLUG}`. Do not change notes, memories, other syntheses or any file under the store by hand. Do not run `mem unify`, `rename`, `import`, `forget` or any other write.
- English, plain and dense, as the notes are. No names of clients, companies, private systems or people beyond cited authors.
- Never dispatch subagents.
- Any helper file you create goes in `{WORK_DIR}` and starts with `{SLUG}-`.

## Report (under 15 lines)

Slug; number of parts and their headings; notes used of notes in the topic; notes left out and why (one line each, at most 5, then a count); `mem check` result; doubts.
