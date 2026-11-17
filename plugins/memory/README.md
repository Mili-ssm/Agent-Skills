# memory

Notes and memories reachable from every repository and subagent, through the `mem` command.
ADR 0023; see the [stage plan](../../docs/superpowers/plans/2026-11-17-memory-plugin.md).

## Install

`/plugin install memory --marketplace Mili-ssm/Agent-Skills`

## Requirements

[`uv`](https://docs.astral.sh/uv/) on the path. Without it `mem` exits 127.

## Two kinds of record, two scopes

| | Note | Memory |
|---|---|---|
| What | A general statement with its source | Something seen or decided once, in a context: experience, not fact |
| Where | The store | The project's `.memory/` folder by default; a global folder with `--global` |
| Written with | `mem new` (a paper or other source is a `literature` note with its `--url`; `mem fetch-sources` keeps a local copy outside git and `mem passages` reads it) | `mem remember`, `mem observe` (kinds: decision, constraint, pitfall, lesson, finding, document, state) |

`mem search` prints matching memories first, labelled `[memory: …]`, then notes.

## Folders and how they are set

| Folder | Set by | Notes |
|---|---|---|
| Store (notes) | Nothing to set: the default store is created on first use (`mem init`). Or the plugin option `store`, `MEM_STORE`, `--root` | A store is read-only unless it holds a `mem-store.yaml` marker; the default one has it. An existing folder of notes without the marker is never made writable by this tool. To sync, make the store a git repository and push it to a remote of your choice |
| Global memories | Plugin option `memories`, or `MEM_MEMORIES`; else `memories/` in a writable store | May not be inside a read-only store. Nothing specific to a project belongs here. `mem terms add <term>` lists a hard term (a write that contains it is refused); `mem terms add <term> --soft` lists a soft one (the agent must ask the owner); `mem terms list` and `remove` manage them |
| Other projects | A local registry, filled as memories are written (`mem projects list`) | Never read by default. `mem search "<q>" --project <name>` or `--all-projects` includes them, each under its own header; the registry holds names and paths, stays on this machine and is not synced |
| Project memories | The main worktree's `.memory/` | Kept out of git through `.git/info/exclude`, added once when the folder is created; remove that line to commit the folder |

## Bringing in existing notes

`mem import <folder> [--dry-run] [--overwrite] [--with-sources] [--research-data]` copies the `literature/` and `knowledge/` files, the Markdown files and figures of `research/` (its data and code only with `--research-data`) and the topics of an older folder of notes into the store, reading the source only. Files that differ stay as they are and are listed, unless `--overwrite`; imported text is not checked for secrets or terms, only reported.

Plugin options take effect in the next session: a `SessionStart` hook exports them to shell commands and writes them under `$XDG_CONFIG_HOME/agent-memory/`.

## Syntheses

A synthesis is the long version behind a group of notes: one indexed document per subject with origins, reasons, and when a thing applies and when not. `mem synthesis new|add|append|edit|attach|list` build it one cited part at a time; `rename`, `remove` and `detach` change a part or a note's link, and `topics` sets the synthesis's topics (`mem restore s:<handle>` undoes a step); a note says which part it recalls (`part of:`), and `mem search` prints matching parts after the notes. Notes are written loose; a curation pass (`mem curate --notes`) joins them to a synthesis, lists notes to unify (`mem unify`) and topics that have enough notes for one. The `memory-synthesis` skill holds the procedure.

A project can also keep stamped syntheses in `.memory/syntheses/` (`organization`, `plans`, `pending`, `conventions`): each `## ` part ends with the files it covers and the commit it was written at. `mem project-synthesis add <name> "<heading>" --paths a,b --body-file F` writes or replaces a part, `confirm p:<name>#<handle>` re-stamps it after you checked it, `list` shows each part's freshness, and `mem show p:<name>[#<handle>]` reads it, marking a part whose files changed since as possibly stale. They need no store and never write to one.

## Subagents

They keep the main conversation's context on the task.

| Subagent | Given | Does | Returns |
|---|---|---|---|
| `memory-researcher` (Sonnet) | A question | Answers from the memory, deeper sources if needed, outside research only for what is missing, which it records as findings | Conclusions with their references, and what is new and unchecked |
| `memory-recorder` (Sonnet) | An account of what happened, or logs and files | Writes the few memories worth keeping, each in its scope; optionally lists the curation queue | What it recorded |
| `memory-curator` (Haiku) | Nothing | Reads the curation queue | A table of proposed actions; it applies none |

The start text every other subagent receives is not given to these three: they carry their own instructions.

## Curation

`mem curate` lists what needs a decision (memories that say the same or the opposite, expired ones, ones seen several times, ones nobody confirmed); `mem merge`, `refute`, `distinct`, `supersede`, `forget`, `confirm` and `promote` carry a decision out, and `mem restore` undoes the last one on a memory. Records change only through commands, never by editing files: `mem note edit` corrects a note (claim, topics or one section) and `mem memory edit` a memory (`mem restore` a retired one first). Nothing is deleted. The session start text says when a pass is due; the `memory-curation` skill holds the procedure and the `memory-curator` subagent proposes actions without applying them.

## History

A store can keep a git history of its own: `mem history init` makes it a local repository (its `.gitignore` keeps out the `.curation-log` files, `.sources/` downloads, `research/*/data/` and files over 5 MB). `mem` commits at three points only, never per command and never through an agent: when a curation pass ends (`mem curate --done`), at session end (a `SessionEnd` hook, bounded to 5 seconds), and on `mem history commit [-m TEXT]`. `mem history` lists the commits. After `curate --done` commits, curation-log entries older than 30 days are trimmed inside the store (never in a project's `.memory/`, never in a store without git). `mem restore` stays the undo for recent changes; for older ones, git holds the state at each commit point, and states between two commit points older than 30 days are not kept. A remote for backup comes later.

## Use

`mem --help` lists the commands; the `memory` skill holds the recall and writing recipes.

## Tests

```sh
uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q
```

Routing trials (nine headless sessions that cost model usage; they check that each kind of thing to remember lands in the right place, and that a client's name never reaches the store):

```sh
python3 plugins/memory/evals/routing/run_trials.py --claude "$(command -v claude)"
```

Trials keep everything under the ignored `target/` folder at the repository root: their config, data, stores and work folders, so they never read or write a real store or global memories (inherited `MEM_*` and `CLAUDE_PLUGIN_OPTION_*` variables are dropped), and `PATH` entries of an installed copy of a plugin (under `/plugins/cache/`) are dropped so sessions run the `mem` under test. A work folder is kept when a run fails, for inspection. To check the isolation without a model session:

```sh
python3 plugins/memory/evals/routing/run_trials.py --self-check
python3 plugins/memory/evals/recall/run_trials.py --self-check
```
