---
name: release-hygiene
description: Use when writing commit messages, preparing a release, bumping versions, tagging or updating a changelog - Conventional Commits, SemVer, Keep a Changelog and a release checklist.
---

# Release Hygiene

## Conventional Commits

`<type>(<scope>)!: <imperative summary ≤ 72 chars>` + optional body (why, not what) + footers.

| Type | Use | SemVer effect |
|---|---|---|
| `feat` | New capability | minor |
| `fix` | Bug fix | patch |
| `perf` | Performance improvement | patch |
| `refactor` | Structure change, no behavior change | none |
| `docs`, `test`, `style` | Docs / tests / formatting | none |
| `build`, `ci`, `chore` | Tooling, deps, CI, housekeeping | none |
| `!` or `BREAKING CHANGE:` footer | Incompatible change | major |

Rules: one logical change per commit; tests pass at each commit; reference issues in footers (`Refs: #123`).

## SemVer (`MAJOR.MINOR.PATCH`)

- MAJOR: incompatible public API change. MINOR: backward-compatible feature. PATCH: backward-compatible fix.
- `0.y.z`: anything may change; bump minor for breaking changes by convention.
- Pre-releases: `1.4.0-rc.1`. Public API must be defined (docs, exported symbols) for SemVer to mean anything.
- Rust: follow Cargo's SemVer compatibility guide; `cargo semver-checks` detects breaks. Python: PEP 440 versions.

## Keep a Changelog

```markdown
## [Unreleased]
### Added | Changed | Deprecated | Removed | Fixed | Security
## [1.4.0] - 2026-10-27
```

Written for users (impact), not a git log dump. Link versions to compare URLs.

## Release checklist

1. Main green; no unreleased breaking change without major bump.
2. Version bumped in one place (`pyproject.toml` / `Cargo.toml`), lockfile updated.
3. Changelog `[Unreleased]` → version + date.
4. Migration notes for breaking changes and deprecations.
5. Tag `vX.Y.Z` (annotated), build from tag, publish artifacts.
6. Verify install from the registry in a clean environment.
7. Announce; open next `[Unreleased]`.

Tools (optional): `git-cliff`, `release-please`, `cargo-release`, `commitizen`.
