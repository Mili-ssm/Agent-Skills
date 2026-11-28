# Seamless stage 4 · Split a synthesis

**Status** — Owner accepted the candidate rule and automatic application after a successful trial on 2026-11-28. Implementation follows the [approved plan](../plans/2026-11-28-memory-seamless-stage-4.md).

## Outcome and scope

Keep a synthesis's general coverage in place and move detailed coverage of a subtopic to a linked child synthesis. A split preserves references and figures, routes affected notes to the right part, and has one undo operation. Stage 4 proves the split on a store copy. Scheduling, budget and failure reporting in `mem-auto` belong to [stage 5](../plans/2026-11-17-memory-seamless.md#stage-5-joining-mem-auto).

| Requirement | Kind | Check |
|---|---|---|
| Propose a candidate when at least five distinct, non-superseded notes attached to the same part explicitly name the same strict descendant of a declared synthesis topic | Technical, owner-approved trial rule | Four notes yield no candidate. Five yield one. Repeated references to a note and topics outside that ancestry contribute zero. |
| Keep the general content and a child pointer in the parent, with a backlink from the child | Functional, required | Resolve both links and check the retained parent part after application. |
| Preserve all original note references and numeric figures across the two parts. Move each selected note's attachment to the child and leave claims unchanged | Functional, required | Compare the original with the union of the resulting parts. Check every affected attachment and fingerprint, then run `mem check`. |
| Undo the split together and refuse stale or conflicting inputs | Functional, required | Restore prior files byte for byte, remove a child created by the split, and preserve later edits when undo refuses. |
| Apply automatically after the copied-store trial passes | Functional, owner-approved | Rehearse the same apply path on a copy first. Stage 5 schedules it under its own verification. |

## Approaches considered

| Approach | Trade-off |
|---|---|
| Three notes in a strict descendant | Three candidates in the 2026-11-28 survey, with more parts to review. |
| Five notes in a strict descendant | **Selected.** One candidate in that survey gives the first trial a focused case. |
| Five notes in any non-primary topic | Seven candidates, including overlap between topics that have no parent–child relationship. |

Manual confirmation would give the owner a veto on each split. The owner chose automatic application after the trial and asked for candidate proposals from the detector. The trial preview supplies evidence for that gate.

## Preview, validation and application

1. Read attachments, declared synthesis topics and topic ancestry through the existing engine. Exclude topics already declared by the parent. List candidate part, topic and note count in a new `mem curate --notes` block. Verify that the existing `mem-auto` parser still reads the separate topics-without-synthesis block. Keep conflicting candidates visible in the preview, and refuse automatic application if their affected notes overlap and the destination is ambiguous.
2. Preview the original part, retained parent text, destination part and attachment moves. Keep original text for units that can move intact. For a mixed part, let the synthesis worker propose content on a copy through a file. Python validates the plan and owns every write.
3. Resolve note references against their source paths before comparison. Check original numeric figures in the content, with Markdown reference markers excluded. Validate both resulting parts, term guards, path collisions, and expected input digests. A pre-existing child can receive a new part only when the destination is unambiguous. Existing parts may not be overwritten.
4. Publish parent, child and attachment edits as one recoverable group. The existing synthesis write and restore helpers handle files with prior contents. Extend that contract to represent an absent child explicitly so rollback and undo can remove it. Target undo by the split's group identifier. Check versions before recovery or undo, including unrelated later edits in a shared child file. Exercise a write failure after the first replacement and an interrupted process on a copy.

## Trial and release gate

Use a seeded strict-descendant case with at least five attached notes and a mixed parent part. Exercise both a new child and an existing destination, plus an invalid reference, a missing figure, a conflicting destination, an interrupted write and a later edit that blocks undo. Then preview the candidate from a copy of the local store. Inspect the retained and moved text before grading conservation and attachment routing. Record exact counts, changed paths by role, `mem check` and byte-for-byte undo excluding logs. The trial fails if a reference or figure is lost, any note is routed incorrectly, or recovery or undo leaves a partial split. Keep the live store out of the trial.
