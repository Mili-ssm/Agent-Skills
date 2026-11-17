# memory

Notes and memories reachable from every repository and subagent, through the `mem` command.
Stages 1 and 2 of ADR 0023 (proposed); see the [stage plan](../../docs/superpowers/plans/2026-11-17-memory-plugin.md).

## Install

`/plugin install memory --marketplace Mili-ssm/Agent-Skills`

## Requirements

[`uv`](https://docs.astral.sh/uv/) on the path. Without it `mem` exits 127.

## Two kinds of record, two scopes

| | Note | Memory |
|---|---|---|
| What | A general statement with its source | Something seen or decided once, in a context: experience, not fact |
| Where | The store | The project's `.memory/` folder by default; a global folder with `--global` |
| Written with | `mem new` | `mem remember`, `mem observe` |

`mem search` prints matching memories first, labelled `[memory: …]`, then notes.

## Folders and how they are set

| Folder | Set by | Notes |
|---|---|---|
| Store (notes) | Plugin option `store`, or `MEM_STORE`, or `--root` | Read-only unless it holds a `mem-store.yaml` marker; `mem init <folder>` creates a new store with one. An existing store without the marker is never made writable by this tool |
| Global memories | Plugin option `memories`, or `MEM_MEMORIES`; else `memories/` in a writable store | May not be inside a read-only store. Writing needs the file `$XDG_CONFIG_HOME/agent-memory/forbidden-terms` (one term per line; it may be empty): a text that contains a term is refused |
| Project memories | The main worktree's `.memory/` | Kept out of git through `.git/info/exclude`, added once when the folder is created; remove that line to commit the folder |

Plugin options take effect in the next session: a `SessionStart` hook exports them to shell commands and writes them under `$XDG_CONFIG_HOME/agent-memory/`.

## Use

`mem --help` lists the commands; the `memory` skill holds the recall and writing recipes.

## Tests

```sh
uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q
```
