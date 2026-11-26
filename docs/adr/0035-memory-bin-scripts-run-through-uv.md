# 0035 The memory plugin's `bin/` scripts run through uv

Status: accepted · Date: 2026-11-26 · Supersedes 0033

## Context

- [ADR 0033](0033-memory-bin-scripts-need-python-3-11.md) kept the six background scripts (`mem-auto`, `mem-capture`, `mem-corroborate`, `mem-research`, `mem-settle`, `mem-synthesize`) on the system `python3` with a 3.11 floor, and named its own revisit trigger: "`bin/` scripts run through `uv`". `mem` already needs `uv`, so the floor bought no independence from it, and it needed a test (the floor test) and a per-file Ruff target to hold.
- Measured 2026-11-26 (pre-mortems of the [plan](../superpowers/plans/2026-11-26-memory-bin-through-uv.md)):
  - `uv` keys script environments by the script path: a PEP 723 header in each of seven scripts means seven environments per plugin version.
  - A cold start prints `Installed ...` on stderr unless `--quiet`.
  - A cold cache with no network fails.
  - A warm start costs 0.03 s.
  - Parallel cold starts share one install.
- A background pass that fails to start is silent by design (detached, output discarded), so a missing `uv` must be reported elsewhere.

## Decision

- Every `bin/` file is a bash launcher: it finds its folder through a `readlink` loop, checks `command -v uv` (exit 127 with `<name>: uv is not installed (https://docs.astral.sh/uv/)`), then `exec uv run --quiet --script engine/run.py --bin <name> "$@"`. `bin/mem` is the same without `--bin`.
- `engine/run.py` is the only PEP 723 header (one environment) and dispatches `--bin <name>` with one static import per name. It rewrites `sys.argv` to `[name, *rest]` so `--help` stays identical.
- The bodies of the old scripts live in `engine/entry/` (`auto`, `capture`, `corroborate`, `settle`; `research` and `synthesize` delegate to their packages). Only `run.py` imports that layer.
- Launch sites execute the launcher with no interpreter prefix (`settle/state.py`, capture's corroborate start).
- `hooks/session-index.sh` prints one notice line in its "mem did not answer" branch when `uv` is missing, so the silent failures are visible once per session.
- `test_bin_launchers.py` replaces the floor test: every `bin/` file is a bash launcher and the `--bin` names of `run.py` match the launchers one to one. The Ruff `py311` per-file targets are removed.

## Alternatives

| Option | Why not |
|---|---|
| A PEP 723 header per script | Seven environments per plugin version, each a cold install; failures stay silent |
| Keep the system `python3` with the 3.11 floor (ADR 0033) | Two interpreter policies; a floor test and per-file Ruff targets to maintain; `mem-research` already broke it |
| Install the engine as a `uv` project with entry points | Larger change (packaging, `src/` layout); ADR 0034 names it as a later revisit |

## Consequences

- No system `python3` is needed; the whole engine targets Python 3.12 to 3.14.
- `uv` is required for the background passes, as for `mem`; without it they exit 127 and the session start text says so.
- An offline machine after a plugin update fails until it is online once (the cache for the new plugin path is cold).
- `mem --bin X` now dispatches to a job instead of an argparse error; accepted, nobody types it.
- One cached environment per plugin path serves all launchers; a synchronous hook path gains no `uv` start.

## Revisit if

- The cold-start failure offline is reported by users: vendor or pre-build the environment.
- The engine becomes an installed package (ADR 0034 revisit): entry points then replace `run.py`'s dispatch table.
- `uv` stops being available on the platforms the plugin targets.
