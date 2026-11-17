---
name: memory-curation
description: Procedure for a curation pass over the memories kept with the `mem` command - deciding what to do with memories that say the same or the opposite, that expired, that were seen several times, or that were written again after being refuted - with one reversible command per decision. Use when the session start text says "Curation due", when the owner asks to review, clean up, deduplicate or tidy the memory, or when a search returns memories that contradict each other; load it before changing any memory so nothing still true is forgotten and no two opposite claims are merged.
---

# Memory curation

**Core rule:** a pass decides, one item at a time, and every decision can be undone (`mem restore m:<handle>`). Nothing is deleted: a memory leaves search by being marked. When you cannot tell, leave the item and say so; a wrong merge costs more than a duplicate.

Run a pass after the current task, not in the middle of it. It may be handed to the `memory-curator` subagent, which proposes actions and applies none; you apply the ones you agree with.

## The pass

1. `mem curate`: the queue. It prints nothing when there is nothing to decide.
2. For each item, read both memories whole when the claims alone do not settle it: `mem show m:<a> m:<b>`.
3. Apply one action per item (table below).
4. `mem curate --done`: records the pass, so the session start text stops announcing it.

| Block of the queue | What it means | Actions |
|---|---|---|
| same or opposite? | Two claims share most of their words. The tool cannot tell a copy from a contradiction or from two versions: read the `differ in:` line | The same thing said twice: `mem merge <keep> <drop>` (keep the clearer or newer one). Opposites: decide which is right and `mem refute <wrong> --because "<why>"`; if you cannot, leave both. Different things (two versions, two systems): `mem distinct <a> <b>` |
| written again after being refuted | A live memory matches one that was refuted earlier | Still wrong: `mem refute <live> --because "<why>"`. A different claim after all: `mem distinct <a> <b>` |
| expired | Past its `valid until` date | No longer true: `mem forget <h>`. Still true: write it again with `mem remember` and a new date, then `mem supersede <old> <new>` |
| seen 3 times or more | A candidate for a general lesson | Would hold in any project: `mem promote <h>` prints a draft; rewrite the claim in general terms with no name of a project, system, client or person, then run it. Only true here: `mem promote --no <h>` |
| not confirmed in 90 days | An old lesson, pitfall or finding nobody confirmed | Check it against the project if that is cheap. Still true: `mem confirm <h>`. False: `mem refute <h> --because "<why>"`. Cannot tell: leave it |

## Rules

- `mem merge` refuses two claims that differ in a negation or a number, because those are usually opposites or versions. Use `--force` only after reading both memories whole.
- Never merge or supersede across scopes: a project memory and a global one stay two records.
- `mem forget` is for what stopped being true or useful. For something that was wrong from the start, `mem refute` with the reason: the reason is what stops it being written again.
- A decision or a constraint does not go stale by age: the queue never lists them as unconfirmed, and you do not forget one because it is old.
- Undo: `mem restore m:<handle>` puts a memory back as it was before the last action on it.

## Report

End with a short table: item, action taken (or "left"), one line of reason; then how many memories are live now.
