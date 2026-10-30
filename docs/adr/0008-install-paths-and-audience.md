# 0008 Install paths and audience

Status: accepted · Date: 2026-10-27 · Supersedes 0005 · Amended by 0011

## Context

ADR 0005 assumed one install command per environment. Verified on Claude Code 2.1.311: cloud sessions ignore plugins declared in a repository's settings; a GitHub-hosted marketplace installs with `claude plugin install agent-skills --marketplace Mili-ssm/Agent-Skills`; `claude plugin update` alone keeps a stale marketplace copy. Auto-update means every push to the default branch runs as instructions and scripts in the owner's sessions. The owner confirmed the plugin is for personal use.

## Decision

- Repo root stays a plugin plus a single-plugin marketplace.
- Local: `/plugin install` or `claude plugin install … --marketplace …`. Cloud: `scripts/cloud-setup.sh` as the environment setup script; it installs the plugin and the Python Playwright library, enables marketplace auto-update, and prints a warning instead of failing silently.
- Audience: owner only; no license; the default branch (`main`) is trusted code because auto-update runs it.

## Alternatives

| Option | Rejected because |
|---|---|
| Repo `.claude/settings.json` with `enabledPlugins` | Ignored by cloud sessions |
| Copy skills into each project's `.claude/` | Duplicates and drifts per project |
| Auto-update off | Stale skills in cached cloud snapshots |

## Consequences

- Install failures in cloud show as warnings in the setup log.
- Anyone with push access to `main` controls the owner's agent instructions.

## Revisit if

Others start using the plugin (add a license, pin versions per ADR 0006), or cloud sessions start honoring repo-declared plugins.

## Review 2026-10-30

Decision bullet 1 is amended by ADR 0011: the root is a marketplace only, and each plugin, `agent-skills` included, lives in `plugins/<name>/`.
