"""The `mem` command handlers (A5, ADR 0028), a top layer like `entry`: it may import every package and only `mem` imports it.

Modules:

`common`: helpers shared by the handlers and the dispatch (store resolution, logs, note resolution, guards, `UsageError`)
`admin`: `terms`, `projects`, `init`, `history`
`read`: `check`, `index`, `find`, `topics`, `show`, `search`, `passages`, `related`, `search-eval`, `stats`, `review`
`edit`: `new`, `note` (edit and marks), `rename`, `unify`; `new_note` and the attach-to-section helpers
`import_recovery`: write-ahead rollback journal for interrupted imports
`sources`: `fetch-sources` and `import`; download, HTML and PDF text extraction, and the store import
`memory`: `remember`, `confirm` (and `observe`), `refute`, `forget`, `triage`, `supersede`, `merge`, `distinct`, `restore`, `promote`, `memories`, `rules`, `memory` (edit) and `settle`
`curate`: `curate`, and the session-start curation decisions (passes, marks, pair and note queues)
`hooks`: `session-index`, `compact-log` and `signal`, with the session start text and the logic only they use
`diagnostics`: read-only report of local plugin, store, roles and hooks
`install`: `install-command`, which puts a `mem` launcher on PATH, and the plugin-root record the launcher follows
`synthesis`: `synthesis` (list, new, add, append, edit, attach, rename, remove, detach, topics, refs) and `project-synthesis`, with the logic only they use
`split`: CLI for split proposals, preview, apply, status, recovery and undo
`split_plan`: read-only synthesis split proposals and previews
`split_transaction`: recoverable split groups and exact undo
`integrate`: `synthesis integrate`, which joins knowledge notes to parts of a synthesis (registered by `mem`, not by the synthesis dispatch, because it imports `synthesis`)
"""
