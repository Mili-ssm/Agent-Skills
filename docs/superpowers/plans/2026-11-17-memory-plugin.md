# Memory plugin

Goal: sessions in any repository, and their subagents, recall from and write to the owner's note store and a per-project memory (owner, 2026-11-17). Design and evidence: [the design](../specs/2026-11-17-memory-plugin-design.md); decision: ADR 0023 (proposed). `agent-skills`, the mods and the ports do not change.

Each stage is installable and revertible on its own, ends with the owner's review, and gets its own task plan (Superpowers `writing-plans`) and one `pre-mortem` when it starts, not before: a detailed plan written now would be stale by then. "The store" is the owner's note repository; work there follows its own rules and decision records, including a measured comparison, with a rule written beforehand, before any change to what its search prints.

- [ ] **0. Proposal.** ADR 0023, the design and this plan reviewed by the owner; ADR 0023 moves to accepted or is amended. Check: `python3 scripts/validate.py` and `claude plugin validate .` pass; the owner's word in the conversation before any push or pull request.
- [ ] **1. Reach and orient** (U1, U2, U3, U8). `plugins/memory/` with `plugin.json` (`userConfig.store`), `bin/mem`, the `memory` skill, the marketplace entry and README row; `session-index` in the store's tool; the `SessionStart` and `SubagentStart` hooks, which read a cached index file and start no interpreter. The index states the order: recall before researching or dispatching a web researcher, and carry what was found in the brief (N10). The store's usage log records whether a call came from outside the store, and the `SessionStart` hook logs the date of each session started outside it. `mem` prints one line when the store's tool is older than a command needs. Check, in a scratch repository with the plugin enabled:
  - `mem search "<a known topic>"` prints the store's results, in the main session and in a Haiku subagent, with no permission prompt once the allow rule is set;
  - a headless session can quote the index and a subagent, including one that skips context files, can quote its three lines; the index is under 1,500 characters and the three lines under 300;
  - the skill is within N1 and N2, read by hand because `scripts/validate.py` does not cover the new plugin; one trigger eval case for its description at 2 runs (N6), and no wider suite;
  - with the store path missing or the network down, the session starts with no error; each hook logs its own duration and stays under 0.5 s, also with ten subagents started at once;
  - one `neg-*` eval case gives the same result with the plugin enabled and disabled; if not, eval runs disable it (G8);
  - `claude plugin validate .` passes and `scripts/port.py --check` shows the ports unchanged.
- [ ] **2. Kill read.** After two weeks of use of stage 1, read the criteria below with the owner. Check: the figures are recorded in ADR 0023 as a `## Review`; later stages start only if it passes.
- [ ] **3. Project scope** (U2, U4, U5). `.memory/` at the main worktree's root so linked worktrees share it, `mem note`, `--scope`, `valid_until` for `state` notes, the `.git/info/exclude` entry, the `PreCompact` hook, and a local list of forbidden terms checked on every write to the global scope. In the store: a decision record for the scope, and the comparison for searching both scopes at once. Check: a note written in one session appears in the next session's index; it survives `git worktree remove`; `git status` in the project shows nothing new; a global write that contains a listed term is refused, and a scan of the global scope with the list returns no hit; after a manual compaction the summary names the active plan's path; one session transcript shows the note was written through `mem`, not with a file write.
- [ ] **4. Leads** (U6). In the store: a decision record for the note type, the type itself with its expiry, and the comparison before leads print beside verified notes with their trust grade. Here: the reminder hook after the web researcher returns, once a dump of the hook's input shows it names the subagent. Check: a lead written in one repository is found from another and prints as unverified; an expired lead appears in the store's review list.
- [ ] **5. Curate** (U9). `superseded_by` for every note and `valid_until` beyond `state` notes, hidden from search by default, after the store's comparison. Check: a superseded note is not returned, and is returned on request.
- [ ] **6. Sync** (U7). Background pull at session start; "not pushed" and "diverged" lines in the index. Check: with two clones, a pushed note appears in the other clone's next session; a diverged clone prints the rebase command and changes nothing.
- [ ] **7. Experiment: recall before a web search** (U1). A rule written beforehand, agent runs with and without the hook, total tokens and correct answers compared. Check: the rule and the result are recorded in ADR 0023 as a `## Measurement`; adopted only if it passes.
- [ ] **8. Move the engine** (ADR 0023, second step), only after stage 2 passes. The store's rules in a configuration file; the tool's code in this plugin; `init` for an empty store. Check: the store's own checks and search evaluation give the same figures before and after.
- [ ] With stage 1, and again after each later stage: the owner's user-level text about the note repository cut to what the skill and the index do not say; requirement rows added. A routing row in `user-config/routing.md` only if the kill read shows the index is not enough, with a kill criterion and worded so the ports stay correct. Check: `python3 scripts/port.py --check` passes; the pasted blocks of the owner's file equal `origin/main` (ADR 0021).

## Kill criteria

| Signal | Read at | Action |
|---|---|---|
| Day ratio: days with a recall call from outside the store, divided by days with a session started outside it (both read from the logs of stage 1), is below 0.5. The threshold is the agent's proposal | Stage 2 | Reword the index and the skill once; if still below after two more weeks, stop |
| A hook's logged duration exceeds 0.5 s, or a session fails to start because of one | Any time | Disable the hook until fixed |
| The day ratio is below 0.5 while subagents still receive their three lines | Stage 2 | Remove the `SubagentStart` hook first |
| An eval case changes with the plugin enabled | Stage 1 | Disable the plugin in eval runs |
| The index exceeds its cap or lists project notes past `valid_until` | After stage 3 | Fix the generator before stage 4 |
| A session transcript shows a note written without `mem` | After stage 3 | Fix the skill and the index before stage 4 |
| The scan with the list of forbidden terms finds a hit in the global scope, or the owner reports a business name there | Each stage's check from stage 3 on | Stop global writes from other repositories until promotion is redesigned |
| A store comparison fails twice for one stage | Stages 3 to 5 | Re-plan that stage |
| The owner turns the plugin off | Any time | Record why in ADR 0023 and stop |

## Pre-mortem of 2026-11-17 and what changed

| Failure story | Amendment |
|---|---|
| Agents never call the memory: the web researcher has no Bash tool, the order in always-loaded text decides the path, a subagent may meet a permission prompt, and the usage log could not tell where a call came from | The first draft's two stages (command, then index) became stage 1, so the index ships with the command and states the order; the allow rule, the Haiku subagent check and the two log fields are in stage 1; the kill signal is a ratio of days |
| A hook starts an interpreter for every subagent and stalls sessions; hooks shift eval figures unseen | Hooks read a cached file; duration logged; the eval check on and off |
| Project notes are lost with a removed worktree or go stale; agents write files directly | The folder sits at the main worktree's root; `valid_until` for `state` notes moved up; a trace is read |
| A business name reaches the global scope through a direct write | A local list of forbidden terms checked on write; the index never prints the store path as a place to write. The list catches only names already on it, so the agent remains the check |
| Work in the store stalls on its comparisons; a second machine runs an older tool | The comparisons are named in stages 3 to 5 with a re-plan trigger; `mem` reports an older tool; stage 8 waits for the kill read |

## Risks not yet resolved

- No measurement shows that a session index raises task success; stage 1 ships unmeasured (N6 allows it with these criteria).
- The web researcher depends on its caller to recall before dispatch and to write the lead after.
- Whether a `PreToolUse` hook can add context without blocking is only partly documented; stage 7 tries it first.
- Whether `claude plugin eval` loads plugins the user has enabled is not known; stage 1 checks it.
