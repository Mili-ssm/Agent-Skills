# Memory plugin

Goal: sessions in any repository, and their subagents, recall from and write to a store of notes and memories and a per-project memory (owner, 2026-11-17). Design and evidence: [the design](../specs/2026-11-17-memory-plugin-design.md); decision: ADR 0023 (proposed). `agent-skills`, the mods and the ports do not change, and neither does the owner's note repository until stage 7.

Each stage is installable and revertible on its own, ends with the owner's review, and gets its own task plan (Superpowers `writing-plans`) and one `pre-mortem` when it starts, not before: a detailed plan written now would be stale by then. Code is written on a branch of this repository and pushed; tests that write use a disposable copy of the notes, never the note repository itself.

- [ ] **0. Proposal.** ADR 0023, the design and this plan pushed on the branch `docs/memory-plugin-proposal` and reviewed by the owner. Check: `python3 scripts/validate.py` and `claude plugin validate .` pass; the three files hold no path, name or note title from the private repository.
- [ ] **1. Engine and reach** (U1). *Built and measured on 2026-11-17 except the two eval checks, which wait for the owner to trust the plugin folder; results in [the stage 1 plan](2026-11-17-memory-plugin-stage-1.md#results). The engine is one file for now; the split into modules moves to stage 2.* `plugins/memory/`: the engine as a Python package copied from the search tool and split into modules, `bin/mem`, `plugin.json` with `userConfig.store`, the `memory` skill, the marketplace entry and README row, a usage log in the plugin's data folder. Check:
  - on a disposable copy of the notes, the copy's search evaluation gives the same figures as the original tool, and its first ten results are identical for twenty fixed queries;
  - in a scratch repository with the plugin enabled, `mem search "<a known topic>"` prints results in the main session and in a Haiku subagent, with no permission prompt once the allow rule is set; with no store set, the command says how to set one;
  - the skill is within N1 and N2, read by hand; one trigger eval case at 2 runs (N6);
  - one `neg-*` eval case gives the same result with the plugin enabled and disabled; if not, eval runs disable it (G8);
  - no file under `plugins/memory/` holds a path, name or note text from the private repository; `claude plugin validate .` passes and `scripts/port.py --check` shows the ports unchanged.
- [ ] **2. Notes and memories** (U2, U5, U6). The two kinds of record with their fields, `remember`, the project folder at the main worktree's root with its `.git/info/exclude` entry, `--scope`, the local list of forbidden terms, the check at writing that prints similar records, handles that carry the kind (`m:` or `n:`). Check: a memory written in one session is found in the next; it survives `git worktree remove`; `git status` in the project shows nothing new; a global write that contains a listed term is refused, and a scan of the global scope with the list returns no hit; writing a near-copy of an existing record prints that record and asks which to do; every search result says "note" or "memory"; one session transcript shows the memory was written through `mem`, not with a file write.
- [ ] **3. Orient** (U2, U3, U4, U8). `session-index`; the `SessionStart`, `SubagentStart` and `PreCompact` hooks; the reminder when the web researcher returns, once an event that fires at its return is found; the index states the order: recall before researching or dispatching a web researcher, and carry what was found in the brief (N10). Check: a headless session can quote the index and a subagent, including one that skips context files, can quote its three lines; the index is under 1,500 characters and the three lines under 300; with the store path missing the session starts with no error; each hook logs its duration and stays under 0.5 s, also with ten subagents started at once; after a manual compaction the summary names the active plan's path.
- [ ] **4. Kill read.** After two weeks of use of stages 1 to 3, read the criteria below with the owner. Check: the figures are recorded in ADR 0023 as a `## Review`; later stages start only if it passes.
- [ ] **5. Curation** (U9, U10). `review`, `similar --unlinked`, `confirm`, `refute`, `merge`, `supersede`, `promote`, `forget`; the `memory-curation` skill with one trigger eval case at 2 runs (N6); the queue's size in the session index. Check: on a disposable copy seeded with five duplicates, three unlinked similar pairs and two expired memories, `review` lists all ten and nothing else from the seeded set; `merge` leaves no broken link; a refuted memory is not returned by default; `promote` prints a draft and copies no text.
- [ ] **6. Signal** (U1, U11). An evaluation set of prompts and web queries in Spanish and English with the records that truly relate to each, written without looking at search results; the rule for adoption written before any run; the bands calibrated on half of the set and scored on the other half; the three means for Spanish prompts compared; the two forms of the hint (handles, per-call reference) compared in agent runs. Then the hooks, each only if the rule passes for its kind of text: `PreToolUse` on `Agent` (the brief, in English, expected first), `UserPromptSubmit` (the prompt), and `PreToolUse` on the web search tool if context can be added without deciding the permission. Check: the rule, the figures and the choice are recorded in ADR 0023 as a `## Measurement`; a hook ships only if the rule passes; it prints nothing for the evaluation texts that have no related record, stays under 300 characters and under 1 s, and skips task notifications.
- [ ] **7. Sync and adoption** (U7). The owner chooses the repository that syncs the global scope. Background pull at session start; "not pushed" and "diverged" lines in the index; if the choice is the note repository, the change there follows its own rules and decision records. Check: with two clones, a pushed record appears in the other clone's next session; a diverged clone prints the rebase command and changes nothing.
- [ ] **8. Rust decision.** Hook and search times from the usage log, and the number of changes to the record model since stage 2, put to the owner. Check: the decision and its figures are recorded in ADR 0023.
- [ ] With stage 3, and again after each later stage: the owner's user-level text about the note repository cut to what the skill and the index do not say; requirement rows added. A routing row in `user-config/routing.md` only if the kill read shows the index is not enough, with a kill criterion and worded so the ports stay correct. Check: `python3 scripts/port.py --check` passes; the pasted blocks of the owner's file equal `origin/main` (ADR 0021).

## Kill criteria

| Observation | Read at | Action |
|---|---|---|
| Day ratio: days with a recall call, divided by days with a session started outside the store (both from the plugin's logs), is below 0.5. The threshold is the agent's proposal | Stage 4 | Reword the index and the skill once; if still below after two more weeks, stop |
| The day ratio is below 0.5 while subagents still receive their three lines | Stage 4 | Remove the `SubagentStart` hook first |
| A hook's logged duration exceeds its budget, or a session fails to start because of one | Any time | Disable the hook until fixed |
| An eval case changes with the plugin enabled | Stage 1 | Disable the plugin in eval runs |
| The index exceeds its cap or lists memories past `valid_until` | After stage 3 | Fix the generator before the next stage |
| A session transcript shows a record written without `mem` | After stage 2 | Fix the skill and the index before the next stage |
| The scan with the list of forbidden terms finds a hit in the global scope, or the owner reports a business name there | Each stage's check from stage 2 on | Stop global writes from other repositories until `promote` is redesigned |
| The review queue grows for two weeks in a row | After stage 5 | Tighten the check at writing before adding any hook that invites more writing |
| The signal's rule fails on the held-out half | Stage 6 | Do not ship the hook; keep the session index |
| The owner turns the plugin off | Any time | Record why in ADR 0023 and stop |

## Pre-mortem of 2026-11-17 and what changed

Run on the first draft of this plan, before the owner's second round of decisions.

| Failure story | Amendment |
|---|---|
| Agents never call the memory: the web researcher has no Bash tool, the order in always-loaded text decides the path, a subagent may meet a permission prompt, and the log could not tell where a call came from | The index states the order; the allow rule and the Haiku subagent check are in stage 1; the logs give a ratio of days |
| A hook starts an interpreter for every subagent and stalls sessions; hooks shift eval figures unseen | The two hooks that run most print a cached file; durations logged; the eval check on and off |
| Project memories are lost with a removed worktree or go stale; agents write files directly | The folder sits at the main worktree's root; `valid_until`; a transcript is read |
| A business name reaches the global scope through a direct write | A local list of forbidden terms checked on write; the index never prints the store path as a place to write. The list catches only names already on it, so the agent remains the check |
| Work stalls between two repositories with different rules; a second machine runs an older tool | No longer applies as written: the note repository is not touched until stage 7, and the engine ships with the plugin |

## Risks not yet resolved

- No measurement shows that a session index raises task success; stages 1 to 3 ship unmeasured (N6 allows it with these criteria).
- The web researcher depends on its caller to recall before dispatch and to write the findings after.
- The stages added in the second round (curation, the signal, the copy of the engine) have had no pre-mortem; each gets one when it starts.
- Whether `claude plugin eval` loads plugins the user has enabled is not known; stage 1 checks it.
- Spanish prompts against English records: none of the three means has been tried.
