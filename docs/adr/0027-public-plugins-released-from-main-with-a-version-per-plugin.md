# 0027 Public plugins, released from main with a version per plugin

Status: accepted · Date: 2026-11-19 · Supersedes 0006 · Amends 0008, 0011

## Context

Fewer than ten people besides the owner use the plugins (owner, 2026-11-19), which fires the "Revisit if" of ADR 0006 and 0008. The owner wants releases when several changes accumulate, not one per commit, and a changelog for users and for themselves.

Facts behind the decision:

| Fact | Source |
|---|---|
| Claude Code takes the version from `plugin.json`, then the marketplace entry, else the commit SHA; a version blocks updates until the string changes | Claude Code plugin docs, 2026-11-19 |
| Auto-update of a third-party marketplace is a user opt-in; the marketplace author cannot turn it on | same |
| An install recorded by SHA moves to `0.1.0` on `marketplace update` + `plugin update`; a later commit with the same version does not update it | observed, Claude Code 2.1.328, isolated HOME, 2026-11-19 |
| Plugin sources are relative paths read from the branch users track, so a version only labels that branch's content: new installs and cloud sessions get every commit on it | pre-mortem 2026-11-19, from `.claude-plugin/marketplace.json` |
| Copilot CLI reads `version`; its switch from no version to one is untested (not installed on the owner's machine) | Copilot CLI plugin reference |
| Codex caches an unversioned plugin under `local`, which `CODEX_ROOT` in `scripts/port.py` and the paths skills print rely on; Codex documents no auto-update | Codex plugin docs |

## Decision

1. **License**: MIT, one `LICENSE` at the root for every plugin.
2. **Branches**: work integrates on `dev` (pull requests target it); `main` holds only releases, so what users and cloud sessions install from `main` is always released, `user-config/` included. A release is a pull request from `dev` to `main`.
3. **Versions**: SemVer per plugin, single source `plugins/<name>/.claude-plugin/plugin.json`; marketplace entries carry none. A release bumps only the plugins that changed; a change under `ports/`, `user-config/` or `user-agents/` counts as an agent-skills change. The Copilot port copies the agent-skills version; the Codex port stays unversioned.
4. **Changelog**: `plugins/<name>/CHANGELOG.md`, Keep a Changelog, written for users (impact and migration), with an `[Unreleased]` section filled on `dev`.
5. **Tags**: annotated `<name>-vX.Y.Z` on the release merge commit on `main`.
6. **Checks**: `validate.py` checks each plugin's version and changelog section; `validate.py --release` fails when a plugin changed since its last tag without a bump, or when a tag disagrees with its `plugin.json`.

The owner's install follows `dev` (`Mili-ssm/Agent-Skills#dev`; `cloud-setup.sh` reads `AGENT_SKILLS_REF`), so their own fixes do not wait for a release.

## Alternatives

| Option | Rejected because |
|---|---|
| Keep no version, every commit a release (ADR 0006) | The owner wants batched releases and a changelog |
| One version for the whole repository | A release of one plugin would update all of them |
| Versions on `main` without a `dev` branch | The version would label unreleased content (Context) |
| Marketplace sources pinned to each plugin's tag (`git-subdir` with `ref`) | Untested in Claude Code and Copilot; `user-config/` would still ship unversioned from `main` |

## Consequences

- Users change nothing: they keep tracking `main` and, with auto-update on, receive only releases.
- A forgotten bump keeps a change from users; `validate.py --release` on the release pull request catches it.
- Pull requests need `--base dev`, since `main` stays the default branch users clone.

## Revisit if

Copilot stops updating once its port has a version (then drop it there, as for Codex); the owner releases more than twice a week only to reach their own fixes; or users need a channel that tracks `dev`.

## Review 2026-11-19

The Decision's line "the owner's install follows `dev` … so their own fixes do not wait for a release" is wrong for a persistent install: Claude Code updates a plugin only when its version string changes (Context), so an install that follows `dev` stays on the last version until a release bumps it. Only a fresh install (a cloud session) takes `dev`'s current content. The owner chose to follow `main` and update only on releases; unreleased work is tried with `claude --plugin-dir plugins/<name>`. `AGENT_SKILLS_REF` stays for cloud environments that want `dev`. A marketplace added with `#<ref>` is a single-branch clone: removing the ref later does not switch it back (the clone's fetch refspec must change, or the marketplace be re-added).
