# 0006 Track commits, no pinned version

Status: accepted · Date: 2026-10-27

## Context

Claude Code computes a plugin's version from `plugin.json` `version`, then the marketplace entry `version`, else the commit SHA. A pinned `"version": "0.1.0"` keeps every install on the cached copy until the string changes, however many commits are pushed. Single owner, no release process.

## Decision

- No `version` in `plugin.json` or `marketplace.json`: each commit on the default branch is a new version (12-char SHA).
- Updates reach installs via `claude plugin update`, `/plugin` → Marketplaces → Update marketplace, or auto-update (off by default for third-party marketplaces; enable per install).
- Cloud sessions install the plugin from the environment setup script (README).

## Alternatives

| Option | Rejected because |
|---|---|
| Pinned SemVer, bump per release | Forgotten bump = silent no-update; no consumers needing stability |
| Tags + `#vX.Y.Z` marketplace refs | Release overhead without benefit yet |

## Consequences

- Any push to the default branch ships; keep it green (`scripts/validate.py`).

## Revisit if

Other people depend on the plugin, or breaking changes need controlled rollout → pin `version` and follow `release-hygiene`.

## Review 2026-10-27

Verified on Claude Code 2.1.311: removing `version` moved an install from `0.1.0` to `931a3034b9a3`. `claude plugin update` alone reported "already at latest" on a stale marketplace copy; run `claude plugin marketplace update mili-ssm` first.
