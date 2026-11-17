# 0023 A memory plugin makes notes and memories reachable from every repository

Status: accepted · Date: 2026-11-17

## Context

The owner keeps a private repository of Markdown notes (conclusions, lessons, summaries of sources, investigations) with a one-file search tool. On 2026-11-17 the owner said it "practically only works if I work from here" (translated): sessions in other repositories and every subagent do not use it, nothing learned in a work repository is kept in a searchable place, and web research is discarded with the session. The owner asked for a plugin that makes this memory available everywhere, serves as working memory, and syncs through a private git repository.

Evidence, measurements and the options considered are in the [design](../superpowers/specs/2026-11-17-memory-plugin-design.md). Assumptions: the owner is the only user (ADR 0008); `uv` is installed on the owner's machines; the product behaviors the design relies on were read in the product docs on 2026-11-17 (its evidence table says which were checked twice, which once, and which are still to be tried) and may change.

## Decision

Add an opt-in plugin, `memory`, beside `agent-skills` (ADR 0011). The owner decided on 2026-11-17, in two rounds; where the second round changed the first, only the result is stated:

- **Two kinds of record.** A *note* is generic and abstract. A *memory* is specific, comes from experience and carries doubt because it is not an established fact. Memories can be confirmed, refuted, merged and promoted to notes.
- **Two scopes.** The *global scope* holds notes, and memories that do not depend on one project, with no business names. The *project scope* is a hidden folder at each project's root, local by default and committed only when a project opts in.
- **The owner's note repository is not touched until the plugin is finished.** The plugin starts with its own copy of the search tool's code and its own store; which repository syncs the global scope (the note repository or another) is decided at the end.
- **The code is developed in this repository**, on a branch that is pushed, with a documentation branch.
- **Python first.** A move to Rust is decided later, with measured latencies.
- **The agent writes to the memory explicitly**; no hook writes for it, though one may remind it.
- **Hooks signal, they do not inject.** A hook that finds records related to the task prints counts in bands (strong, possible, tangential) and the titles of the best few, so the model decides what to open and writes its own search. No reference to a cached query by default; a per-call reference may be tried.
- **Curation is part of the plugin**: a check when a record is written, a review queue for duplicates and for similar records that are not linked, and commands to merge, supersede, promote and forget.
- **A first version reaches Claude Code on the owner's machines and its subagents**; cloud sessions and the Copilot and Codex ports (ADR 0015) are outside it.

Proposed with this record and not ruled on by the owner (the design lists them): a command plus one skill and no MCP server; reading the note repository as a read-only source during development; the signal bands calibrated on an evaluation set before the hook ships; pull automatic, commit and push explicit; Claude Code's own auto memory left as it is.

## Alternatives

| Option | Rejected because |
|---|---|
| Keep the rule in the owner's user-level file ("consult the note repository") | It is what exists: by the owner's account sessions elsewhere do not use the notes, and a subagent gets only its brief |
| Point Claude Code's auto memory at a synced folder (`autoMemoryDirectory`) | The docs do not say whether one folder serves every project; as read once in the docs, auto memory is kept per repository and is not loaded into subagents |
| An existing memory plugin that captures sessions through hooks into a database | Automatic capture is what the owner declined; the one such plugin read keeps its records in a database, not in Markdown under git |
| An MCP server | A process to keep running and a second interface; its gains (no Bash call, per-tool permissions) do not reach a subagent with a fixed tool list; revisit below |
| Hooks that inject the related records themselves | No source read measures it against task success; two 2026 preprints report the cost of injected memory and lower pass rates from injected skills. The owner chose a signal instead |
| Extending the note repository's own tool in place | The owner wants that repository untouched until the plugin is finished |
| Rust from the start | The record model and the hooks are still changing, which is when a rewrite costs most; this repository has no CI to build binaries. Measured on 2026-11-17: 630 ms per search in Python, enough to try the design |

## Consequences

- First command hooks, first `bin/` executable and first `userConfig` in this marketplace; `scripts/validate.py` and the ports do not cover the new plugin until extended.
- Existing installs do not change: the plugin is opt-in and adds nothing to `agent-skills` (G8).
- The plugin carries a copy of the search tool's code that will diverge from the original; the note repository adopts the plugin's version, or stays as it is, when the plugin is finished.
- The owner's user-level text about the note repository shrinks to what the plugin's skill does not say, so one instruction covers one task.
- Each session pays for a session index, each subagent for three lines, and a signal only when records match (caps in the design).
- The marketplace gains a plugin that is neither `agent-skills` nor a mod: on acceptance, ADR 0011's description of the marketplace and the Repo role row of `docs/requirements.md` are updated.
- Ships unmeasured; the kill criteria are in the [plan](../superpowers/plans/2026-11-17-memory-plugin.md).

## Revisit if

- A kill criterion of the plan fires.
- A subagent without the Bash tool needs to search the memory itself, or the command still prompts for permission in subagents after the allow rule is set: reconsider an MCP server.
- A hook's measured time stays over its budget after the engine keeps a search index on disk: reconsider Rust, for the hooks alone or for the engine.
- The owner wants the memory in cloud sessions, Copilot or Codex.
- Claude Code documents a way for a plugin to supply or sync auto memory.

## Review 2026-11-17

Accepted by the owner the same day, by asking for the branch to be merged and the plugin installed for a trial. Between the proposal and the merge the owner ruled further, and stages 1 to 3, 5, 5b and 6 were built; the decisions table of the [design](../superpowers/specs/2026-11-17-memory-plugin-design.md) (D1 to D23) is the current statement, and where it differs from the Decision above, it wins. The differences:

- The store is the default one, created on first use; the owner's note repository stays a research hub, and its notes are transferred later (D15, D23). Git is for pushing the default store to a remote the owner chooses.
- The standard search returns notes and memories; papers, documents and syntheses are an explicit, deeper search. Writing while working is a note or a memory; everything complex belongs to curation and to subagents (D21, D22).
- Syntheses were added: long documents written by a model over many notes (D17, D19).
- The signal hook was built and measured, showed no gain, and is not registered; what made agents consult the memory was a short start text that states its reason.
- Terms that must not reach the global scope are of two classes: hard ones block, soft ones make the agent ask the owner (D23).

Measured, with one or two runs per case on a Sonnet-class model, which the owner takes as a sufficient reference: routing 9 of 9, recall 8 of 8, delegated recall 9 of 9. No measurement shows that the plugin makes tasks come out better; the field research found none for comparable systems either. The kill criteria of the [plan](../superpowers/plans/2026-11-17-memory-plugin.md) are read after two weeks of use.

