---
name: release-hygiene
description: Conventions for Conventional Commits, SemVer bumps, Keep a Changelog entries and release checklists. Use when writing a commit message or changelog entry, choosing a version number, tagging or preparing a release; load it before proposing a version or tag so the bump follows the commit rules.
---

# Release Hygiene

Conventional Commits, SemVer and Keep a Changelog are assumed known; this skill covers the decisions that usually go wrong.

## Commits

- A breaking change (anything that breaks the documented or exported API) carries `!` after the type or a `BREAKING CHANGE:` footer; it forces a major bump, except under `0.y.z` (below).
- `feat` → minor; `fix`/`perf` → patch; other types → no release by themselves.
- One logical change per commit, tests green at each, so bisect and revert stay usable; refactoring and behavior changes in separate commits.

## Versions

- `0.y.z`: bump minor for breaking changes by convention.
- One source of the version (`pyproject.toml` / `Cargo.toml`); lockfile updated with it, so the tag, the artifact and the changelog name the same version.
- Pre-releases follow the ecosystem: Cargo and SemVer use `1.4.0-rc.1`; PyPI uses `1.4.0rc1`, not `1.4.0-rc.1`, because PEP 440 normalizes the registry version to that form and the SemVer spelling in a tag or changelog then differs from what PyPI shows.
- Detect breaks mechanically: `cargo semver-checks` (Rust).

### Choosing the next version

1. List the commits since the last tag (`git log "$(git describe --tags --abbrev=0)"..HEAD --oneline`; no tag yet: the whole history).
2. Classify each commit with the rules above; the highest bump wins (major > minor > patch).
3. Propose the version to the owner and confirm before pushing a tag or publishing, because published versions cannot be replaced.

## Changelog

Entries describe the impact on users and the migration path, not the commit subjects.

<example>
## [2.0.0] - 2026-10-27
### Removed
- `/v1/export` endpoint (deprecated since 1.6.0). Use `/v2/exports`; see migration notes.
</example>

## Release checklist

```
- [ ] Main green; breaking changes have a major bump and migration notes
- [ ] Version chosen from the commits since the last tag (highest bump wins)
- [ ] Version bumped in its single source; lockfile updated
- [ ] Changelog [Unreleased] → version + date
- [ ] Annotated tag vX.Y.Z (local); build from the tag
- [ ] Owner confirms; then push the tag and publish
- [ ] Install from the registry in a clean environment and smoke-test
- [ ] Open a new [Unreleased]
```

Optional automation: `git-cliff`, `release-please`, `cargo-release`, `commitizen`.
