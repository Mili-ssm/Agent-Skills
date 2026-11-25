# 0029 Shared prompt text from fragments, Codex mapping from a model catalog

Status: accepted · Date: 2026-11-25 · Amends 0015

## Context

The owner wants one source of truth wherever possible, a marketplace that is clean, correct and extensible, and general tools that other plugins can reuse (2026-11-25). The project review of 2026-11-24 (B9–B12) found instruction lines copied 4 to 17 times across agents, with wording drift and no check. `scripts/port.py` held a hand-written 20-cell Claude → Codex table, edited cell by cell on each model change.

| Fact | Source |
|---|---|
| Installed plugins read the committed files; no tool runs a plugin step at install | `docs/platform-parity.md` (hook events) |
| A `SessionStart` render would apply only from the next session and write into a cache that updates replace | Claude Code loads agents and skills at session start |
| `user-config/*.md` is copied raw into eval cases, users' `~/.claude/CLAUDE.md` and the README prompt block | `scripts/cloud-setup.sh`, `port.py prompts()`, `evals/offload/*-with-policy` |
| Costs are compared only within a vendor (different plan budgets) | owner, 2026-11-19 |

## Decision

1. **Marked blocks, rendered at build time.** A shared text lives once in `shared/fragments/<id>.md`; plugin files carry `<!-- shared:<id> -->` blocks that `scripts/promptkit/fragments.py` fills and `--check` (run by `validate.py`) verifies, including copies outside blocks. Ports strip the markers. No markers in `user-config/`; text living there is guarded with `verbatim-in:`. Rules: [`shared/fragments/README.md`](../../shared/fragments/README.md).
2. **Model catalog.** `shared/models.toml` gives each vendor model a `level` on a scale shared across vendors (owner judgment) and a `cost` relative to the vendor's cheapest model (never compared across vendors). `scripts/promptkit/models.py` derives each Claude (model, effort) pair's Codex pair: the allowed pair with the smallest grade (level + 0.25 per effort step) that matches or beats it, ties to the cheaper; owner rulings that differ are pins (`[[overrides]]`). `port.py` builds `CODEX_PAIRS` and `COPILOT_MODELS` from it and generates the table in `docs/ports.md`.
3. **Effort policy (owner, 2026-11-25):** never `max`; `xhigh` only on a vendor's top model, because the next model at `low` beats the previous model at `xhigh`. `load_catalog` rejects levels that break it.
4. **Description person rule (main session, 2026-11-25, owner informed):** a short quoted user phrase is not the description speaking (requirement N2 states the bounds).
5. **Commit gate (owner, 2026-11-24, review Q3):** tests for `validate.py` and `port.py` under `scripts/tests/`, and an opt-in local `pre-push` hook (`git config core.hooksPath scripts/hooks`); still no CI, so the non-goal in `docs/requirements.md` narrows to CI and mandatory hooks.
6. `promptkit` takes paths as arguments and imports neither `port` nor `validate`, so any plugin can reuse it.

## Alternatives

| Option | Why not |
|---|---|
| Template sources (`*.md.tmpl`) generated at build time | Every agent would exist twice (source and output), and outputs invite hand edits; ports already give a clean install per vendor |
| Templates rendered at install (owner's proposal) | No tool runs a plugin step at install; a `SessionStart` render arrives one session late and needs Python and a hook on users' machines |
| Regenerate in CI when a release is tagged | Between releases `dev` would hold stale outputs, and the release would contain an unreviewed commit; the owner ruled out CI (2026-11-24) |
| A drift check only (the review's proposal) | Copies would remain; every edit still touches N files |
| Keep the hand table, add cost columns | Each new model means re-deriving 20 cells by hand; the effort policy would live in prose |

## Consequences

- Editing a shared line means editing its fragment and running `python3 -m promptkit.fragments` from `scripts/`; a hand edit inside a block fails `validate.py`.
- Markers cost a few tokens per block in each Claude agent's prompt (HTML comments); ports carry none.
- A new model is one catalog entry plus its level; the literal `AGENT_PAIRS` in `scripts/tests/test_models.py` fails if an agent's Codex pair moves, so a remap is deliberate.
- With the owner's acceptance (2026-11-25), only the four unused `max` cells changed; no agent's Codex model or effort changed.
- Unmeasured (eval protocol, CLAUDE.md): four read-only agents (`prompt-engineer`, `fact-checker`, `skeptical-reviewer`, `ux-reviewer`) gained the shared wording "build caches and temp dirs are fine"; `skeptical-reviewer` is a worker. Kill criterion: its next `offload/skeptical-reviewer*` run below its last recorded result by 2 or more of 6, or a trace where a reviewer writes into the repository → revert commit `fix(agent-skills): unify drifted copies of the read-only shell line`.

## Revisit if

- A tool adds an install-time hook or variable substitution in agent and skill bodies (install-time templates become possible).
- An agent needs a body that differs per vendor beyond model and tool names (full templates would pay off).
- A third vendor is ported, or a vendor publishes a capability benchmark that contradicts the levels.
