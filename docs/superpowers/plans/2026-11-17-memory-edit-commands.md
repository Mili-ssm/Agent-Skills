# Commands to edit notes, memories and syntheses: plan

Status: done · merged in #121 · boxes left unticked during execution are not open work (checked 2026-11-19).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agents change every record through `mem`, never by editing files: a command exists for each change that today needs a hand edit.

**Architecture:** New subcommands in `plugins/memory/engine/mem.py`, reusing what exists: `syntheses._guard_shrink` (refuses losing more than 20% of the words, a sentence or a link unless `--shrink`), `_refuse_secret`, `_check_terms` (forbidden terms, global scope only), the persistent undo logs (`_log_note` for notes, `records.log_before` for memories and for a synthesis file, as `synthesis edit` does; a group entry in the store's root `.curation-log`, as `unify` and `rename` write and `_restore_group` reads, for a command that changes several files) so `mem restore` undoes every new command. `syntheses.snapshot` is only the in-memory rollback when a write fails half way; it is not an undo log.

**Tech Stack:** Python 3.12+, pyyaml, pytest.

**Status:** done 2026-11-17 (branch `feat/memory-edit-commands`, not merged).

## Decisions already taken (owner, 2026-11-17)

| Decision | Reason |
| --- | --- |
| Agents change records only through commands; syntheses included, no exception | Commands carry the guards (shrink, secrets, terms), the undo log and link integrity that a hand edit skips, and cost fewer tokens |
| An edit has the same guard as `synthesis edit`: refused when it drops over 20% of the words, a sentence or a link, unless `--shrink`; the text before goes to the undo log; secrets refused; forbidden terms checked where the scope is global | One rule for every edit |
| Nothing is deleted: removing is marking or moving to the undo log, and `mem restore` brings it back | Every curation action stays reversible |

## Global Constraints

- Long text arrives by `--body-file F` or `--body-file -` (stdin), as `synthesis add` does; never only as an argument.
- Every new write: secret check (`_refuse_secret`, exit 4, nothing written); forbidden-terms check (`_check_terms`) for notes and global memories, never for project memories; undo entry written before the file changes; `mem restore <handle>` puts the previous bytes back.
- A note's `updated` and a synthesis's `updated` are bumped by a write; a memory's fields follow `records.update`.
- Writes to the store need a writable store (`records.store_is_writable`); project memories need none.
- Output: one line per changed record, `<handle>\t<what changed>`; errors on stderr with exit 2.
- Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (745 passed, 4 skipped on `main`); `python3 scripts/validate.py` before every commit. Public repository: no home paths or private names.
- Single-sentence fields (a note's or a memory's `claim`): the guard's sentence rule does not apply, because changing the one sentence is the point; the word-ratio and link rules do. (Ruling 2026-11-17 after the pre-mortem: otherwise every claim correction needs `--shrink` and agents learn to pass it always.)
- Every write goes through a temporary file and `os.replace`, and is refused (exit 2) when the file's bytes changed since the command read them (an edit racing `unify` or `rename` must not write an old path back).
- A change to a note's `claim` or `topics`, and its restore, rebuilds the README index blocks (`apply_index`), so rule 9 of `mem check` holds.
- Out of scope: renaming a memory, retiring a whole synthesis, a real delete (decided: only marking).

---

### Task 1: `mem note edit`

**Files:** Modify `plugins/memory/engine/mem.py`; Test `plugins/memory/engine/tests/test_note_edit.py`

| Command | Effect |
| --- | --- |
| `mem note edit <note> --section "<heading>" --body-file F [--shrink]` | Replaces the text under that `## ` heading of the note; every other byte stays |
| `mem note edit <note> --claim "<text>"` | Replaces the frontmatter `claim` |
| `mem note edit <note> --topics a,b,c` | Replaces the frontmatter topics; each id must exist in the store's topic tree and belong to the note's domain folder (else `rule_domain` of `mem check` fails) |

- `<note>` resolves like `mem show` (path or handle). Options combine in one call; one undo entry per call.
- Refused (exit 2): an unknown section, a body with a `## ` heading, an empty result, an unknown topic id.
- Guard applies to `--section` and `--claim` text.

- [x] **Step 1: Write the failing tests** — one per table row; guard refusal without `--shrink` and acceptance with it; a one-word claim correction accepted without `--shrink`; secret refusal writes nothing; forbidden term refused; a topic of another domain refused; `mem restore` returns the exact previous bytes and `mem check` passes after each edit and after each restore (README index included); a note `part of` a synthesis keeps its `part_of`; a write refused when the file changed since it was read.
- [x] **Step 2: Run them and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Whole suite and `scripts/validate.py` pass.**
- [x] **Step 5: Commit** `feat(memory): mem note edit for a section, the claim or the topics`.

### Task 2: `mem memory edit`

**Files:** Modify `plugins/memory/engine/mem.py`; Test `plugins/memory/engine/tests/test_memory_edit.py`

`mem memory edit m:<handle> [--claim "<text>"] [--context "<text>"] [--body-file F] [--shrink] [--global]`: changes the given fields; the handle stays (renaming is out of scope); `records.log_before(..., "edit")` first; guard on `--claim` and the body; forbidden terms for a global memory only; secrets always.

- [x] **Step 1: Write the failing tests** — each field; guard; secret; a global memory with a forbidden term refused, a project one accepted; `mem restore m:<h>` undoes; `--global` picks the global memory when both scopes hold the handle (as `supersede` does).
- [x] **Step 2: Run them and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Whole suite and `scripts/validate.py` pass.**
- [x] **Step 5: Commit** `feat(memory): mem memory edit for a memory's claim, context or body`.

### Task 3: Synthesis structure commands

**Files:** Modify `plugins/memory/engine/syntheses.py`, `plugins/memory/engine/mem.py`; Test `plugins/memory/engine/tests/test_synthesis_structure.py`

| Command | Effect |
| --- | --- |
| `mem synthesis rename s:<h>#<section> "<new heading>"` | Renames the heading; every note `part of` that section gets the new handle in `part_of`; `part_of_hash` is kept as it was (the heading is not part of the hash, and refreshing it would hide notes already stale from `curate --notes`) |
| `mem synthesis remove s:<h>#<section>` | Takes the section out of the file; notes `part of` it lose `part_of` and are listed; the summary cannot be removed |
| `mem synthesis detach <note>` | Removes a note's `part_of` (logged with `_log_note`) |
| `mem synthesis topics s:<h> a,b,c` | Replaces the synthesis's topics; each id must exist in the topic tree |

- `rename` and `remove` change several files: they write one group entry (the synthesis and every note they touch) to the store's root log, and `mem restore s:<h>` restores the whole group, or nothing when a member changed since (the `_restore_group` rule); `topics` logs the synthesis file alone with `records.log_before`; `mem restore <note>` undoes `detach`. A rename to a heading whose handle exists is refused.

- [x] **Step 1: Write the failing tests** — one per row; `mem restore` after each returns the exact previous bytes of every file it touched, and `mem check` passes after each command and after each restore; a restore after `rename` does not undo an earlier `edit` of the same synthesis; `part_of_hash` unchanged by `rename`; `mem curate --notes` stops listing a topic once a synthesis names it.
- [x] **Step 2: Run them and see them fail.**
- [x] **Step 3: Implement.**
- [x] **Step 4: Whole suite and `scripts/validate.py` pass.**
- [x] **Step 5: Commit** `feat(memory): rename, remove and detach synthesis sections, set a synthesis's topics`.

### Task 4: Tell the agents

**Files:** Modify `plugins/memory/skills/memory/SKILL.md`, `plugins/memory/skills/memory-curation/SKILL.md`, `plugins/memory/skills/memory-synthesis/SKILL.md`, `plugins/memory/README.md`

- The `memory` skill states once, with its reason, that records change only through `mem` commands, never by editing files, and names `note edit` and `memory edit`. The curation and synthesis skills name the new commands where their method needs them (correct a note, fix a memory, rename or remove a part, detach a note, set topics). Bodies only: no `description:` changes (they would need an eval). README: the command table gains the new rows.

- [x] **Step 1: Edit the four files.**
- [x] **Step 2: `python3 scripts/validate.py` and `claude plugin validate .` pass.**
- [x] **Step 3: Commit** `docs(memory): agents change records only through mem commands`.

## Pre-mortem of 2026-11-17 and what changed

| Risk found | Change |
| --- | --- |
| `snapshot` is not an undo log; `restore s:` would replay an earlier entry | Persistent logs named in Architecture; test that restore after `rename` does not undo an earlier `edit` |
| `rename` and `remove` change several files, `restore` put back one | One group entry in the root log, restored whole |
| Refreshing `part_of_hash` on rename hides stale notes | Hash kept |
| Claim and topics edits leave the README index stale; foreign topics fail `rule_domain` | `apply_index` after edit and restore; topics limited to the note's domain |
| The sentence rule refuses every claim correction | Not applied to single-sentence fields |
| An edit racing `unify`/`rename` writes an old path back | Temp file plus `os.replace`, refused when the file changed since read |

## Results

All four tasks built, each reviewed once and fixed: `note edit` (rollback on any error, changed-since check just before the swap), `memory edit` (file rolled back on any error; retired memories refused), synthesis `rename`/`remove`/`detach`/`topics` with one group undo entry and a restore that chooses group or own entry by content, not by timestamp; the skills state the rule once. Engine tests: 809 passed, 4 skipped (745 on `main` before). Deferred (low): `updated` added only when a note has the key; `_restore_group` duplicates `_swap_file`; `remove` detaches notes edited after their part was written (reversible). The branch carries the test-isolation commit also in PR #120.
