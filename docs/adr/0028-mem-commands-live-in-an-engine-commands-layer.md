# 0028 The mem commands live in an engine/commands/ layer; mem.py keeps the parser

Status: accepted · Date: 2026-11-26

## Context

- `engine/mem.py` has 10,502 lines, 697 top-level symbols and 42 `cmd_*` handlers; handlers sit far from their logic (`cmd_search` near the parser, its `rank` 8,700 lines above). It took 174 commits in nine days (architect measurement 2026-11-26).
- Refactor plan A5 ([plan](../superpowers/plans/2026-11-23-memory-refactor.md) item "Split the rest of `mem.py`"): one feature per pull request, handlers move with their logic, `mem.py` stays the facade and the parser, a line ceiling on `mem.py`.
- ADR 0034 layers: `core → memories → syntheses → notes` import no feature package; `FROZEN_EDGES` only shrinks; no package imports `mem`. The command clusters import up to five feature packages (memory lifecycle: `corroborate`, `digest`, `settle`; hooks: `capture`, `session`, `settle`), so no existing package can hold them.
- Handlers call `build_parser().error` at ten sites: moved as they are, they would import `mem` back.
- Start-up is not binding: `import mem` costs 79–95 ms; the hooks wrap `mem` in `timeout 3`/`timeout 4`.

## Decision

Create `engine/commands/` (`common`, `admin`, `read`, `edit`, `sources`, `synthesis`, `memory`, `curate`, `hooks`), each module holding its `cmd_*` handlers with their logic; pure search goes to `notes/search.py`. `commands` is a top layer like `entry`: it may import every package, only `mem` imports it. `mem.py` keeps the parser, the dispatch and `_MOVED` (a name → defining module map for names tests read as `mem.X`), imports the command modules eagerly except `sources` (a local static import: `http.client` and `html.parser` cost about 18 ms on every hook run). Handlers raise `UsageError`; the dispatch turns it into `parser.error`, so the message and exit code 2 stay identical. Tests patch the defining module (or use `patch_all`), never `mem`. Owner rulings 2026-11-26: the parser stays in `mem.py`; `admin` stays apart from `common`; the `settle` commands live in `commands/memory.py`.

## Alternatives

| Option | Rejected because |
|---|---|
| Handlers into `notes`, `memories`, `session`, `syntheses` | base layers would import feature packages; `session` would need new edges to `capture` and `settle` |
| A `cli.py` per feature package | six of the nine clusters have no feature package |
| Split along the section banners | leaves handlers thousands of lines from their logic (A5) |
| Lazy import of every handler | `importlib` is banned in the engine; at most about 20 ms gained |
| A `register(sub)` parser per module now | doubles each pull request; owner kept the parser in `mem.py` |

## Consequences

- `grep cmd_X` finds one file holding the handler, its logic and its helpers; files between about 400 and 2,100 lines.
- Nine pull requests; about 45 names join `_MOVED`; 23 test patches move to the defining modules.
- `os.environ` stays in the command modules (the shell around pure logic); only `notes/search.py` is pure.
- A patch on `mem.X` for a moved name would silently do nothing: a test fails on any `setattr(mem, name)` whose name `mem.py` does not define.

## Revisit if

- `commands/` passes 10 modules or one of its modules passes 2,600 lines.
- The parser in `mem.py` passes 1,200 lines, or flag changes keep touching two files.
- The session-index hook's start-up p95 passes 1 s.
