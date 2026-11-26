"""The `mem` command handlers (A5, ADR 0028), a top layer like `entry`: it may import every package and only `mem` imports it.

Modules (the plan, docs/superpowers/plans/2026-11-26-memory-mem-split.md, adds one line per module as the handlers move here):

`common`: helpers shared by the handlers and the dispatch (store resolution, logs, note resolution, guards, `UsageError`)
`admin`: `terms`, `projects`, `init`, `history`
`read`: `check`, `index`, `find`, `topics`, `show`, `search`, `passages`, `related`, `search-eval`, `stats`, `review`
"""
