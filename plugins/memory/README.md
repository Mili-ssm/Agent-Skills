# memory

Notes and memories reachable from every repository and subagent: the `mem` command searches and reads a configured store.
Stage 1 of ADR 0023 (proposed); see the [plan](../../docs/superpowers/plans/2026-11-17-memory-plugin-stage-1.md).

## Install

`/plugin install memory --marketplace Mili-ssm/Agent-Skills`

## Requirements

[`uv`](https://docs.astral.sh/uv/) on the path. Without it `mem` exits 127.

## Setting the store

| Way | Notes |
|---|---|
| Plugin option `store` | Set at install; takes effect in the next session. A `SessionStart` hook exports `MEM_STORE` to shell commands and writes `$XDG_CONFIG_HOME/agent-memory/store` |
| `MEM_STORE` environment variable | Overrides the config file |
| `--root` | Per call |

Stage 1 is read-only: `new`, `rename`, `index` and `fetch-sources` refuse to run unless `MEM_ALLOW_WRITE=1`.

## Use

`mem --help` lists the commands.

## Tests

```sh
uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q
```
