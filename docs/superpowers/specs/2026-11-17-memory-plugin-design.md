# Memory plugin: notes reachable from every repository and subagent

Status: proposed · Date: 2026-11-17 · Decision: [ADR 0023](../../adr/0023-a-memory-plugin-makes-a-note-store-reachable-from-every-repository.md) · Plan: [2026-11-17-memory-plugin.md](../plans/2026-11-17-memory-plugin.md)

Nothing is built. This file holds the intent, the design, the evidence and the change impact; the plan holds the order of work.

## Intent

The owner's note repository (about 1,060 Markdown notes with a one-file search tool, private) is used only by sessions started in its folder. The plugin makes it, and a per-project memory, available to every session and subagent, so that an agent asks the memory before it researches or re-reads, and writes down what it learns.

| In scope | Out of scope for a first version |
|---|---|
| Recall from any repository; a session index at start; capture in one call; task state across compaction; leads from web research; a per-project scope; sync of the global scope through git | Cloud sessions, the Copilot and Codex ports, embeddings or a vector database, a knowledge graph built by a model, background agents that rewrite notes, any hook that calls a model |

## Terms

| Term | Meaning |
|---|---|
| Store | A folder of notes the plugin reads and writes; the owner's note repository is the first |
| Global scope | Generic, abstract knowledge: lessons about code and design, summaries of sources, investigations. No business names |
| Project scope | A hidden folder at a project's root with what is specific to it: what it uses, what was decided, what does not work because of its business constraints |
| Lead | An unverified finding from web research, with its URL, date and expiry |
| Trust grade | Printed with each result and derived from fields the notes already have: *verified* (a source note, or a claim backed by one), *experience* (a lesson from work), *unverified* (a lead) |
| Session index | The short text printed at session start: what the memory holds and the commands that open it |

## Use cases

| Id | Moment | Need | Today |
|---|---|---|---|
| U1 | Before researching, in any repository | "Do we already know this?" | Only from the note repository's folder |
| U2 | Session start | Decisions, constraints and pitfalls of this project | Auto memory: one repository, one machine |
| U3 | A subagent starts | The lessons that apply to its task | Nothing reaches it unless its brief carries them |
| U4 | After compaction or in a new session | Where the work stands | Plan files, when written (G3) |
| U5 | A task ends, or the owner corrects the agent | Keep the lesson in one call | Auto memory, or a full note-writing procedure |
| U6 | A web-research subagent returns | Keep the findings so the search is not repeated | Lost |
| U7 | The owner changes machine | The same memory | The note repository syncs; auto memory does not |
| U8 | The owner asks what the memory holds | A short readable view | Generated listings in the note repository only |
| U9 | A fact changes | The old note stops being returned | Manual edit |
| U10 | A project lesson is general | Promote it without business names | Manual |

## Design

### Components

| Component | What it is | Serves |
|---|---|---|
| `bin/mem` | A launcher on the Bash tool's path that runs the store's search tool with the configured store path. Step two of ADR 0023 replaces it with the tool itself | U1, U5 |
| Skill `memory` | The recall recipe (search, open the conclusion, read deeper only if needed), when to write, and what goes where | U1, U5 |
| `userConfig.store` | A `directory` value asked when the plugin is enabled; hooks read it from `CLAUDE_PLUGIN_OPTION_STORE`, following the documented `CLAUDE_PLUGIN_OPTION_<KEY>` pattern | U7 |
| Hooks | Commands that print short fixed text (table below) | U2, U3, U4, U6 |
| Project folder | `.memory/` (proposed name), one Markdown file per note | U2, U4 |

### What goes where

One home per kind of fact, so the memory, auto memory and context files do not contradict.

| Fact | Home |
|---|---|
| How the owner wants the agent to work (preferences, corrections) | Claude Code auto memory, unchanged |
| What this project uses, decided or cannot do, with names | Project scope |
| A lesson that holds beyond the project, a source summary, an investigation | Global scope, abstracted |
| A web finding not yet checked against its source | Global scope, as a lead |
| The state of the task in progress | The plan file (G3); the project scope keeps only a pointer to it |

### Project scope

- One file per note with a `kind` (`decision`, `constraint`, `pitfall`, `state`), a one-sentence claim, a date, and optional `superseded_by` and `valid_until`.
- At the main worktree's root, so linked worktrees share it and removing one loses nothing.
- Local by default: the folder is added to `.git/info/exclude`, so the project's own ignore file is untouched. A project opts in to committing it; then the notes travel with the code and business names stay in the business's repository.
- Plain files, so a subagent with only Read and Grep can use it.
- Outside the store, writing defaults to the project scope. Writing to the global scope is a separate, explicit call, the skill states the abstraction rule, and the call is refused when the text contains a term from a local list of forbidden terms that is never committed.

### Command surface

The store's tool already has the commands in the first row; they were shaped by measuring how agents call them.

| Group | Commands | State |
|---|---|---|
| Recall and reading | `search` (ranked, `--links` for neighbours), `show` (one section, outline, line range), `passages` (the best passages of a source copy), `related`, `find`, `topics` | Exist |
| Writing | `new` with the whole body in one call and an inline check, `rename` that rewrites links, `check` | Exist |
| Session index | `session-index`, with a three-line form for subagents | New |
| Project scope | `note` (write one project note), `--scope project|global|all` on `search` | New |
| Leads and curation | `new lead`, expiry listed by `review`, `superseded_by` and `valid_until` | New |
| Sync | `sync --pull` (fast-forward only, silent offline), a "not pushed" and "diverged" line in the session index | New |

### Hooks

Each is a `command` hook that exits 0 whatever happens, prints nothing when no store is set, calls no model and starts no interpreter: the session-start and subagent-start hooks print a cached file that the tool rewrites after each write to either scope and after each pull, because a subagent start happens many times per task. Each hook logs its duration and stays under 0.5 s.

| Event | Prints | Limit |
|---|---|---|
| `SessionStart` | The session index: store path, topic tree with counts, the claims of this project's notes, the three recall commands, notes not pushed | Target under 1,500 characters; the same text until the store changes, so a cached prefix is not broken |
| `SubagentStart` | Three lines: the memory exists, the recall command, the project folder | Under 300 characters |
| `PreCompact` | An instruction for the summary: keep the active plan's path and any lesson not yet written | Fixed text |
| `PostToolUse` on `Agent`, when the subagent is the web researcher | One line: write the findings as a lead | Fixed text; that the hook's input names the subagent is confirmed in stage 4 before it is built |
| `SessionStart`, asynchronous | Nothing: pulls the global scope, fast-forward only (see Sync) | Never blocks the session |
| `PreToolUse` on the web search tool | The first three memory results for the query | **Experiment only**, adopted if a rule written beforehand passes in agent runs |

The session index names the command that opens each thing it lists, and nothing is dropped from a note to shorten it: the index is a way in, not a replacement.

### Sync

The global scope is a git repository. The plugin pulls at session start in the background, fast-forward only. Commit and push stay explicit and pass through the store's own pre-commit check, because a pushed secret or business name cannot be recalled from other clones. When local commits are not pushed and the remote has moved, the pull fails; the session index then says the store has diverged and names the command that rebases.

## Owner decisions and open choices

| Id | Decided by the owner on 2026-11-17 |
|---|---|
| D1 | Two scopes: generic and abstract knowledge apart from project-specific memory in a hidden folder of the project |
| D2 | The plugin is the engine; the note repository is its first store and keeps its stricter rules |
| D3 | The agent writes explicitly; no hook writes for it, though one may remind it |
| D4 | A first version reaches local Claude Code and its subagents |
| D5 | The global scope lives at a configured path (the note repository), not in the plugin's data folder |
| D6 | The project folder is local by default and committed only when a project opts in |
| D7 | The engine's code moves in two steps |
| D8 | Leads are a note type of the store, with an expiry |

Shown to the owner and not ruled on (the agent's choices, all reversible): the command plus skill and no MCP server; the hook set above; pull automatic, push explicit; auto memory left unchanged; the out-of-scope list of the Intent table, except cloud sessions and the ports, which D4 covers. Added after the plan's pre-mortem and not yet shown: the cached index file, the local list of forbidden terms, the folder at the main worktree's root.

Not settled: how a project note is promoted to the global scope (a command that prints a draft for the agent to abstract, never a copy); the contents of the store configuration file of step two; the folder name.

## Evidence

Status values: "Checked" means a second agent opened the page on 2026-11-17 and quoted it, at the place named; "Partly" means it found the statement only in part; "Lead" means one agent read it and nobody re-opened it; "Measured there" means the owner's own measurement, which this repository cannot show.

| Claim | Source | Status |
|---|---|---|
| Plugin hooks run inside subagents; a `SubagentStart` hook can inject context; `SessionStart` stdout is added as context | `code.claude.com/docs/en/hooks`, `…/sub-agents` | Checked |
| Injected strings are capped at 10,000 characters; `PreCompact` stdout becomes instructions for the summary and is cut at the cap | `code.claude.com/docs/en/hooks` | Checked |
| A plugin's `bin/` is on the Bash tool's path; `userConfig` has a `directory` type and reaches hooks as an environment variable; the plugin's data folder is deleted on uninstall by default | `code.claude.com/docs/en/plugins-reference` | Checked |
| A `PreToolUse` hook can add context without blocking the call | Same page | Partly: the field is listed, no example found; to be tried |
| Auto memory is machine-local, loads the first 200 lines or 25 KB of its index and is not loaded into subagents | `code.claude.com/docs/en/memory`, `…/sub-agents` | Lead |
| Memory injection was about 12% of billed cost in multi-agent workflows on a 200-task benchmark | arXiv 2609.23790 (preprint) | Checked on the abstract |
| Injecting a matched skill lowered mean Pass@2 by 1.3% to 4.2% and raised token cost by 72% to 394% | arXiv 2608.23067 (preprint; skills, not memory) | Checked on the abstract |
| Errors in stored experiences compound in later runs | arXiv 2505.16067 | Checked on the abstract |
| In one observed case a model's rewrite of a whole context cut it from 18,282 to 122 tokens and lowered accuracy | arXiv 2510.04618 | Checked in the full text |
| Libraries of lessons raised scores over a no-memory baseline | arXiv 2308.10144, 2409.07429, 2508.06433, 2509.25140 | Leads; each is its authors' own evaluation |
| Other memory tools share a session index plus reading on demand; reported problems are stale memory, silent truncation of the index and unnoticed background rewrites | Vendor docs (some read only as search snippets) and issue reports read through a mirror | Leads |
| In the owner's store, answers cited the first one to three search results, agents did not ask for a second page, and a 20% cut in printed text did not lower the tokens of a run | The owner's own measurements, 2026-11-15 (private) | Measured there |

No source read measures a session-start or per-prompt memory hook in a coding agent against task success, which is why injection beyond the session index is an experiment.

## Change impact

Change: a new opt-in plugin here, and in the note repository a project scope, a note type and two fields. Compatibility: additive in both; the store's printed search results change, which its own rules treat as a contract with the agents that read them.

| Dimension | Affected | Action |
|---|---|---|
| Marketplace | `.claude-plugin/marketplace.json`, the README catalog | Add the entry and row; check that `scripts/port.py` leaves the new plugin out of the Copilot and Codex catalogs |
| Checks | `scripts/validate.py` reads only `agent-skills` | Until it is extended, the new skill's limits (N1, N2) are checked by hand in stage 1 and `claude plugin validate` is the only automatic check |
| Evals | N6 measures descriptions | One trigger case for the new skill when it is written; no wider suite |
| User-level rules | The owner's text about the note repository; `user-config/routing.md` rows on research | Shrink the first; add a routing row with a kill criterion (ADR 0021) |
| Requirements and ADR 0011 | The Repo role row and the marketplace description name one plugin plus mods; the Runtime row names cloud; G3 (work survives a compaction) gains a second means | Update both on acceptance; add rows for the plugin; note that it is local only |
| Note repository | Its tool, note schemas, checks, agent contract and the requirement that fixes three note types | A decision record there for the lead type and the project scope; a measured comparison before leads print beside verified notes |
| Each project | `.memory/`, `.git/info/exclude` | Written on first use, never the project's ignore file |
| Cost | A session index per session, three lines per subagent | Caps above; measured in the first stage that adds them |

| Risk | Rating | Mitigation |
|---|---|---|
| A business name reaches the global scope from a work repository | high | Writing defaults to the project scope outside the store; global writes are explicit and checked against a local list of forbidden terms; no automatic push. The list holds only names already known, so the agent remains the check, as the store's rule already says |
| A hook fails, hangs or slows every subagent start | medium | Exit 0 always, a cached file and no interpreter, duration logged, nothing printed without a store |
| The hooks change this repository's eval figures (G8) | medium | One eval case run with the plugin enabled and disabled in the first stage; eval runs disable it if they differ |
| The memory, auto memory and context files give different instructions | medium | The "what goes where" table is the only statement; the owner's user-level text is cut to it |
| Agents do not call the command despite the index | high | The web researcher has no Bash tool, so the index tells its caller to recall first and carry the result in the brief; calls from outside the store are counted in the store's usage log; a kill criterion in the plan |
| A lead is read as a verified fact | medium | Trust grade printed with every result; expiry; leads are paraphrase without instructions |
| Text from the web or from a shared project folder carries instructions into later sessions | medium | Notes are data; the index prints claims only; a committed project folder is trusted like the repository's own context file |
| The store's tool passes its own size limit as features are added | low | Step two of ADR 0023 splits it |

Point of no return: none in the plugin. Committing a project folder to a shared repository is the one step that history keeps, and it is opt-in per project.
