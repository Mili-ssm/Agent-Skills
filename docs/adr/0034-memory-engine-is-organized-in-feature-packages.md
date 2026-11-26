# 0034 The memory engine is organized in feature packages

Status: accepted · Date: 2026-11-26 · Amends 0033

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

## Review 2026-11-26

The last revisit trigger fired: `store/` reached 19 modules in two families with different reasons to change (the memory records, and the notes with their index, validators and syntheses). The owner chose two top-level packages over subpackages inside `store/` and over keeping it flat; `store/` no longer exists.

| Package | Modules | Imports |
|---|---|---|
| `core` | gains `yaml_load` (the YAML loader and `safe_load`) and `store_git` (both families commit the store) | stdlib; PyYAML in `yaml_load` only |
| `memories` | `records` (facade), `journal`, `matching` (with the former `pairing`), `terms`, `locations`, `sightings`, `rules`, `fingerprints`, `model` (with the former `shortcheck`), `parse`, `write` | `core` |
| `syntheses` | `document` (model, load, validation, source numbering), `units` (unit parser, fingerprints), `edit` (section writes and their guards), `project` (project syntheses) | `core`, `memories` |
| `notes` | `note`, `index`, `check` (the rule catalog), `fields`, `links`, `due` | `core`, `memories`, `syntheses` |

- Layering, enforced in `test_import_graph.py`: `notes → syntheses → memories → core`; `memories` imports neither `notes` nor `syntheses`, `syntheses` never imports `notes`. `memories`, `syntheses` and `notes` are base layers like `core`: any feature package may import them, within its own entry in `PACKAGE_DEPENDENCIES`.
- Modules inside `memories/` import siblings directly, never the `records` facade (a rule in the same test).
- Each package's `__init__.py` docstring is its module map, one `` `module`: role`` line per module, so an agent finds a module without opening the folder; `test_package_docstring_maps_every_module` keeps every map complete.
- `patch_all` (`tests/patching.py`) patches every `memories.*`, `syntheses.*` and `notes.*` binding of a name.
- `notes/check.py` (1,396 lines) and the old `notes/syntheses.py` (1,316) were split by cohesion, not to a line cap; `check.py` keeps the whole rule catalog (~800 lines). Owner rule 2026-11-26: size is a balance, neither one 10k-line file nor a hundred 100-line files; split a file that mixes reasons to change or abstraction levels, or a part likely to grow or change often; merge small parts that rarely change. Measured norm: CPython 3.14 stdlib median 269 lines, p90 1,165, p99 3,409; rustc's tidy rejects files over 3,000 lines.
- Behavior and goldens are unchanged; the collected count grew only by new guard tests.
