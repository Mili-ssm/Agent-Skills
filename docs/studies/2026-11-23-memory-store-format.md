# Memory store format: Markdown files, SQLite or another portable format

Status: suggestion documented, investigation done, no change proposed now · Date: 2026-11-23

The owner's question (2026-11-23): would a portable, efficient format (SQLite was the first example) serve the `mem` store better than one Markdown file with YAML frontmatter per record? It should travel in git as files, make the data easier to reach, and ease imports, exports and moving old data to newer versions. A second side: a database forces agents through `mem` commands, while files also let them list and read directly; would that help or hurt? Implementation, if ever worth it, is for later.

## Conclusion

Keep one Markdown file per record as the source of truth. With one JSON file per record it is one of the two options that keep readable diffs and file-level merges between git clones, and it is the one that needs no migration of the existing store and keeps note bodies readable as prose; agents and people can still list and grep. The real gaps are elsewhere, and each has a file-friendly fix:

| Need | Today | Proposal |
|---|---|---|
| Speed | Python start-up and YAML parsing are the costs of search and the session start ([Rust study](2026-11-23-memory-rust-port.md)) | a **derived index** (SQLite FTS5 or a JSON cache), git-ignored, rebuilt from the files when stale |
| Moving old data to newer versions | the store declares `format: 1` in `mem-store.yaml`; records carry no format version field (a memory's `versions` list is its wording history); new fields rely on tolerant reading; no migrate command | a format version (major/minor, as Jupyter's `nbformat`), a reader that upgrades on read, and a one-shot `mem migrate` that rewrites records and bumps the version |
| Import and export | `mem import` copies a folder of notes; no export | `mem export` and `mem import --jsonl` in JSON Lines (one record per line with its fields and body): backups, moving stores between tools, feeding a port |
| Logs | already append-only files | JSON Lines for append-only data only; with `merge=union` in `.gitattributes` if a log is ever tracked |

## How agents reach the store today (measured)

Claude Code transcripts of the last three days (2026-11-21 to 11-23), all projects, 15 main sessions and 403 subagent transcripts, this session excluded; each tool call counted once by its id; [script](scripts/store_access.py) (`python3 -I docs/studies/scripts/store_access.py 3 <session id to exclude>`), aggregate counts only.

| Access | Calls |
|---|---|
| `mem` commands (all subcommands) | 672 (main 322, subagents 350) |
| of which `mem search`, `show`, `memories` and `rules` | 546 |
| Direct reads of note bodies in the store (`literature/`, `knowledge/`, `syntheses/`) | 0 |
| Direct shell reads of the store's global `memories/` | 12 |
| Direct shell reads of project `.memory/` folders | 76; the 72 by subagents came from `implementer`, `skeptical-reviewer` and `pre-mortem` agents (classified by agent type) in sessions developing or reviewing the plugin itself; that they served development, not recall, is inferred from those sessions' tasks |
| Listings (`ls`, `find`, `Glob`) of any memory folder | 1 |
| Claude Code's own auto memory (`~/.claude/projects/*/memory/`, outside the store) | 51 reads, 25 writes: that system is file-based by design and works as documented |

The premise that agents tend to read the store's files by hand does not hold for this period: recall goes through the CLI, so forcing it through a database would change little. One period of three days on one machine; the measurement is cheap to repeat.

## Options compared

| Option | Diffs and merges in git | Full scan of about 1,600 files | Several local processes | Dependencies | Agents can list and grep |
|---|---|---|---|---|---|
| One Markdown/YAML file per record (current) | readable; merges per file, so clones rarely conflict | fine; YAML parsing is the cost, cut by the C loader | safe with atomic writes | `pyyaml` | yes |
| One JSON file per record with a version | same as current | faster parse (stdlib `json`); bodies less readable | same as current | stdlib | yes |
| JSON Lines, one file per collection | readable, but concurrent appends conflict unless `merge=union`, which may reorder lines | fast | one writer per file | stdlib | yes |
| SQLite as the store | binary: merges operate on the whole file | fast, with FTS5's built-in `bm25()` ranking | one writer; WAL is same-host only | stdlib `sqlite3` | no (SQL only) |
| Text dump plus rebuild (`sqlite-diffable`: one JSON metadata file and one NDJSON file per table) | readable | fast once rebuilt; the database is git-ignored and rebuilt per clone | as SQLite | stdlib | the dump, not the database |
| Dolt (git-like SQL database) | versioned inside its own format and remote (branch, merge, push like git); not text in plain git | fast | a server or CLI | a Go binary | no |
| DuckDB with Parquet or CSV export | Parquet is binary | fast for analysis | single process | large | no |

Sources: [JSON Lines](https://jsonlines.org/); [git `merge=union`](https://git-scm.com/docs/gitattributes) (lines "may end up in random order"); [SQLite FTS5](https://www.sqlite.org/fts5.html) and [WAL](https://www.sqlite.org/wal.html); [sqlite-diffable](https://github.com/simonw/sqlite-diffable); [sqldiff](https://www.sqlite.org/sqldiff.html) (a diff tool, "not designed to support schema migrations"); [Dolt](https://www.dolthub.com/docs/introduction/what-is-dolt). Performance and concurrency cells are reasoned from the docs, not measured here.

## Versioning and migration practice

| Tool | How it moves old data forward |
|---|---|
| Jupyter [`nbformat`](https://github.com/jupyter/nbformat/blob/5.7.0/docs/format_description.rst) | `nbformat` (major) and `nbformat_minor`: compatible changes bump the minor, breaking ones the major; `read(..., as_version=4)` upgrades on read |
| [Taskwarrior 3](https://taskwarrior.org/docs/upgrade-3/) | moved from text files to SQLite; old data needs an explicit `import-v2` step with hooks off: a format change to a database cost every user a migration |
| [Obsidian properties](https://obsidian.md/help/properties) | YAML frontmatter with typed properties; a property's type is shared by every note using that name; no version field |

For the store this suggests: a format major/minor in `mem-store.yaml` (today `format: 1`), a converter that reads older versions, and a `mem migrate` that rewrites once; per-record versions only if records of several formats must coexist (for example after importing an old export).

## What vendors and other memory systems do

| Source | What it says | Kind |
|---|---|---|
| [Claude Code memory](https://code.claude.com/docs/en/memory) | auto memory is plain Markdown: an index loaded at start, topic files read on demand with the normal file tools | recommended (rank 1) |
| [Claude memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) | the model sees a `/memories` file interface; the application may back it with a directory "or keys in a database" | recommended (rank 1) |
| [Effective context engineering](https://anthropic.com/engineering/effective-context-engineering-for-ai-agents) | agents keep "lightweight identifiers (file paths…)" and use glob and grep "just-in-time" | recommended (rank 1) |
| [Codex memories](https://learn.chatgpt.com/docs/customization/memories) | memories are generated files; rules belong in `AGENTS.md` | recommended (rank 1) |
| [Letta MemFS](https://docs.letta.com/letta-code/memfs) | each memory a Markdown file with YAML frontmatter in a per-agent git repository, every edit committed | design choice (rank 1) |
| [Letta benchmark](https://www.letta.com/blog/benchmarking-ai-agent-memory) | an agent with file tools over LoCoMo scored 74.0% against 68.5% reported for a database-backed memory; vendor-run, no token counts | measured, medium |
| [arXiv 2604.01707](https://arxiv.org/html/2604.01707v2) | tool-managed memories show more tool-call failures and indexing conflicts as context grows | measured, medium |

No head-to-head measurement of files against a database for agent memory was found, nor any study of forcing agents through commands instead of file access.

## If it is ever built

1. Derived index: `mem` builds a git-ignored index file from the records, checks staleness by modification time and size, rebuilds what changed, and falls back to parsing files when the index is missing; writes keep going to the files through `mem`. Measure against the numbers in the [Rust study](2026-11-23-memory-rust-port.md) before adopting.
2. Versioning: `format` major/minor in `mem-store.yaml`, an upgrade-on-read converter, `mem migrate` with a dry run, and a test fixture per older format.
3. Export and import in JSON Lines, round-trip tested (export then import gives byte-identical records).

## Size, deltas and merges (owner's points, 2026-11-23; for later)

Measured on the real store the same day (1,583 Markdown files, 33 history commits, `.sources/` excluded):

| Form | Size |
|---|---|
| Working tree | 27 MB |
| The same files as `tar.gz` | 6.9 MB |
| `.git` today (1,867 loose objects, never packed) | 9.3 MB |
| The whole history packed by git (`pack-objects`, deltas and zlib; measured without changing the repository) | 3.4 MB |

- **Deltas and compression already come with git for text:** every commit since the import fits in 3.4 MB once packed, about an eighth of the working tree. A binary database gets worse deltas, because small edits move pages around. The cheap gain is to let git pack the store (`git gc --auto` after history commits, or on a schedule), not to change format.
- **Merging through deltas before a pull (owner's idea):** fetch the remote, merge record by record against the common ancestor, commit, then push. Git supports exactly this as a custom merge driver (`.gitattributes` `merge=<driver>`, given base, ours and theirs), and the sync of stage 7 would run fetch, merge and push in that order. With one file per record git already merges per record on its own, so the driver only earns its cost if a single-file format is chosen for other reasons; with a database it would need a record-level three-way merge and a conflict policy (newest wins, keep both, or ask).
- **For the stage 7 sync:** pull before push, a merge driver only for files that are not per-record (`topics.yaml`, indexes), and periodic packing.

## Revisit when

The derived index is built and a hook stays over its budget; the store's packed history grows past what a git host handles comfortably; a record change can no longer be handled by tolerant reading; or a later transcript measurement shows agents reading or listing the store's files directly during ordinary work.
