# 0023 A memory plugin makes a note store reachable from every repository

Status: proposed · Date: 2026-11-17

## Context

The owner keeps a private repository of Markdown notes (conclusions, lessons, summaries of sources, investigations) with a one-file search tool. On 2026-11-17 the owner said it "practically only works if I work from here" (translated): sessions in other repositories and every subagent do not use it, nothing learned in a work repository is kept in a searchable place, and web research is discarded with the session. The owner asked for a plugin that makes this memory available everywhere, serves as working memory, and syncs through a private git repository; hooks that add context, perhaps chosen by a small model, were raised as an idea, not a requirement.

Evidence and the options considered are in the [design](../superpowers/specs/2026-11-17-memory-plugin-design.md). Assumptions: the owner is the only user (ADR 0008); `uv` is installed on the owner's machines; the product behaviors the design relies on were read in the product docs on 2026-11-17 (its evidence table says which were checked twice, which once, and the one still to be tried) and may change.

## Decision

Add an opt-in plugin, `memory`, beside `agent-skills` (ADR 0011). The owner decided on 2026-11-17:

- **Two scopes.** The *global scope* holds generic, abstract knowledge at a folder path set when the plugin is enabled (for the owner, the note repository; its git remote is the private repository that syncs it). The *project scope* is a hidden folder at each project's root for what is specific to that project, including business constraints that must not reach the global scope.
- **The project folder is local by default**; a project opts in to committing it.
- **The plugin is the engine and the note repository its first store**, reached in two steps: first the plugin's command runs the store's own search tool; the code moves into the plugin once the store's rules are read from a configuration file.
- **The agent writes to the memory explicitly**; no hook writes for it, though one may remind it. Capture by a small model is at most a later, measured experiment.
- **Leads** (unverified findings from web research, with URL, date and expiry) become a note type of the store.
- **A first version reaches Claude Code on the owner's machines and its subagents**; cloud sessions and the Copilot and Codex ports (ADR 0015) are outside it.

Proposed with this record and not ruled on by the owner (the design lists them): a command plus one skill and no MCP server; hooks that print short fixed text and call no model; pull automatic, commit and push explicit; Claude Code's own auto memory left as it is.

## Alternatives

| Option | Rejected because |
|---|---|
| Keep the rule in the owner's user-level file ("consult the note repository") | It is what exists: by the owner's account sessions elsewhere do not use the notes, and a subagent gets only its brief |
| Point Claude Code's auto memory at a synced folder (`autoMemoryDirectory`) | The docs do not say whether one folder serves every project; auto memory has no search across projects and, as read once in the docs, is not loaded into subagents |
| An existing memory plugin that captures sessions through hooks into a database | Automatic capture is what the owner declined; the one such plugin read keeps its records in a database, not in Markdown under git |
| An MCP server | A process to keep running and a second interface; its gains (no Bash call, per-tool permissions) do not reach a subagent with a fixed tool list; revisit below |
| Injecting memory on every prompt, or choosing it with a small model | No source read measures it against task success; two 2026 preprints report the cost of injected memory and lower pass rates from injected skills |
| The plugin's own data folder for the global scope | The docs say it is deleted on uninstall by default |
| Moving the search tool's code into this repository now | Every search experiment would touch two repositories, and changes here are meant to be low-risk |

## Consequences

- First command hooks, first `bin/` executable and first `userConfig` in this marketplace; `scripts/validate.py` and the ports do not cover the new plugin until extended.
- Existing installs do not change: the plugin is opt-in and adds nothing to `agent-skills` (G8).
- The owner's user-level text about the note repository shrinks to what the plugin's skill does not say, so one instruction covers one task.
- Each session pays for a session index and each subagent for three lines (caps in the design).
- The marketplace gains a plugin that is neither `agent-skills` nor a mod: on acceptance, ADR 0011's description of the marketplace and the Repo role row of `docs/requirements.md` are updated.
- The note repository gains a note type, new fields and a project scope; each change to what its search prints goes through that repository's own measured comparison.
- Ships unmeasured; the kill criteria are in the [plan](../superpowers/plans/2026-11-17-memory-plugin.md).

## Revisit if

- A kill criterion of the plan fires.
- A subagent without the Bash tool needs to search the memory itself, or the command still prompts for permission in subagents after the allow rule is set: reconsider an MCP server.
- The owner wants the memory in cloud sessions, Copilot or Codex.
- Claude Code documents a way for a plugin to supply or sync auto memory.
