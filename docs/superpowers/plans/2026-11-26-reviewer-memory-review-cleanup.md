# Reviewer fixes, provisional memory kill read, state cleanup

Status: in progress · Date: 2026-11-26 · Owner request: `skeptical-reviewer` review, then the memory review and seamless stage 3, fix memories and docs, clean merged branches.

Owner rulings (2026-11-26): provisional kill read now, formal record in ADR 0023 on 2026-12-01; delete merged branches locally, on GitHub and their worktrees; memories = stale state memories plus a first project synthesis; P1 evals authorized up to 5 USD; spent 5.15 USD (in-flight runs passed the cap), recorded in ADR 0017.

- [x] Branch cleanup. Check: `git branch -r` shows only `dev`, `main`, `idea/memory-reminders`; `git worktree list` shows the main tree and one worktree locked by a live session. Every removed worktree's commits were in `origin/dev` by patch (`git cherry`), except one whose file moved and evolved in dev (`tests/synthesize/test_synthesize_references.py`, Ruff clean).
- [x] P1: cut "PR or diff review (code-review)" from the `skeptical-reviewer` description (own commit). Check: Eval protocol, agent description row: `offload-skeptical-reviewer-*` and every `neg-*` at 2 runs, Sonnet main; table in ADR 0017 `## Measurement`.
- [x] B1: the body accepts a process-review brief and its checklist has a `Process` row. Check: one process-review trace.
- [x] Provisional kill read: the figures of the plugin plan's kill criteria from the plugin's logs. Check: figures with their source in the memory plan § Current state, labeled provisional.
- [x] Stale state memories (project and auto memory) superseded or forgotten. Check: `mem search` for refactor state returns no claim git contradicts.
- [x] First project synthesis of this project's memories. Check: `mem check` passes.
- [x] Docs: backlog refresh (A5, A14 done; D2, D7, D9), memory plan § Current state. Done 2026-11-26 except D2 (with seamless stage 3), the D7 and D9 leftovers listed in the backlog rows. Check: `python3 scripts/validate.py`.
- [ ] Seamless stage 3 T2–T5: task plan from its design (with amendments A3–A7), `pre-mortem`, then the plan loop. Plan and pre-mortem done 2026-11-26; owner ruling: stop before execution, the owner reviews the plan and how it works with Fable 5.2 first. Check: its revised kill criteria.
