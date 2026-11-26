# 0034 The memory engine is organized in feature packages

Status: accepted · Date: 2026-11-26

## Context

- `plugins/memory/engine/` held 35 modules in one folder. Families shared a filename prefix instead of a package: seven `corroborate_*`, `research_*`, `capture*`, `settle*`, `synth*`. No ADR or plan recorded a reason; the layout followed from how the code starts: `mem.py` runs as a PEP 723 script (`uv run --script`), whose folder Python puts first on `sys.path`, and the `bin/` launchers insert `engine/`.
- Research 2026-11-26 (memory `m:organize-source-folders-by-feature-or-component-what`): group code by what changes together (Common Closure Principle; Parnas 1972; vertical slices; package by component), colocate helpers and tests, treat a repeated filename prefix as a missing package, keep nesting shallow, and check boundaries with an import test, because folders alone erode. No source gives a file-count threshold.
- A package beside the script needs no install: with `engine/` on `sys.path`, `from synthesize import pipeline` resolves `engine/synthesize/pipeline.py`.
- The owner asked for this organization on 2026-11-26 and chose a pilot: `mem-synthesize` (review A4) moved into `engine/synthesize/` ([plan](../superpowers/plans/2026-11-26-memory-synthesize-split.md)).

## Decision

Engine code lives in feature packages under `engine/` (`synthesize/` first; then `corroborate/`, `research/`, `capture/`, `settle/`, `store/` and a small `core/`, backlog A14), moved one package per pull request with behavior unchanged. Imports are absolute and package-qualified (`from synthesize import run`), calls go through the module attribute, and `__init__.py` files stay empty or a docstring. Each package gets a rule in `engine/tests/test_import_graph.py` naming who may not import it (first: store modules never import `synthesize`). Tests of a package live in `engine/tests/<package>/` without `__init__.py`. `mem.py` stays at the engine root as the entry point until A5 splits it.

## Alternatives

| Option | Rejected because |
|---|---|
| Keep the flat folder | The prefixes already act as unnamed packages; a reader cannot see where a feature starts, and nothing checks the boundaries |
| `src/` layout with an installed package | The engine is never installed; `mem.py` runs as a PEP 723 script and the `bin/` scripts on the system `python3` (ADR 0033), so an install step adds a moving part for no gain |
| Move every module in one pull request | One large rename touches about 100 tests and their `monkeypatch` targets at once; per-package pull requests keep each review and rollback small |

## Consequences

- Every move retargets imports and `monkeypatch` targets in tests, evals and `bin/`; a `__file__`-relative path one level deeper needs `parents[n+1]` (seen in the pilot: `PLUGIN` in `synthesize/pipeline.py`).
- `test_bin_python_floor.py` and `test_import_graph.py` resolve dotted names and package `__init__.py` files, so the 3.11 floor and the import bans cover packages.
- `bin/mem-auto` and `bin/mem-settle` import `synthesize` instead of loading `bin/mem-synthesize` with `exec_module`.

## Revisit if

- The engine becomes an installed package (for example when `bin/` runs through `uv` as a project): then a `src/` layout and entry points replace the `sys.path` insert.
- A package grows past about 10 modules or mixes unrelated reasons to change: split it.
