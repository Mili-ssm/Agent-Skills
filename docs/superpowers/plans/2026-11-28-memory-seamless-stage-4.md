# Seamless stage 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Approved 2026-11-28. Implemented and trial passed on 2026-11-28. Baseline at `66ee81c`: 102 focused engine tests passed and repository validation passed.

**Goal:** Detect eligible synthesis splits, preview and verify a proposal, and apply or undo the split as one recoverable operation.

**Architecture:** Candidate detection and proposal validation are pure with respect to the store. The CLI plans exact file replacements and applies them through a journal that supports both file creation and removal. The copied-store trial grades the engine and the quality of the selected split before automatic application can ship.

**Tech Stack:** Python engine, pathlib, Markdown and YAML synthesis formats, pytest, existing store fixtures.

**Spec:** [Seamless stage 4 design](../specs/2026-11-28-memory-seamless-stage-4-design.md).

## Global Constraints

- Five distinct, non-superseded notes attached to the same part and explicitly carrying the same strict descendant topic. Exclude topics already declared by the synthesis.
- Keep parent and child links, preserve original references and numeric figures, and keep note claims unchanged. Refuse ambiguous moves and stale input.
- Preserve existing synthesis sections and CLI/import behavior. Add no dependency. One undo operation targets the exact split.
- Test on a disposable store. No unattended application ships before the trial passes. `mem-auto` scheduling belongs to stage 5.

## Review Focus

- An attached note with repeated topics or a missing section contributes at most once to a valid candidate. Task 1.
- Two descendant topics with overlapping moves remain visible but do not auto-apply. Task 3.
- Trailing note reference labels and numeric link targets provide no figure coverage by themselves. Task 2.
- A file absent before apply or absent after undo is a first-class journal state. Task 4.
- An edited destination or a crash during recovery must leave a safe refusal or retry path. Tasks 4–5.

### Task 1: Report split candidates

**Files:** `engine/notes/split_candidates.py`, `engine/notes/__init__.py`, `engine/commands/curate.py`, `engine/tests/syntheses/test_split_candidates.py`, `engine/tests/test_import_graph.py` under `plugins/memory/`.

**Interfaces:** `find_candidates(notes: Iterable[Note], syntheses: Iterable[Synthesis], topics: Mapping[str, dict]) -> list[SplitCandidate]`. A frozen candidate has `part: str` (bare `handle#section`), `topic: str` and `notes: tuple[str, ...]` (sorted store-relative paths).

- [x] Test four versus five qualifying notes, duplicate topic tags, superseded and unattached notes, missing sections, strict ancestry, and declared/unknown topics. The CLI test checks the split block and calls the existing `topics_without_synthesis` parser on the combined result.
- [x] Run `pytest plugins/memory/engine/tests/syntheses/test_split_candidates.py -q`; expect missing candidate import or block.
- [x] Implement using valid note metadata, the existing topic tree, and exact attachment references. Add an independent `synthesis split candidates` block at the end of `mem curate --notes`, with one part, topic and count per row. Reuse the existing live note list.
- [x] Run the focused file, `test_consolidation.py`, and `test_import_graph.py`. Commit Task 1 paths and record red/green evidence.

### Task 2: Validate conservation

**Files:** `engine/syntheses/split_conservation.py`, `engine/syntheses/__init__.py`, `engine/tests/syntheses/test_split_conservation.py` and `engine/tests/test_import_graph.py` under `plugins/memory/`.

**Interfaces:** `check_conservation(root: Path, original: str, retained: str, moved: str) -> list[str]` returns a problem per missing resolved note reference or numeric figure.

- [x] Test canonical equivalents for relative paths, loss of a body or Sources reference, repeated figures, and numeric URLs or trailing citation labels that must not mask missing figures.
- [x] Run the focused test expecting a missing validator.
- [x] Reuse Markdown parsing to compare resolved references and numeric occurrences in stored content. Exclude targets, Sources metadata and trailing citation labels. Retain visible figures in an ordinary link's text.
- [x] Run the focused and import graph tests, then commit Task 2 paths and record red/green evidence.

### Task 3: Prepare and preview proposed splits

**Files:** `engine/commands/split_plan.py`, `engine/commands/__init__.py`, `engine/syntheses/document.py` and `edit.py` for reusable Markdown helpers if needed, `engine/tests/syntheses/test_split_plan.py` and `engine/tests/test_import_graph.py` under `plugins/memory/`.

**Interfaces:** `prepare_split(root: Path, proposal: SplitProposal, today: date, env: Mapping[str, str]) -> SplitPlan`. The proposal has `part`, `topic`, `parent_text`, `child_heading`, `child_text`, and an `expected` mapping of store-relative paths to SHA-256 digests or null for absence. A companion `candidate_input(root: Path, part: str, topic: str) -> dict[str, object]` produces the editable fields and expected digest map from the same candidate resolution. The plan exposes the current part, proposed bodies, destination reference, note moves, `conflicts: tuple[str, ...]` of overlapping candidate topic IDs, and `changes: dict[Path, tuple[bytes | None, bytes | None]]`. It performs zero writes.

- [x] Test new and existing child, links resolved in both directions, stable original section order, all original references (body and Sources) and numeric figures, restamped current parent members, a previously stale parent member kept stale, unchanged claims, child section collision and unsafe paths. Preview overlapping candidates and return their conflict IDs without writing. Refuse a stale plan after a sixth note qualifies, a competing route appears or another synthesis adopts the destination topic.
- [x] Run the focused test expecting a missing planner.
- [x] Derive the destination from the unique synthesis declaring the topic or a new topic-handle file. Derive moves from the candidate and require each moved note to be supported by the child part. Add links in Python. Validate both resulting parts and term/secret guards. Call Task 2's conservation checker. Fingerprint the topic tree and every file the operation would change, with explicit absence for a new child. Recompute eligible members and destination under the lock and require the exact snapshot keys and values. Reuse existing Markdown rendering and attachment fingerprint code. Add links before the closing Sources line. Preserve the stale status of unmoved notes. Keep the preview inspectable without writes.
- [x] Run focused synthesis tests and import graph test. Commit Task 3 paths and record red/green evidence.

### Task 4: Reuse the rollback journal for file creation and deletion

**Files:** `engine/core/file_journal.py`, `engine/core/__init__.py`, `engine/commands/import_recovery.py`, `engine/tests/core/test_file_journal.py` under `plugins/memory/`.

**Interfaces:** `FileJournal(root: Path, directory: str)` with `locked()`, `pending()`, `publish(changes: Mapping[Path, tuple[bytes | None, bytes | None]])`, `rollback()`, and `clear()`. The constructor defaults to split's version 2 and accepts an import version 1 adapter. Preserve the import adapter's callers, `DivergedError`, version-1 format and recovery messages.

- [x] Test new file, deletion, absent versus empty, diverged member refusal before any restoration, and repeated rollback after interruption. Verify existing version-1 import journals are still readable.
- [x] Run the journal tests expecting missing core module.
- [x] Extract common journal mechanics. The caller supplies expected originals and replacements; preflight versions and path containment before publishing any journal. Write version 2 with null for an absent replacement in split journals. Keep the import adapter on version 1 with non-null replacements. Take the operation lock and keep private journal files. Preserve the import adapter's public behavior and path.
- [x] Run journal tests, `test_import.py` and import graph test. Commit Task 4 paths and record red/green evidence.

### Task 5: Apply and undo an exact split group

**Files:** `engine/commands/split_transaction.py`, `engine/commands/__init__.py`, `engine/tests/syntheses/test_split_transaction.py` and `engine/tests/test_import_graph.py` under `plugins/memory/`.

**Interfaces:** `apply_split(root: Path, prepare: Callable[[], SplitPlan]) -> str`, `undo_split(root: Path, group: str) -> None`, `recover_split(root: Path) -> bool` and `split_status(root: Path) -> tuple[bool, list[str]]`.

- [x] Test exact group undo, later-edit refusal, private receipt path containment, failure after first replacement, repeated recovery, and the state after journal clear when stdout was lost.
- [x] Run the focused tests expecting a missing transaction module.
- [x] Serialize split operations with Task 4's lock. Replan under it before publishing and refuse any nonempty `SplitPlan.conflicts`. Place private receipts in `.split-history/`, outside the journal directory. A pending journal blocks new split writes. Removing its journal is the commit point. Recovery rolls back both member files and the receipt. Undo writes a receipt marking the group undone. Status exposes completed, still-undoable groups after interrupted output. Other manual store writers follow the existing single-writer assumption.
- [x] Run crash/recovery tests and the import graph test. Commit Task 5 paths and record red/green evidence.

### Task 6: Apply, recover, and undo through the CLI

**Files:** `engine/commands/split.py`, `engine/commands/__init__.py`, `engine/commands/synthesis.py`, `engine/mem.py`, `engine/tests/syntheses/test_split_command.py` and existing CLI golden fixtures under `plugins/memory/`.

**Interfaces:** `mem synthesis split --candidate PART TOPIC` emits the inputs and expected digests for a proposal. `--preview FILE` validates a JSON proposal and prints the original/retained/moved text and routes. `--apply FILE` reruns validation under the lock through Task 5 and emits the group identifier. `--undo GROUP` targets that exact split. `--recover` restores a pending operation before further split writes. `--status` lists pending state and groups available to undo.

- [x] Add CLI tests for the six mutually exclusive forms, write refusal on an unmarked read-only store, read-only preview, full apply and undo of an absent child, refusal after a later edit, idempotent recovery, and blocking operations while recovery is pending. Inject an I/O error after the first replacement and a subprocess exit between replacements during both apply and undo.
- [x] Run focused tests expecting missing CLI registration.
- [x] Wire commands to the planner and transaction. Move the existing synthesis section parser into `commands/synthesis.py` with its help and arguments preserved if needed to meet the `mem.py` ceiling. Apply the existing writable-store check only to apply, undo and recovery. Candidate, preview and status never create files or take a write lock. Verify that a committed group is discoverable through status and that the existing latest-edit unwinder does not mistake split receipts for ordinary edits.
- [x] Run focused CLI tests, golden help and the import graph/line ceiling checks. Commit Task 6 paths and record red/green evidence.

### Task 7: Grade the copied-store trial

**Files:** `plugins/memory/evals/split/`, plugin README and changelog, this plan and the parent Seamless plan.

- [x] Add a seeded proposal and a deterministic trial using the real CLI on temporary copies with new and existing children. Assert original references and figures, routing, `mem check`, byte-for-byte undo aside from operation history, and failures for invalid reference, missing figure, conflicting destination, interrupted write and later edit.
- [x] Run the trial expecting failure before the harness exists; build the smallest harness that executes and grades those cases.
- [x] Preview and grade the local candidate using a disposable snapshot. Have the synthesis worker produce a proposal file for a mixed part. Independently inspect the retained and moved text. Record a passing verdict only after the worker proposal passes independent semantic review and copied-store apply, check and undo. A missing candidate or unresolved overlap leaves the trial incomplete. Keep raw store content out of tracked files and logs used for reporting.
- [x] Run the engine suite and repository validator. Update usage, recovery and trial status. Commit the trial and docs. A failing or incomplete verdict leaves automatic application gated.

## Trial results

- Synthetic CLI trial passed for a new and an existing destination, including refusal cases, store checks and byte-exact undo. CLI regressions exercised process exits during both apply and undo.
- Copied local store: one candidate, five notes, zero overlapping candidates. The worker's proposal passed independent semantic review. Apply changed seven files. `mem check` returned zero before and after with identical output. Group undo restored every file byte for byte, excluding split history and lock state.
- Engine suite: 3,582 passed, 6 skipped. Repository validation passed. Stage 5 owns unattended scheduling and its budget and failure reporting.
