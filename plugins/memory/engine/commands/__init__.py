"""The `mem` command handlers (A5, ADR 0028), a top layer like `entry`: it may import every package and only `mem` imports it.

Modules (the plan, docs/superpowers/plans/2026-11-26-memory-mem-split.md, adds one line per module as the handlers move here):

`common`: helpers shared by the handlers and the dispatch (store resolution, logs, note resolution, guards, `UsageError`)
`admin`: `terms`, `projects`, `init`, `history`
`read`: `check`, `index`, `find`, `topics`, `show`, `search`, `passages`, `related`, `search-eval`, `stats`, `review`
`edit`: `new`, `note` (edit and marks), `rename`, `unify`; `new_note` and the attach-to-section helpers
`sources`: `fetch-sources` and `import`; download, HTML and PDF text extraction, and the store import
`memory`: `remember`, `confirm` (and `observe`), `refute`, `forget`, `triage`, `supersede`, `merge`, `distinct`, `restore`, `promote`, `memories`, `rules`, `memory` (edit) and `settle`
`curate`: `curate`, and the session-start curation decisions (passes, marks, pair and note queues)
`hooks`: `session-index`, `compact-log` and `signal`, with the session start text and the logic only they use
"""
