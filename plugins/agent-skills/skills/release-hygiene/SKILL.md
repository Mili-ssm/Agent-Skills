---
name: release-hygiene
description: Conventions for Conventional Commits, SemVer bumps, Keep a Changelog entries and release checklists. Use when writing a commit message or changelog entry, choosing a version number, tagging or preparing a release.
---

# Release Hygiene

Conventional Commits, SemVer and Keep a Changelog are assumed known; these are the decisions that usually go wrong.

## Commits

- `<type>(<scope>)!: <imperative summary ≤ 72 chars>`; body says why, not what.
- `!` or a `BREAKING CHANGE:` footer marks a major change; `feat` → minor; `fix`/`perf` → patch; others → none.
- One logical change per commit, tests green at each, so bisect and revert stay usable.
- Refactoring and behavior changes in separate commits.

## Versions

- Define the public API (docs, exported symbols) first; SemVer is meaningless without it.
- `0.y.z`: bump minor for breaking changes by convention.
- Pre-releases: `1.4.0-rc.1`.
- One source of the version (`pyproject.toml` / `Cargo.toml`); lockfile updated with it.
- Detect breaks mechanically: `cargo semver-checks` (Rust); PEP 440 versions (Python).

## Changelog

Written for users: impact, migration notes, deprecations. Sections `Added · Changed · Deprecated · Removed · Fixed · Security` under `## [x.y.z] - YYYY-MM-DD`, with an `[Unreleased]` section on top.

<example>
## [2.0.0] - 2026-10-27
### Removed
- `/v1/export` endpoint (deprecated since 1.6.0). Use `/v2/exports`; see migration notes.
</example>

## Release checklist

```
- [ ] Main green; breaking changes have a major bump and migration notes
- [ ] Version bumped in its single source; lockfile updated
- [ ] Changelog [Unreleased] → version + date
- [ ] Annotated tag vX.Y.Z; build from the tag
- [ ] Install from the registry in a clean environment and smoke-test
- [ ] Open a new [Unreleased]
```

Optional automation: `git-cliff`, `release-please`, `cargo-release`, `commitizen`.
