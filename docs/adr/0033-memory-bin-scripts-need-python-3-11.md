# 0033 The memory plugin's `bin/` scripts need Python 3.11

Status: accepted · Date: 2026-11-26

## Context

- `mem` runs through `uv` (`engine/mem.py` header: Python 3.12 or newer). The other `bin/` scripts (`mem-auto`, `mem-capture`, `mem-corroborate`, `mem-settle`, `mem-synthesize`, `mem-research`) start with `#!/usr/bin/env python3`, so they run on whatever `python3` the system has, and import engine modules from `engine/`.
- 2026-11-25 (commit 66679d2): Ruff targets `plugins/memory/bin/*` at `py310`, so those scripts keep to Python 3.10.
- 2026-11-26: the lint cleanup of [ADR 0031](0031-a-touched-python-file-passes-ruff-and-basedpyright.md) put `typing.Unpack` (3.11) into `engine/records.py` and `bin/mem-synthesize` (PR #199, unreleased), so `mem-synthesize`, and `mem-settle` and `mem-auto` that load it, fail at start on 3.10. Ruff's target version checks syntax, not standard-library names, so nothing caught it.
- `bin/mem-research` already needs 3.12 and `pyyaml` (it imports `mem.py`), on `dev` too.
- Assumption: users run Claude Code on systems whose `python3` is 3.11 or newer (macOS with a current Python, Ubuntu 24.04, Fedora); not measured.

## Decision

The `bin/` python scripts and the engine modules they import need Python 3.11 or newer. Ruff targets `bin/*` and `engine/headless.py` at `py311`; `engine/tests/test_bin_python_floor.py` parses every engine module a `bin/` script imports (transitively) at feature version 3.11 and rejects three 3.12-only names (`override`, `batched`, `TypeAliasType`); other standard-library names are not checked. `bin/mem-research` is excluded until `bin/` runs through `uv` (refactor plan, task "`bin/` holds launchers only").

## Alternatives

| Option | Rejected because |
|---|---|
| Keep 3.10: replace `Unpack`/`Required` with `NamedTuple` or dataclasses in everything `bin/` imports | About 15 signatures and their callers to change again, for systems with a 3.10 `python3` (Ubuntu 22.04) not known to be in use |
| Run every `bin/` script through `uv` now | The right end state, but it changes hooks and launchers: bigger than the refactor in progress |

## Consequences

- A system whose `python3` is 3.10 (Ubuntu 22.04) can no longer run the background passes; `mem` itself is unaffected (it uses `uv`).
- The 3.10 workaround in `bin/mem-corroborate` (`timezone.utc`) is gone; `datetime.UTC` is allowed.
- The floor test, not Ruff, catches 3.12 syntax and the three names it lists in code `bin/` imports; any other newer API still needs a review or a 3.11 run.

## Revisit if

- A user reports a system `python3` older than 3.11.
- `bin/` scripts run through `uv`: the floor then follows `mem.py`, and this ADR is superseded.
