# Follow-ups of the weekly usage study (2026-11-18)

Source: the local, unpublished study `.local/studies/2026-11-18-weekly-usage.md` (suggestions G1 to G7). The owner approved this order on 2026-11-18. Hand-written plan: each task is an outcome with its check.

- [x] **1. Record the study.** The local, unpublished study `.local/studies/2026-11-18-weekly-usage.md` holds observations, suspicions and suggestions. Check: `python3 scripts/validate.py`.
- [x] **2. Waiting and worktree rules for `implementer` (G2).** ADR 0025. Agent body only, no `description` change, so it ships unmeasured with a kill criterion in the ADR. Check: `python3 scripts/port.py`, `python3 scripts/validate.py`, `claude plugin validate .`; one `prompt-engineer` review of the changed bodies.
- [x] **3. Session length (G3).** Owner's ruling (2026-11-18): a habit, no line in `user-config/routing.md`. Recorded in the study's Status column.
- [x] **3b. Shell (G1).** `CLAUDE_CODE_SHELL=/usr/bin/bash` is set in the owner's `~/.claude/settings.json` (backup in `~/.claude/backups/settings-2026-11-18-before-shell.json`). Check, in a new session: `echo $0` and `echo ===` in the main session and in one subagent print without error. Verified 2026-11-18: both print `/usr/bin/bash` and `===`.
- [x] **3c. Inline checks (G6, suspicion S3).** Measured over all 453 inline checks; figures in the study ("Inline checks, measured for suspicion S3").
- [x] **3d. Checks row of the offload table (G6).** Narrowed at the owner's request; eval table in ADR 0010, Review 2026-11-18.
- [x] **3e. Re-paste the offload block** into the owner's `~/.claude/CLAUDE.md` (done 2026-11-18; the marker names the commit that changed the file).
- [x] **3f. `offload-ui-verifier-with-policy` degraded on `main`.** Cause found in two kept traces: no Playwright driver resolves in the eval sandbox since the machine lost its global `playwright` package (ADR 0012 Review 2026-11-18).
- [ ] **3g. Restore a browser driver for that case.** The owner chooses: reinstall the global `playwright` package, or make `playwright-cli` (already named in `ui-verifier.md`) find the real home's browsers from the sandbox. Check: the case passes every grader in 2 of 2 runs.
- [x] **4a. Issue #125.** Owner's ruling: widen the `fact-checker` description to batches, keep it read-only. ADR 0018 Review 2026-11-18.
- [x] **4b. Issue #124 (`note-writer`).** Closed by the owner's ruling, 2026-11-25. Owner's ruling: wait; read the general-purpose note-writing calls again in the next usage study and create the agent only if they persist. Read 2026-11-23: they did not persist (89 to 2); the owner closed it on suggestion G17 of the local, unpublished study `.local/studies/2026-11-23-weekly-usage.md`.
- [x] **4c. Review route (G5).** No change needed: the 22 plan-task reviews that went to general-purpose are all dated 2026-11-12 and 2026-11-13, before the plan-loop rule that names `skeptical-reviewer` shipped (2026-11-15, ADR 0019); none after it. Read again in the next study: none in the 2026-11-23 window either.
- [ ] **4d. Offload policy from a session-start hook (G8, the owner's question).** Owner ruling 2026-11-25: plan it (backlog). Decide after reading the next usage study; see the study's suggestion G8. Read 2026-11-23: about 7 USD a week to gain, so the case rests on upkeep, not cost ("Readings owed" in the 2026-11-23 study).
- [x] **5. Seamless memory, stage 2.** Merged in PR 136; stage 3 is next. Resume from "Where to resume: stages 2 to 5" in [2026-11-17-memory-seamless.md](2026-11-17-memory-seamless.md). Check: that plan's own.
- [ ] **6. Kill read of the memory plugin, around 2026-12-01.** From the usage and hook logs, into ADR 0023 as a `## Review`. Check: the Review section exists.

Not in this plan until the owner decides: G7 (skills with no load; second week read on 2026-11-23, see that study), and suggestions G9 to G19 of the local, unpublished study `.local/studies/2026-11-23-weekly-usage.md`.
