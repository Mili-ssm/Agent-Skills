# Follow-ups of the weekly usage study (2026-11-18)

Source: [docs/studies/2026-11-18-weekly-usage.md](../../studies/2026-11-18-weekly-usage.md) (suggestions G1 to G7). The owner approved this order on 2026-11-18. Hand-written plan: each task is an outcome with its check.

- [x] **1. Record the study.** `docs/studies/2026-11-18-weekly-usage.md` holds observations, suspicions and suggestions. Check: `python3 scripts/validate.py`.
- [x] **2. Waiting and worktree rules for `implementer` (G2).** ADR 0025. Agent body only, no `description` change, so it ships unmeasured with a kill criterion in the ADR. Check: `python3 scripts/port.py`, `python3 scripts/validate.py`, `claude plugin validate .`; one `prompt-engineer` review of the changed bodies.
- [x] **3. Session length (G3).** Owner's ruling (2026-11-18): a habit, no line in `user-config/routing.md`. Recorded in the study's Status column.
- [ ] **3b. Shell (G1).** `CLAUDE_CODE_SHELL=/usr/bin/bash` is set in the owner's `~/.claude/settings.json` (backup in `~/.claude/backups/settings-2026-11-18-before-shell.json`). Check, in a new session: `echo $0` and `echo ===` in the main session and in one subagent print without error.
- [x] **3c. Inline checks (G6, suspicion S3).** Measured over all 453 inline checks; figures in the study ("Inline checks, measured for suspicion S3").
- [x] **3d. Checks row of the offload table (G6).** Narrowed at the owner's request; eval table in ADR 0010, Review 2026-11-18.
- [ ] **3e. Re-paste the offload block** into the owner's `~/.claude/CLAUDE.md` after the G6 pull request merges (ADR 0021). Check: the block's commit marker names the merge commit.
- [ ] **3f. `offload-ui-verifier-with-policy` degraded on `main`** (2 of 6 runs pass every grader against 6/6 on 2026-11-04; ADR 0010 Review 2026-11-18). Read one failing trace before any eval. Check: the cause named in ADR 0012 as a `## Review`.
- [ ] **4. Issues #124 and #125 (G4), and the review route (G5).** The owner rules on each issue's open questions; then one plan per accepted agent change. Check: each issue closed or carrying the ruling.
- [ ] **5. Seamless memory, stage 2.** Resume from "Where to resume: stages 2 to 5" in [2026-11-17-memory-seamless.md](2026-11-17-memory-seamless.md). Check: that plan's own.
- [ ] **6. Kill read of the memory plugin, around 2026-12-01.** From the usage and hook logs, into ADR 0023 as a `## Review`. Check: the Review section exists.

Not in this plan until the owner decides: G7 (skills with no load, read again after 2026-11-25).
