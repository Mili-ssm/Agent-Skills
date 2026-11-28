# Memory plugin, stage 5b (consolidation: syntheses and unified notes) Implementation Plan

Status: done · merged in #117, 2026-11-17 · boxes left unticked during execution are not open work (checked 2026-11-19).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a subject that has gathered many notes gets one long document, a synthesis, that holds the extended knowledge (origins, reasons, when it applies and when not); notes on that subject become the short recall of one of its parts; and two or more notes that say the same are unified into one without breaking a link.

**Architecture:** a synthesis is a fourth kind of record in the store, one Markdown file under `syntheses/`, built from sections that are added or edited one at a time and never rewritten whole. A note says which section it summarizes (`part_of`). Search keeps ranking notes exactly as before and prints matching syntheses after them. Unifying notes marks the replaced ones and rewrites links with the code `rename` already has. Every change is logged for undo as memory curation is.

**Tech Stack:** Python 3.12, `uv`, `pyyaml`, `pytest`.

**Spec:** [../specs/2026-11-17-memory-plugin-design.md](../../specs/2026-11-17-memory-plugin-design.md), owner decisions D16 to D19; stage 5b of [2026-11-17-memory-plugin.md](../2026-11-17-memory-plugin.md).

## Why it is shaped this way

- Sections are edited one at a time because a model's rewrite of a whole context was observed to cut it from 18,282 tokens to 122 with a loss of accuracy (arXiv 2510.04618, checked in the full text).
- Every section cites the notes or sources it rests on, because a synthesis is third-hand (source, note, synthesis) and errors in stored text compound (arXiv 2505.16067).
- Search does not put a synthesis before its notes: in the owner's store, grouping studies under their synthesis lowered the rank of the expected note on single-fact questions (measured there on 2026-11-14).
- "First into the synthesis, then the note" applies where a synthesis of the subject exists; the owner wants the flow explored and it may not prove a good idea, so the rule can be switched off per call and its use is counted.

## Global Constraints

- Nothing outside `plugins/memory/` and `docs/` changes. Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (564 passed, 3 skipped before this stage).
- With no synthesis and no unified note in a store, the output of every existing command is byte-identical to before this stage (the parity run of stage 1 must still pass).
- All of this writes to the store, so every command here needs a store with its `mem-store.yaml` marker; the guards of stage 2 apply unchanged.
- A synthesis file: frontmatter `title`, `topics` (list of topic ids), `created`, `updated`; body: an `## Summary` section first, then one `## <heading>` section per part. A section's handle is its heading in lower case with hyphens. Each part ends with a line that starts `Sources:` and holds at least one relative Markdown link to a note in the store.
- No command rewrites a whole synthesis: `add` appends one section, `edit` replaces one section's text. Both log the file's previous text to `.curation-log` in `syntheses/`, and `mem restore s:<handle>` undoes them step by step.
- A note's new optional fields: `part_of` (`<synthesis handle>#<section handle>`) and `superseded_by` (a note handle). The store's `check` accepts them and verifies that their targets exist.
- Public repository: no home-directory path or private name. Commit after each task on `feat/memory-plugin`; do not push.

## Review Focus

1. A heading that repeats inside one synthesis, or that differs only in case: refused.
2. A section with no `Sources:` line, or whose links point outside the store or to a missing note: refused at writing and reported by `check`.
3. A note whose `part_of` names a section that was later renamed or removed: `check` reports it; `show` still prints the note.
4. Unifying a note into itself, into a note of another type, or one that other notes are already `superseded_by`: refused.
5. A synthesis of several thousand lines: `show s:<h> --outline --ranges` and reading one section stay as cheap as for a note.

---

### Task 1: The synthesis record

**Files:**
- Create: `plugins/memory/engine/syntheses.py`, `plugins/memory/engine/tests/test_syntheses.py`
- Modify: `plugins/memory/engine/mem.py`, `plugins/memory/engine/templates/` (a `synthesis.md` template), `mem init` (creates `syntheses/`)

**Interfaces:**
- `syntheses.py` imports nothing from `mem`. It holds: the `Synthesis` dataclass (`path`, `handle`, `title`, `topics`, `created`, `updated`, `sections: list[Section]`, `error`), `Section` (`handle`, `heading`, `text`, `sources: list[str]`, `line`), `load(folder) -> list[Synthesis]` (never raises), `section_handle(heading) -> str`, `add_section(path, heading, text, today)`, `edit_section(path, section_handle, text, today)`, `validate_section(text, store) -> list[str]` (the problems of Review Focus 2), and the log-and-restore functions, shared with `records.py` if that is cleaner (one implementation of the append-only log).
- Commands:
  - `mem synthesis new --title T --topics a,b --slug S [--summary-file PATH|-]`: creates `syntheses/<slug>.md` from the template with the summary; prints `s:<slug>\tsyntheses/<slug>.md`.
  - `mem synthesis add s:<h> --section "<heading>" --body-file PATH|-`: appends the section; the body must end with a valid `Sources:` line; prints `s:<h>#<section handle>\tadded`.
  - `mem synthesis edit s:<h>#<section handle> --body-file PATH|-`: replaces that section's text (the summary's handle is `summary`, and it needs no `Sources:` line); prints `…\tedited`.
  - `mem synthesis list [--topic T]`: one line per synthesis, `s:<h>\t<N> parts, updated <date>\t<title>`.
  - `mem show s:<h>` prints the whole file; `--outline --ranges` and `--section "<heading>"` work as they do for notes; `mem show s:<h>#<section handle>` prints one section.
  - `mem restore s:<h>` undoes the last `add` or `edit`.
- `mem search`: after the notes and before the page footer, when a synthesis matches: the line `-- syntheses (extended versions) --` and up to two lines `s:<h>#<section handle>\t<title>: <heading>`. A section matches by the rule already used for memories (`records.match_memories`' rule: at least half of the query's terms, stop words removed, occur in the section's heading and text); order by terms in the heading, then terms overall. Nothing is printed with `--offset` above 0, with a filter, or with `--detail paths`; `--scope notes` and `--scope memories` print no synthesis.
- `mem check` reports: a synthesis that cannot be parsed; a part without a valid `Sources:` line; a repeated section handle; a `topics` id that does not exist.
- `mem stats` adds `syntheses: N (P parts)` when N is above 0.

- [ ] **Step 1: Write the failing tests** for each behavior above and for Review Focus 1, 2 and 5, including: `add` then `restore` leaves the file byte-identical; `edit` changes one section and leaves every other byte of the file unchanged; search output with no synthesis in the store equals the output before this stage; with one, the note lines are unchanged and the synthesis lines follow them.
- [ ] **Step 2 to 4:** Run (fail), implement, run the whole suite.
- [ ] **Step 5:** Commit: `feat(memory): add syntheses, the extended documents behind notes`.

### Task 2: Notes that summarize a part, and unified notes

**Files:**
- Modify: `plugins/memory/engine/mem.py`; create `plugins/memory/engine/tests/test_consolidation.py`

**Interfaces:**
- The note schemas accept `part_of` and `superseded_by`; `check` verifies their targets.
- `mem new knowledge … --part-of s:<h>#<section>`: records the field. **Synthesis first:** when a synthesis lists one of the new note's topics and neither `--part-of` nor `--no-synthesis` is given, the command writes nothing, exits 3, and prints `mem: a synthesis covers this topic: s:<h> (<title>). Add what is new to it first (mem synthesis add or edit), then repeat with --part-of s:<h>#<section>; or repeat with --no-synthesis if it does not belong there.` Each `--no-synthesis` is counted in the usage log (`{"cmd": "new", "no_synthesis": true}`), so the rule's worth can be read later.
- `mem show <note>` prints, after the note's key facts line, `part of: s:<h>#<section> (extended version: mem show s:<h>#<section>)` when the field is set.
- `mem unify <keep> <other>... --body-file PATH|-`: all must be notes of the same type in the store. `<keep>`'s body becomes the given text (the unified version the agent wrote; it passes the same inline check as `mem new --body-file`), each `<other>` gets `superseded_by: <keep>`, and every link to an `<other>` in the store is rewritten to `<keep>` with the code `rename` uses. The previous text of every changed file goes to `.curation-log` at the store's root; `mem restore <note>` undoes one file at a time. Prints `<keep>\tunified from <n> notes, <k> links rewritten`.
- A note with `superseded_by` is left out of `search`, `find` and `related` unless `--superseded` is given, and `show` prints `superseded by: <keep>` under its header.
- `mem curate --notes`: two blocks, each only when it has items: `notes that say the same or the opposite? (decide: mem unify <keep> <other> --body-file …, or leave)` for pairs of knowledge notes that share a topic and whose claims contain each other at `records.STRONG` or more, with the `differ in:` line; and `topics with 8 notes or more and no synthesis (mem synthesis new)` with the topic id and the count.

- [ ] **Step 1: Write the failing tests**, including the stage plan's checks: after unifying three notes a search for words of any old claim returns the kept one, `check` passes and no link is broken; a source note linked from three knowledge notes still lists all three under `mem related`, and a knowledge note with two sources keeps both links after a `unify` (D18); the synthesis-first refusal, `--part-of` and `--no-synthesis`; search output is unchanged in a store with no superseded note.
- [ ] **Step 2 to 4:** Run (fail), implement, run the whole suite.
- [ ] **Step 5:** Commit: `feat(memory): notes point to their synthesis section, and notes can be unified`.

### Task 3: The skill

Written by the main conversation: a `memory-synthesis` skill (when a synthesis is worth writing; how to build one part at a time from notes and sources, each part with its origins, its reasons, when it applies and when not, and its `Sources:` line; how to add new knowledge to it before writing the note; never rewrite the whole document); the `memory` skill gains the reading recipe (a note first; its `part of:` line leads to the extended version) and the `memory-curation` skill the two note blocks. One trigger case for the new skill.

### Task 4: Measurements

- [ ] **Step 1:** Parity: the stage 1 run on the disposable clone. Expected: identical.
- [ ] **Step 2:** On a scratch store with about ten notes and three source notes on one subject, a headless session asked to write a synthesis of the subject: it uses `mem synthesis new` and one `add` per part, every part has sources, `check` passes. One run.
- [ ] **Step 3:** In that store, a session told something new on the subject and asked to keep it: it adds to the synthesis first and then writes the note with `--part-of`. Two runs; record how often `--no-synthesis` was used instead.
- [ ] **Step 4:** A question no single note answers ("when does this practice not apply, and why"): the session reaches the synthesis section and answers from it. A single-fact question: it answers from the note without opening the synthesis. One run each.
- [ ] **Step 5:** Record the figures; tick stage 5b.

## Amendments after the pre-mortem (2026-11-17)

These override the tasks above. Task 1 as first written is being implemented; items A to C change it.

### A. Synthesis first, in one call (the section is the source of truth)
- `mem synthesis add s:<h> --section "<heading>" --body-file F` gains the optional group `--note-slug S --note-claim "…" --note-body-file G --confidence C --level L`: with it, the command writes the section and a knowledge note that summarizes it, the note's topics taken from the synthesis and its `part_of` set, both or neither. This is the normal way to record new knowledge on a subject that has a synthesis.
- `part_of` is stored with a fingerprint of the section's text when the note was written (`part_of_hash`). `mem curate --notes` gains a block `notes older than their section (rewrite the note from the section: mem show s:<h>#<section>)`.
- A part's `Sources:` line may cite a note in the store, an `https` URL, or the word `experience` followed by a date: knowledge that comes from work has no note to cite yet.
- The refusal of `mem new knowledge` on a covered topic (exit 3) names the one-call form first. A topic is covered when a synthesis lists that exact topic id (no ancestors, no descendants); when several match, all are listed.

### B. Sections grow, they are not retyped
- `mem synthesis append s:<h>#<section> --body-file F` adds text at the end of a section, before its `Sources:` line, and may add links to that line. This is the default way to extend a part.
- `mem synthesis edit` refuses, unless `--shrink` is given, a text with fewer than 80% of the section's words or without one of its links: `mem: the new text drops <N> words and the links <…>; use --shrink if that is meant.`
- `mem show s:<h>` prints the outline with line ranges; `--all` prints the whole file. A section above 800 words makes `add`, `append` and `edit` print a note on stderr suggesting a split; nothing is refused.

### C. Search and overlap
- A section matches a query on its heading and its first paragraph only, never on its whole text or its `Sources:` line.
- `mem synthesis new` refuses a topic id that another synthesis already lists: `mem: s:<h> already covers the topic <id>; add a part to it.`

### D. Unifying notes without losing anything
- Links are rewritten with paths recomputed from each file's folder to the kept note's folder (a note may be in another topic folder), and `check` runs on the result before anything is kept; on a problem every file is put back.
- The unified body is refused, unless `--drop` is given, when it lacks a link target that any of the unified notes' bodies had: `mem: the unified text drops the links <…>; use --drop if that is meant.`
- The kept note takes the union of the topics and the lowest confidence of the unified notes.
- One `unify` is one undo: `mem restore <keep>` puts back every file it changed, and refuses when any of them changed since.
- `mem distinct <a> <b>` works for notes too (a `distinct_from` field), so a pair told apart leaves `curate --notes`.
- `mem rename` also rewrites `part_of` and `superseded_by` values that name the renamed note or synthesis.
- A superseded note stays in the store's README listings marked `(superseded)`, and is left out of the session index's count.

### E. How the owner's flow is judged
Read from the usage log two weeks after the plugin is installed:
- `--no-synthesis` on more than half of the `new knowledge` calls on covered topics, or a file under `syntheses/` changed outside `mem`: the synthesis-first rule is switched off and the result recorded.
- Fewer than one `show s:` for every ten searches that printed a synthesis line: syntheses leave the search output.
- Any lost link or stale-note report after a `unify` on real notes: `unify` is stopped and re-planned.

## Change of rule by the owner (2026-11-17, while this stage was being built)

Loose notes are written freely; joining a note to a synthesis is part of curation, not of writing. This replaces the synthesis-first refusal of Task 2 and of amendment A:

- `mem new knowledge` on a covered topic writes the note and prints one line on stderr saying which synthesis covers the topic and that a curation pass can attach it. There is no exit 3 and no `--no-synthesis`.
- `mem synthesis attach <note> s:<h>#<section>` records that an existing note is the recall of that part.
- `mem curate --notes` lists the notes on a covered topic that are not part of the synthesis yet, beside the notes older than their part, the pairs to unify and the topics with many notes and no synthesis.
- The one-call form (`mem synthesis add` with the note group) stays as an optional way.
- Amendment E's first criterion changes to: two weeks after installing, fewer than half of the notes on covered topics attached after a curation pass means the attach step is not being done and the flow is revisited.

## Second change of rule by the owner (2026-11-17): D21

- `mem search` returns knowledge notes and memories by default. `--deep` adds source notes (papers, documents), investigations and syntheses, printed after the notes under their own headers. With `--deep` and no memory or synthesis present, the note lines are those the original tool prints; without it they are the original's lines for knowledge notes only. The parity run compares `mem search --deep`.
- `mem remember` prints, when a pass is due after this write, one line on stderr: `mem: N new memories since the last curation pass: after the current task, hand a pass to the memory-curator subagent.`
- The `memory` skill covers three things: search, open, remember. Everything else is named as the curator's work.
- Open: whether the curator applies actions itself. Proposed: it applies what is mechanical and reversible (merging a near-copy, forgetting an expired finding, attaching a note to its part) and proposes what needs judgment (which of two opposites holds, what to promote to the global scope).

## Results

Measured on 2026-11-17; counts and pass or fail only. Agent trials are one run each with Sonnet unless a count is given.

| Item | Result |
|---|---|
| Code | Syntheses (new, add with an optional note, append, edit, attach, list, restore), `unify`, note `distinct`, `curate --notes` with four blocks, search of notes by default and `--deep`, the in-session curation reminder, secret refusal. Suite: 662 passed, 3 skipped |
| Parity | `mem search --deep` gives output identical to the original tool on 20 of 20 queries; the default search returns knowledge notes and memories only, by the owner's rule D21 |
| A store without its marker | `unify`, `synthesis new`, `synthesis attach` and `distinct` run from inside a real one changed nothing |
| An agent asked for a synthesis of a subject, on a disposable copy of about 1,100 notes | Loaded the `memory-synthesis` skill, wrote five parts each ending with its sources, about 2,200 words; `mem check` passed before and after |
| A single-fact question in that store | One search, answered from the note, opened nothing else |
| A question asking for reasons and limits | Answered from the notes (one search, one `show`); it did not use `--deep` or the synthesis. Under D21 that is the intended default; it also says a synthesis will be read little while the notes are enough |
| Trigger cases | `memory` 2 of 2, `memory-synthesis` 2 of 2; `memory-curation` 5 of 6 once its case accepts either path (loading the skill or dispatching the curator), the grader requiring an actual dispatch |
| Routing and recall trials after these changes | 9 of 9 and 8 of 8 |

Not measured: `unify` and `attach` done by an agent in a curation pass over notes; the one-call form; a second machine; real use. A review round then found, and a fix round closed: a rename that could not be undone and blocked a later undo; `unify` and `new` storing a secret-looking text; reference-style links invisible to `unify` and `rename`; a section edit that accepted a paragraph swapped for other text of the same length; a stale listing not restored byte for byte. Suite after the fixes: 678 passed, 3 skipped; `--deep` parity 20 of 20; the marker-less store unchanged. The fixes were confirmed by tests and these checks, not by a second review.
