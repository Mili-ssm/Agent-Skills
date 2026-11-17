# Memory store curation and a trial fixture

Owner's request, 2026-11-17: bring the linked origin documents into the default store, run an intensive curation pass over the general memory, leave the store's git remote for after a period of use, and give tests and trials a fixture that keeps them inside the repository (plugin from the repository, store in an ignored folder) instead of the owner's real store.

**Status:** in progress. The store is outside this repository: its work is recorded here without note titles (public repository).

Rules for this work: a backup of the store is taken before any change (`~/.local/share/agent-memory/backups/`, outside the store); every store change goes through `mem` (undo by `mem restore`), except copying the linked documents, which `mem import` does not cover; the origin repository is read, not written (the owner's standing rule until the plugin is finished; moving documents out of it is put to the owner).

## Tasks

- [x] Backup of the store before any change. Check: the archive lists the store's files.
- [x] Linked origin documents copied into the store at the paths the notes' links expect, so the links resolve without rewriting; links to origin files that would act as context files in the store (a root `AGENTS.md`) are pointed at a copy under `docs/`. Check: `mem check` reports no broken link. *Done 2026-11-17: the origin's whole `docs/` tree copied (links between its documents resolve too); its root files under `docs/origin/`; links inside the copies rewritten to the copies; two note links rewritten; `mem check` exits 0 with no problem; the origin unchanged.*
- [ ] Notes that may say the same: each pair in `mem curate --notes` decided (`unify`, `distinct` or left with a reason). Check: the block is empty or each left pair has its reason.
- [ ] Syntheses for the topics `mem curate --notes` lists (8 notes or more, none yet), written by the `memory-synthesis` method: one pilot topic first, read by the controller before the rest; then waves of parallel writers. Check per synthesis: `mem check` passes, every part ends with `Sources:` naming notes it read, and its notes are attached.
- [ ] This repository's project memories curated (`mem curate` from the repository). Check: the queue prints nothing, or each item left has its reason.
- [ ] Trial fixture: one helper all trial scripts use, which puts their work folders, store, data and config under an ignored `target/` folder of the repository, loads the plugin from the repository, and keeps an installed `mem` off `PATH`. Check: each trial script's self-check (or a dry run) shows nothing written outside `target/` and the owner's store unchanged.
