# Memory plugin: notes and memories reachable from every repository and subagent

Status: proposed · Date: 2026-11-17 · Decision: [ADR 0023](../../adr/0023-a-memory-plugin-makes-a-note-store-reachable-from-every-repository.md) · Plan: [2026-11-17-memory-plugin.md](../plans/2026-11-17-memory-plugin.md)

Nothing is built. This file holds the intent, the design, the evidence and the change impact; the plan holds the order of work.

## Intent

The owner's note repository (about 1,060 Markdown notes with a one-file search tool, private) is used only by sessions started in its folder. The plugin gives every session and subagent a memory to ask before researching or re-reading, and to write to when something is learned, without filling their context.

| In scope | Out of scope for a first version |
|---|---|
| Recall from any repository; a session index at start; writing a note or a memory in one call; curation; task state across compaction; findings from web research; a per-project scope; signal hooks; sync of the global scope through git | Cloud sessions, the Copilot and Codex ports, a knowledge graph built by a model, background agents that rewrite records, hooks that inject the records themselves |

## Terms

| Term | Meaning |
|---|---|
| Record | A note or a memory: one Markdown file |
| Note | A generic, abstract statement backed by a source or by reasoning. It does not lose weight with age |
| Memory | Something observed or decided in a context: specific, from experience, and doubtful because it is not an established fact. It carries its context, date, how often it was observed and whether it was later confirmed or refuted |
| Store | A folder of records the plugin reads and writes |
| Global scope | The store set when the plugin is enabled: notes, and memories that do not depend on one project. No business names |
| Project scope | A hidden folder at a project's root: memories about what the project uses, what was decided and what does not work because of its business constraints |
| Session index | The short text printed at session start: what the memory holds and the commands that open it |
| Signal | One short text from a hook that says how many records relate to the task and names the best few, without their content |
| Handle | A short unique name of a record, which every command accepts in place of its path |

## Use cases

| Id | Moment | Need | Today |
|---|---|---|---|
| U1 | Before researching, in any repository | "Do we already know this?" | Only from the note repository's folder |
| U2 | Session start | Decisions, constraints and pitfalls of this project | Auto memory, which as read in the docs is kept per repository and per machine |
| U3 | A subagent starts | The lessons that apply to its task | Nothing reaches it unless its brief carries them |
| U4 | After compaction or in a new session | Where the work stands | Plan files, when written (G3) |
| U5 | A task ends, or the owner corrects the agent | Keep the lesson in one call | Auto memory, or a full note-writing procedure |
| U6 | A web-research subagent returns | Keep the findings so the search is not repeated | Lost |
| U7 | The owner changes machine | The same memory | The note repository syncs; auto memory does not |
| U8 | The owner asks what the memory holds | A short readable view | Generated listings in the note repository only |
| U9 | A fact changes, or two records say the same | The old or duplicate record stops being returned | Manual edit |
| U10 | Several memories agree, or a project memory is general | Promote to a note, without business names | Manual |
| U11 | A task touches something the memory knows | The agent learns that it does, without the content being pushed at it | Nothing |

## Design

### Components

| Component | What it is | Serves |
|---|---|---|
| Engine | A Python package in the plugin, started as a copy of the note repository's search tool and split into modules; run with `uv` | All |
| `bin/mem` | The command on the Bash tool's path | U1, U5 |
| Skill `memory` | The recall recipe (search, open the conclusion, read deeper only if needed), when to write a note or a memory, what goes where | U1, U5 |
| Skill `memory-curation` | The review procedure | U9, U10 |
| `userConfig.store` | A `directory` value asked when the plugin is enabled; hooks read it from `CLAUDE_PLUGIN_OPTION_STORE`, following the documented `CLAUDE_PLUGIN_OPTION_<KEY>` pattern | U7 |
| Hooks | Commands that print short text (table below) | U2, U3, U4, U6, U11 |
| Project folder | `.memory/` (proposed name), one Markdown file per memory | U2, U4 |

### Notes and memories

| | Note | Memory |
|---|---|---|
| Says | What holds in general | What was seen or decided, where and when |
| Backed by | A source, or reasoning labelled as such | Experience |
| Scope | Global only | Project by default; global when it does not depend on one project |
| Kinds | Those of the copied tool (source summary, claim, investigation) | `decision`, `constraint`, `pitfall`, `lesson`, `finding` (an unchecked result of web research, with URL and expiry), `state` (a pointer to the active plan) |
| Fields of its own | Confidence, evidence | Context, date, times observed, confirmed or refuted, `valid_until` |
| Ranking | By the words of the query | The same, with less weight when old and never confirmed (to be measured before it is adopted) |
| Ends as | Corrected or superseded | Confirmed, refuted, merged, promoted to a note, or forgotten |

Every search result prints which of the two it is, so a memory is never read as a fact.

### What goes where

One home per kind of fact, so the memory, auto memory and context files do not contradict.

| Fact | Home |
|---|---|
| The owner's preferences and personal matters, how they want the agent to work | Claude Code auto memory, unchanged |
| A discovery, a fact or an assumption about this project (what it uses, decided or cannot do), with names | A memory in the project scope |
| The project's current situation or a special condition (true now, may change) | Both: auto memory, and a `state` or `constraint` memory in the project scope |
| Something learned from experience that does not depend on one project | A memory in the global scope, without names |
| What holds in general, with its source | A note |
| A web finding not yet checked against its source | A `finding` memory |
| The state of the task in progress | The plan file (G3); a `state` memory keeps only a pointer to it |

### Project scope

- At the main worktree's root, so linked worktrees share it and removing one loses nothing.
- Local by default: the folder is added to `.git/info/exclude`, so the project's own ignore file is untouched. A project opts in to committing it; then the memories travel with the code and business names stay in the business's repository.
- Plain files, so a subagent with only Read and Grep can use it.
- Outside the store, writing defaults to the project scope. Writing to the global scope is a separate, explicit call, the skill states the abstraction rule, and the call is refused when the text contains a term from a local list of forbidden terms that is never committed.

### Command surface

| Group | Commands | State |
|---|---|---|
| Recall and reading | `search` (ranked, `--links` for neighbours, `--scope`), `show` (one section, outline, line range), `passages`, `related`, `find`, `topics` | In the copied tool, handles included; `--scope` and the `m:` and `n:` handle prefixes are new (stage 2) |
| Writing | `new` (a note, with the whole body in one call and an inline check), `remember` (a memory in one call), `rename` that rewrites links, `check` | `new`, `rename`, `check` in the copied tool; `remember` new |
| Curation | `review`, `similar`, `confirm`, `refute`, `merge`, `supersede`, `promote`, `forget` | `review` partly in the copied tool; the rest new |
| Session and hooks | `session-index`, `signal` | New (stages 3 and 6) |
| Sync | `sync --pull`, a "not pushed" and "diverged" line in the session index | New (stage 7) |

### Curation

| When | What happens |
|---|---|
| A record is written | Only a memory with exactly the same claim is refused (the answer is `observe`). Otherwise the record is written and the related ones are printed; near-duplicates and contradictions wait for a curation pass (D14). Measured in stage 2: a claim and its negation scored 0.89 on a word-overlap index, so a threshold cannot tell "the same" from "the opposite" |
| `review` | Prints a queue: probable duplicates; similar records that are not linked (`similar --unlinked`); memories past `valid_until`; records never recalled; memories observed three times or more, as candidates for promotion; records marked at writing |
| A memory was used | `confirm` or `refute` records the outcome; a refuted memory is hidden from search by default |
| `merge`, `supersede`, `forget` | Rewrite links as `rename` does; nothing is deleted outside git history |
| `promote` | Prints a draft note from one or more memories for the agent to abstract; it never copies text, because a memory may hold business names |

A curation pass is started on request, after a number of writes, or after a period without one (the session index says when one is due); it may be handed to a small-model subagent that works beside the main task and proposes merges, supersessions and promotions. Every change is an ordinary file change the owner can read; nothing rewrites records unseen.

### Hooks

Each is a `command` hook that exits 0 whatever happens, prints nothing when no store is set, calls no model, and logs its duration. One exception is under comparison, in [The signal](#the-signal): a small model for Spanish prompts.

| Event | Prints | Limit |
|---|---|---|
| `SessionStart` | The session index: counts of notes and memories by topic, the titles of this project's memories, the recall commands, the size of the review queue, records not pushed | Target under 1,500 characters; a cached file, the same text until a record is written or pulled; under 0.5 s |
| `SubagentStart` | Three fixed lines: the memory exists, the recall command, the project folder. The hook's input holds the subagent's type and not its brief, so the task's signal reaches a subagent through its brief (the `PreToolUse` on `Agent` row) | Under 300 characters; a cached file; under 0.5 s |
| `PreCompact` | An instruction for the summary: keep the active plan's path and any lesson not yet written | Fixed text |
| When the web researcher returns | One line to its caller: write the findings as `finding` memories | Fixed text. The event is still to be chosen: in the run tried, `PostToolUse` on `Agent` named the subagent's type but fired at launch, because the subagent ran in the background |
| `UserPromptSubmit` | A signal for the prompt's text | Under 300 characters; silent without a strong match; under 1 s; skips task notifications, which arrive through the same event |
| `PreToolUse` on `Agent` | A signal for the brief, appended to the brief through `updatedInput`, so every subagent receives it whatever its tools | The same limits; in the run tried it worked together with an allow decision |
| `PreToolUse` on the web search tool | A signal for the query | The same; whether context can be added without deciding the permission is to be tried |
| `SessionStart`, asynchronous | Nothing: pulls the global scope, fast-forward only (see Sync) | Never blocks the session |

### The signal

```
memory: 2 memories and 1 note match strongly: m:<handle> m:<handle> n:<handle>
  4 possibly related · 7 linked to those
  open one with `mem show <handle>`, or search in your own words with `mem search`
```

- **Three bands.** *Strong* and *possible* come from the ranking; *tangential* is the records linked to the strong ones, not the low-scoring ones: linked neighbours held answers in the owner's measurements, and in the one query tried the low-scoring results were unrelated. No source read shows that tangential records help the model, so this band is a count only.
- **Titles only for the strong band**, three at most: in the owner's measurements agents used the first one to three results.
- **No reference to a cached query.** The owner's reasons: the query a hook derives from a prompt is not the one the model would write, and with subagents in parallel a "last query" could be another agent's. In the run tried, the hooks of the main session and of its subagent received the same `session_id`, which supports the second reason. A reference unique to each call may be tried as a variant.
- **The bands must be calibrated before the hook ships.** Measured on the owner's store on 2026-11-17: a task with no related record still returned over a thousand matches, the first scoring 11.8, against 16.5 for the first result of a query with a real answer. In that one comparison the raw score did not separate a match from noise; the thresholds come from the evaluation set, not from this observation. Inference: a signal that is often wrong teaches the model to ignore it.
- **Language.** The owner writes prompts in Spanish and the records are in English. Measured the same day: a question asked in English returned the right records first, and the same question in Spanish returned unrelated ones. The signal for a prompt therefore needs one of three means, compared on an evaluation set with a rule written beforehand: word matching alone (expected to fail), a small local multilingual embedding, or a small model that turns the prompt into English search terms. Text the agent writes itself (briefs for subagents, web searches) is in English and needs none, so the signal for a brief can ship first.

### Sync

The global scope is a git repository. The plugin pulls at session start in the background, fast-forward only. Commit and push stay explicit and pass through the store's own check, because a pushed secret or business name cannot be recalled from other clones. When local commits are not pushed and the remote has moved, the pull fails; the session index then says the store has diverged and names the command that rebases. Which repository the global scope syncs to is decided when the plugin is finished.

### Language of the engine

Python now. Measured on 2026-11-17: 630 ms per search over about 1,060 records, of which about 120 ms is start-up; the tool keeps no index on disk. That is inside the budget of the hooks that search; the two hooks that run most print a cached file and do not search. Rust would give one binary and searches in tens of milliseconds (an estimate), at the cost of rewriting about 2,600 lines with proven parity and of distributing binaries from a repository without CI. The decision is taken again when the record model has held for two stages and the hooks' times are measured.

## Owner decisions and open choices

Decided by the owner on 2026-11-17. Round 2 replaced parts of round 1; the table states the result.

| Id | Decision |
|---|---|
| D1 | Two scopes: generic and abstract knowledge apart from project-specific memory in a hidden folder of the project |
| D2 | The plugin is the engine |
| D3 | The agent writes explicitly; no hook writes for it, though one may remind it |
| D4 | A first version reaches local Claude Code and its subagents |
| D5 | The global scope lives at a configured path, not in the plugin's data folder |
| D6 | The project folder is local by default and committed only when a project opts in |
| D7 | The note repository is not touched until the plugin is finished; the repository that syncs the global scope is chosen then. Replaces round 1's two-step move of the code and its note type for findings in that repository |
| D8 | The code is developed in this repository, on a pushed branch with a documentation branch |
| D9 | Python first; Rust decided later with measurements |
| D10 | Notes and memories are different kinds of record; a memory may live in the project scope or the global scope |
| D11 | Curation is part of the plugin: checks at writing, a review of duplicates and of similar records not linked, commands to act on them |
| D12 | Hooks signal with bands and the titles of the best matches; no reference to a cached query by default, and both forms may be tried |
| D13 | What to remember goes by its nature: personal matters and preferences to auto memory; discoveries, facts and assumptions to the plugin; the project's situation or special conditions to both |
| D16 | Post-processing is more than removing duplicates: two or more records may have to be unified into one, their content appended or rewritten, with the old ones redirecting to it |
| D17 | Conclusions may be single notes or be grouped in a synthesis: a document written by a model over related notes, with a summary and an extended version, to which those notes point |
| D18 | A source (paper, document, article) may give several conclusions, and a conclusion may rest on several sources; the store keeps both directions |
| D15 | The owner's note repository stays a research hub (its own documents and experiments). The memory's remote store is a different repository; notes and memories are transferred into it when the time comes, so the plugin needs an import |
| D14 | Only a perfect duplicate is refused at writing. Other duplicates are kept and curated in later passes, started by elapsed time or by a number of writes, possibly by a small-model subagent run beside the work |

The agent's choices, all reversible, not ruled on by the owner: the command plus skill and no MCP server; reading the note repository as a second, read-only store during development; the hook set and its caps; calibration before the signal ships; pull automatic, push explicit; auto memory left unchanged; the cached hook text; the local list of forbidden terms; the folder at the main worktree's root; the names `mem`, `.memory/`, `remember`.

An idea the owner raised without making it a requirement: a conclusion that lists the conclusions it builds on, apart from its sources, so conclusions can be composed.

Not settled: which of the three means handles Spanish prompts; whether old unconfirmed memories rank lower; the thresholds of the bands; the sync repository.

## Evidence

Status values: "Checked" means a second agent opened the page on 2026-11-17 and quoted it, at the place named; "Partly" means it found the statement only in part; "Lead" means one agent read it and nobody re-opened it; "Measured" means a measurement on the owner's store or machine, which this repository cannot show; "Tried" means one headless run on Claude Code 2.1.325 on 2026-11-17 with test hooks that logged their input and added a marker.

| Claim | Source | Status |
|---|---|---|
| Plugin hooks run inside subagents; a `SubagentStart` hook can inject context; `SessionStart` stdout is added as context | `code.claude.com/docs/en/hooks`, `…/sub-agents` | Checked |
| `UserPromptSubmit` receives the prompt's text and its context appears alongside the prompt; `SubagentStart` receives the subagent's id and type and no brief; the web search tool's input holds the query | `code.claude.com/docs/en/hooks` | Checked |
| Injected strings are capped at 10,000 characters; `PreCompact` stdout becomes instructions for the summary and is cut at the cap | Same page | Checked |
| A plugin's `bin/` is on the Bash tool's path; `userConfig` has a `directory` type and reaches hooks as an environment variable; the plugin's data folder is deleted on uninstall by default | `code.claude.com/docs/en/plugins-reference` | Checked |
| A `PreToolUse` hook can add context without deciding the permission; no documented channel passes data from one hook to another | `code.claude.com/docs/en/hooks` | Partly: an example adds context together with an allow decision; to be tried |
| A `PreToolUse` hook on the Agent tool receives the brief, and the brief it returns in `updatedInput` reaches the subagent. `SubagentStart` receives only the subagent's id and type, and its context reaches the subagent. `PostToolUse` on `Agent` names the subagent's type. The prompt hook also fires for a task notification. Every hook of the session, the subagent's included, receives one `session_id` | Test hooks | Tried |
| Auto memory is machine-local, loads the first 200 lines or 25 KB of its index and is not loaded into subagents | `code.claude.com/docs/en/memory`, `…/sub-agents` | Lead |
| Memory injection was about 12% of billed cost in multi-agent workflows on a 200-task benchmark | arXiv 2609.23790 (preprint) | Checked on the abstract |
| Injecting a matched skill lowered mean Pass@2 by 1.3% to 4.2% and raised token cost by 72% to 394% | arXiv 2608.23067 (preprint; skills, not memory) | Checked on the abstract |
| Errors in stored experiences compound in later runs | arXiv 2505.16067 | Checked on the abstract |
| In one observed case a model's rewrite of a whole context cut it from 18,282 to 122 tokens and lowered accuracy | arXiv 2510.04618 | Checked in the full text |
| Libraries of lessons raised scores over a no-memory baseline | arXiv 2308.10144, 2409.07429, 2508.06433, 2509.25140 | Leads; each is its authors' own evaluation |
| Other memory tools share a session index plus reading on demand; reported problems are stale memory, silent truncation of the index and unnoticed background rewrites | Vendor docs (some read only as search snippets) and issue reports read through a mirror | Leads |
| Answers cited the first one to three search results, agents did not ask for a second page, a 20% cut in printed text did not lower the tokens of a run, and records linked to the first results held more answers than a longer flat list | The owner's measurements, 2026-11-15 | Measured |
| Of 51 session transcripts in five other projects, three mention the search tool | Counted by file on 2026-11-17 | Measured; a mention is not a call |
| 630 ms per search; a Spanish question missed what the same question in English found; a task with no related record scored 11.8 against 16.5 for a real match | The owner's store, 2026-11-17, one query each | Measured; one query each is an observation, not a rate |

No source read measures a session-start or per-prompt memory hook in a coding agent against task success, which is why the signal is calibrated and compared before it ships.

## Change impact

Change: a new opt-in plugin in this repository. The note repository does not change. Compatibility: additive.

| Dimension | Affected | Action |
|---|---|---|
| Marketplace | `.claude-plugin/marketplace.json`, the README catalog | Add the entry and row; check that `scripts/port.py` leaves the new plugin out of the Copilot and Codex catalogs |
| Checks | `scripts/validate.py` reads only `agent-skills`; the plugin brings Python code and tests, new to this repository | Until the validator is extended, the skills' limits (N1, N2) are checked by hand and `claude plugin validate` is the only automatic check; the engine's tests run with one documented command |
| Evals | N6 measures descriptions | One trigger case per new skill when it is written; no wider suite |
| User-level rules | The owner's text about the note repository; `user-config/routing.md` rows on research | Shrink the first; a routing row only if the kill read shows the index is not enough (ADR 0021) |
| Requirements and ADR 0011 | The Repo role row and the marketplace description name one plugin plus mods; the Runtime row names cloud; G3 (work survives a compaction) gains a second means | Update both on acceptance; add rows for the plugin; note that it is local only |
| Copied code | The engine starts as a copy of a private tool | The copy carries no note text, paths or names from the private repository; checked before the first push |
| Each project | `.memory/`, `.git/info/exclude` | Written on first use, never the project's ignore file |
| Cost | A session index per session, three lines per subagent, a signal when records match | Caps above; measured in the stage that adds each |

| Risk | Rating | Mitigation |
|---|---|---|
| A business name reaches the global scope from a work repository | high | Writing defaults to the project scope outside the store; global writes are explicit and checked against a local list of forbidden terms; `promote` drafts and never copies; no automatic push. The list holds only names already known, so the agent remains the check |
| Agents do not call the command despite the index | high | The web researcher has no Bash tool, so the index tells its caller to recall first and carry the result in the brief; calls are counted in the plugin's usage log; a kill criterion in the plan |
| The signal is wrong often enough to be ignored, or silent for Spanish prompts | high | Calibrated on an evaluation set with a rule written beforehand; silent without a strong match; the three means for Spanish compared before one is chosen |
| A memory is read as a fact | medium | Every result prints "memory" or "note"; refuted memories are hidden; findings expire |
| Records pile up uncurated | medium | The check at writing; the queue's size in the session index; a kill criterion |
| A hook fails, hangs or slows every subagent start | medium | Exit 0 always, cached files for the two hooks that run most, durations logged |
| The hooks change this repository's eval figures (G8) | medium | One eval case run with the plugin enabled and disabled; eval runs disable it if they differ |
| The memory, auto memory and context files give different instructions | medium | The "what goes where" table is the only statement; the owner's user-level text is cut to it |
| Text from the web or from a shared project folder carries instructions into later sessions | medium | Records are data; hooks print titles and counts, not bodies; a committed project folder is trusted like the repository's own context file |
| The copied code diverges from the original tool | low | Accepted by D7; a parity test fixes the copy's search results at the start |

Point of no return: none in the plugin. Committing a project folder to a shared repository is the one step that history keeps, and it is opt-in per project.
