# Platform parity study (Claude Code, Codex, Copilot, Google)

Status: done · merged in #178, 2026-11-23

Date: 2026-11-23

Goal: document which Claude Code plugin features (skills, agents, commands, hooks, MCP, settings, UI) each other coding-agent CLI supports, so a later port knows what carries over, what is lost and how to work around it. Documentation only: no port is built here.

Owner rulings (2026-11-23):

- Where: this repository (`docs/platform-parity.md`) and the `mem` store (literature notes per vendor page, knowledge notes for cross-vendor claims, a project memory pointing to the doc). Not the research hub, which is to stop receiving studies.
- Refresh: by event only (listed in the doc), no schedule.
- Columns: the CLIs (Claude Code, Codex CLI, Copilot CLI, Google's CLI); IDE and cloud differences as notes.
- Research rules of the hub's `AGENTS.md` and playbook apply in this session (source ranks, notes from source text, fresh-context fact-check); observations on how useful they were go to memory, not into any instruction file.

Finding that changed scope: Google replaced Gemini CLI with Antigravity CLI (`agy`), announced 2026-05-19; the Google column covers Antigravity CLI, with Gemini CLI kept as history.

## Tasks

- [x] Recall (mem, hub, `docs/ports.md`, ADR 0015) and first research round, one researcher per tool. Check: four reports with sources.
- [x] Global `CLAUDE.md`: hub references removed (owner, 2026-11-23). Check: no mention of the research hub remains in the owner's user-level `CLAUDE.md`.
- [x] Second round on Antigravity CLI. Check: report with sources, or the gap named. Result: transition confirmed; Gemini CLI is not archived (v0.70.0 on 2026-11-19, enterprise only since consumer access ended 2026-06-18).
- [x] Literature notes in the `mem` store, written from local copies of each page (one writer per vendor). Check: `mem check <paths>` clean; each note has its `.sources/` folder.
- [x] Fresh-context fact-check of the notes against the local copies. Check: every contradicted or overstated claim fixed. Checked: 32 problems in about 560 claims, none changing a verdict; all fixed with `mem note edit --shrink` (owner authorized it after the permission classifier denied the subagent's run).
- [x] `docs/platform-parity.md`: matrix, per-plugin verdicts with sacrifices and workarounds, refresh events; linked from `docs/ports.md`. Check: every cell traces to a note or a stated gap.
- [x] Knowledge notes for cross-vendor claims and a project memory pointing to the doc. Check: `mem search "port Claude Code plugin to Codex hooks"` finds them.
- [x] Store remote: add the owner's private repository as `origin` and push. Check: `git -C <store> ls-remote origin` shows the branch. Done 2026-11-23: private repository given by the owner, `master` pushed; pushes stay manual until stage 7 automates them.
- [x] Memories: the ruling that supersedes D15 (hub stops receiving studies) and observations on the research rules. Check: `mem memories` lists them.
- [x] Review (`skeptical-reviewer`: round 1, 8 findings, all addressed, the SessionEnd one also in the memory plugin plan; round 2, 4 low/medium findings and 1 nit, all addressed), `python3 scripts/validate.py`, `claude plugin validate .`; commit and pull request to `dev` only with the owner's word.
- [x] Inventory of note-repository features the memory plugin lacks (owner, 2026-11-23): `docs/studies/2026-11-23-note-repository-parity.md`. Check: each gap names its source requirement and a destination.
