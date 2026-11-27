"""Infrastructure of the background jobs: config, safe writes, the `claude -p` launcher, job lifecycle and state.

`auto_state`: `mem-auto` state, run lock, failure line
`config`: store resolution for every entry point
`headless`: spec and runner of `claude -p` sessions
`runner`: the `claude` or `codex` runner of a pass: resolution, Codex argv and environment, one `Outcome`
`codex_pass`: one Codex session of a pass in the shape the builders read, the token cap, the refusal text
`jobs`: generic job pieces: status and lock files, run lock, private JSON
`safe_io`: writes into memory folders that never follow a symlink
`store_git`: a store that is a git repository: commits at curation points
`yaml_load`: the engine's YAML parser and plain `safe_load`

Imports stdlib and `core` only.
"""
