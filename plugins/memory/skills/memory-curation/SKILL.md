---
name: memory-curation
description: Reviews and tidies the memories and notes kept with the `mem` command - merges or unifies records that say the same, joins loose notes to their synthesis, settles ones that contradict each other, retires expired ones and promotes ones seen several times - with one reversible command per decision. Use when the session start text says "Curation due", when the owner asks to review, clean up, tidy, prune or deduplicate the memory, or when a search returns memories that contradict each other; load it before changing any memory so nothing still true is forgotten and no two opposite claims are merged.
---

# Memory curation

**Core rule:** a pass decides, one item at a time, and every decision can be undone (`mem restore m:<handle>`). Nothing is deleted: a memory leaves search by being marked. When you cannot tell, leave the item and say so; a wrong merge costs more than a duplicate.

Run a pass after the current task, not in the middle of it. It may be handed to the `memory-curator` subagent, which proposes actions and applies none; you apply the ones you agree with. Prompt it with "apply" and it also carries out the safe subset through `mem curate apply --safe` (merges of equal claims, attaches the part's `Sources:` line backs; the rest stays a proposal), reporting counts and what it left: you still decide every other row.

## The pass

1. `mem curate`: the queue. It prints nothing when there is nothing to decide.
2. For each item, read both memories whole when the claims alone do not settle it: `mem show m:<a> m:<b>`.
3. Apply one action per item (table below).
4. `mem curate --done`: records the pass, so the session start text stops announcing it; in a store with git history it also commits the pass and trims curation-log entries older than 30 days.

| Block of the queue | What it means | Actions |
|---|---|---|
| same or opposite? | Two claims share most of their words. The tool cannot tell a copy from a contradiction or from two versions: read the `differ in:` line | The same thing said twice: `mem merge <keep> <drop>` (keep the clearer or newer one). Opposites: decide which is right and `mem refute <wrong> --because "<why>"`; if you cannot, leave both. Different things (two versions, two systems): `mem distinct <a> <b>` |
| written again after being refuted | A live memory matches one that was refuted earlier | Still wrong: `mem refute <live> --because "<why>"`. A different claim after all: `mem distinct <a> <b>` |
| expired | Past its `valid until` date | No longer true: `mem forget <h>`. Still true: `mem confirm <h> --until <new date>` |
| seen 3 times or more | A candidate for a general lesson | Would hold in any project: `mem promote <h>` prints a draft; rewrite the claim in general terms with no name of a project, system, client or person, run it, then `mem promote --done <h>`. Only true here: `mem promote --no <h>` |
| not confirmed in 90 days | An old lesson, pitfall or finding nobody confirmed | Check it against the project if that is cheap. Still true: `mem confirm <h>`. False: `mem refute <h> --because "<why>"`. Cannot tell: leave it |
| general lesson, out of quarantine, awaiting triage | A lesson seen in two projects, released and not yet decided | Report it and leave it: a main session or the owner runs `mem triage accept <h>` or `mem triage reject <h>`, or rewords it with `mem memory edit <h> --global` first |
| balance got worse after loading | A loaded lesson has a failed case after its short form loaded ([design](../../../../docs/superpowers/specs/2026-11-22-memory-case-log-design.md)); it keeps loading meanwhile. `mem show <h>` prints each version with its tally and earlier texts | Report it and propose one of four answers: reword it or make it firmer, or go back to an earlier text, both with `mem memory edit <h> --short`; drop it with `mem forget <h>`; keep the wording with `mem triage accept <h>` (`--project-scope` for a project lesson). The owner decides: you never reword or accept on your own |
| short forms nobody read: N | A model's short form (written by the background pass or by `--short`) loads as a rule before anyone read it | List them with `mem rules --unread` and propose: still faithful, reword, `--no-load`, or `mem forget`/`mem refute` if the lesson is false. Never run `mem rules --read` and never pass `--user-read`: reading is the owner's |
| in quarantine: n general lessons | Captured in one project so far; no reader sees them | Nothing to do: they wait for a second project |

In a curation pass never run `mem confirm` on a record marked `from transcript, unconfirmed`: a pass has no new session to add, and only another session showing the lesson confirms it (the capture adds that session itself).

The background curator never runs `mem triage` (`accept`, `reject` or `hold`; the automatic fill, a different process, is what holds a lesson): a main session or the owner accepts (`mem triage accept <h>`) or rejects (`mem triage reject <h>`) a general lesson, which waits there when it is `strong` or when the automatic fill refused its short form twice (the reason is shown), and turning a lesson into a rule (an agent definition, a skill, a context file) needs the owner.

## Notes

`mem curate --notes` is the same pass for notes in the store. Notes are written loose; this is where they are joined up.

| Block of the queue | Actions |
|---|---|
| notes on a topic that has a synthesis, not yet part of it | Add what the note says to the right part (`mem synthesis append` or `add`, the note among its sources), then `mem synthesis attach <note> s:<h>#<section>`. Not about that subject: leave it |
| notes older than their section | Rewrite the note from its part (`mem show s:<h>#<section>`), keeping it short, with `mem note edit <note> --section <heading> --body-file -` |
| notes that say the same or the opposite? | The same: write one text that keeps every source link and every "does not apply when" of both, then `mem unify <keep> <other> --body-file -`. Opposites or different things: `mem distinct <a> <b>`, or leave and say so |
| topics with 8 notes or more and no synthesis | Worth a long document? Load the `memory-synthesis` skill. For many topics, `mem-synthesize` writes them quietly (launch it in the background, it prints one table at the end); for one, the `memory-synthesizer` subagent. Not worth it: leave |

`mem unify` refuses a text that drops a link the notes had; the kept note takes the lowest confidence of the ones it replaces.

## Project syntheses

`mem curate` also lists project synthesis parts that are possibly stale, and asks for a first synthesis when a project has 5 or more memories and none. A part is a section of `.memory/syntheses/<name>.md` stamped with the commit it was written at; `mem project-synthesis add|confirm|list` and `mem show p:<name>` handle them.

- Kinds to names: `state` to `pending` or `plans`; `decision` and `constraint` to `conventions` or `organization`. `pitfall` and `lesson` stay memories unless they describe how the project is organized.
- Read the code a part will describe before writing it, because a part written from memory repeats what may already be wrong.
- Name folders in `--paths`, not many files: a folder survives renames and keeps the stamp meaningful.
- Cite memories in the body as `m:<handle>`; never list files or line numbers, since they go stale on the next edit.
- Possibly stale part: check its files, then `add` again with the corrected text, or `confirm` when it still holds.
- Unreadable part file (`-- project syntheses: unreadable --`): open it and fix the reason shown, or move it out of `.memory/syntheses/`; curation skips it until then.
- Write or confirm a part after committing the changes it describes, because the stamp is the commit (`add` and `confirm` print a note when covered files are uncommitted).

## Rules

- `mem merge` refuses two claims that differ in a negation, a number or version, or a listed pair of opposites (works/fails, enable/disable, before/after…), because those are usually contradictions or versions. It cannot catch opposites said in other words ("is slow" against "is fast"): read the `differ in:` line yourself before every merge, and use `--force` only after reading both memories whole.
- Never merge or supersede across scopes: a project memory and a global one stay two records.
- `mem forget` is for what stopped being true or useful. For something that was wrong from the start, `mem refute` with the reason: the reason is what stops it being written again.
- A decision or a constraint does not go stale by age: the queue never lists them as unconfirmed, and you do not forget one because it is old.
- A memory or note that is wrong in a detail, not as a whole: `mem memory edit m:<h> --claim "…"` or `mem note edit <note> --claim "…"`. A retired memory is restored before it is edited.
- A loaded rule (a line of the session start text, see `mem rules`) that is too strong, too weak or out of date: reword it in one command, `mem memory edit <h> --claim "…" --short "…"` (with `--global` for a global lesson), because a new claim alone removes the short form and the rule stops loading. The short form has at most 120 characters, keeps the claim's hedge and carries no standing (code adds it); code checks the text and it stays marked unread. Prefer the mildest action that fits: reword; then `--index-only` for a lesson that is true but rarely applies; then `--no-load` for one that does harm. `mem forget` or `mem refute` is for a lesson that is false. A lesson of weight `strong`, or a change you are unsure about, goes to the user first.
- Undo: `mem restore m:<handle>` puts a memory back as it was before the last action on it; run it again to go back one more step.

## Report

End with counts per action and one line for each item left. If `memory-curator` ran, name only where you departed from its table; do not repeat the table.
