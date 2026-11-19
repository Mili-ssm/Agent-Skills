# 0026 Paths installed users rely on are a public contract

Status: accepted · Date: 2026-11-19 · Amends 0008, 0011

## Context

The plugins are now public, with fewer than ten users besides the owner (owner, 2026-11-19; ADR 0027). Installed copies and copies of scripts that users pasted resolve repository paths, so a move breaks them silently, at most with a warning (architect review, 2026-11-19):

| Consumer | Paths it resolves |
|---|---|
| Claude Code, Copilot CLI, Codex | The three marketplace files and their `source` paths; plugin names |
| `scripts/cloud-setup.sh`, including old pasted copies | `user-config/offload-policy.md`, `user-agents/Explore.md` (looked up by path in the marketplace clone) |
| Plugin READMEs, installed with each plugin | Root README anchors `#update` and `#develop`; users also follow `#install` and `#recommended-prompt` |
| The owner's `~/.claude/CLAUDE.md` (ADR 0021) | `user-config/offload-policy.md`, `user-config/routing.md` |

The same review found the layout itself sound (plugins in `plugins/<name>/`, ports in `ports/<tool>/<plugin>/`), so the risk is moves, not structure.

## Decision

- The paths in the table above, plus the root `LICENSE`, are public. `scripts/validate.py` checks that each exists, and that the root README keeps the four headings behind the anchors.
- Moving or renaming one needs a new ADR, a release note in the affected plugin's `CHANGELOG.md`, and a stub at the old path (a file pointing to the new one, or the old heading kept) for at least one release of that plugin.
- Every other path may move freely; agents find files by search, not by memorized paths.

## Alternatives

| Option | Rejected because |
|---|---|
| Free moves, as before | Silent breakage for installed users and pasted scripts |
| Self-contained packages per plugin (docs, ADRs, config inside each plugin) | Breaks links inside accepted ADRs and the public paths above, and ships development material in every install; reassessed for the owner on 2026-11-19, not adopted |

## Consequences

- A layout change costs an ADR and a release note; a deletion of a listed path fails `validate.py`.
- The list lives in `validate.py` (one home); this ADR keeps the why.

## Revisit if

The cloud setup stops reading files by path, a plugin moves to its own repository, or the marketplace adds a plugin whose users need other paths kept.
