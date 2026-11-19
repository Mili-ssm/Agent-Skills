# Public release and monorepo option B

Goal: the plugins of the `mili-ssm` marketplace become public (fewer than ten users, owner 2026-11-19): MIT license, one SemVer version and changelog per plugin, released when changes pile up, and the paths installed users rely on recorded as a contract (architect review 2026-11-19, option B). Option C (self-contained per-plugin packages) is assessed, not executed.

Owner decisions (2026-11-19): license MIT; one version per plugin, not one for the repo; versions are cut when several changes accumulate, not per commit; work integrates on a `dev` branch and `main` holds only releases (a release is a PR from `dev` to `main`); `.memory/` goes in `.gitignore`; option B step by step.

Why `dev`: marketplace sources are relative paths read from the branch users track (`main`), so a `version` only labels that branch's content; new installs and cloud sessions would get unreleased commits (pre-mortem 2026-11-19). With `main` = releases, users change nothing and `user-config/` ships versioned with it.

Verified 2026-11-19 (Claude Code 2.1.328, isolated HOME, local clone as marketplace): an install recorded by SHA moves to `0.1.0` on `marketplace update` + `plugin update`; a later commit with the same version does not update. Copilot: not installed here, so its switch from no version to a version is unverified (its docs use `version`); fallback below.

Decisions taken here (owner left them to the agent):

- Copyright holder `Mili-ssm`; one `LICENSE` at the root covers every plugin.
- Version source: `version` in each `plugins/<name>/.claude-plugin/plugin.json` only; marketplace entries carry none.
- Changelog: `plugins/<name>/CHANGELOG.md` (Keep a Changelog), so it installs with the plugin; tag `<plugin>-vX.Y.Z`, annotated, on the release merge commit on `main`.
- Copilot port copies the agent-skills version; the Codex port keeps none, because its cache folder is `local` only without a version and the skills print that path (`CODEX_ROOT` in `scripts/port.py`); Codex has no auto-update to steer anyway. A change to the ports alone needs an agent-skills bump to reach Copilot users.
- Owner's install follows `dev` (`Mili-ssm/Agent-Skills#dev`); `cloud-setup.sh` gets an optional `AGENT_SKILLS_REF` (default `main`).
- Proposed first versions, confirmed by the owner before the release PR merges (the merge ships them): agent-skills 1.0.0; memory, tool-fold, plan-progress 0.1.0.

## Tasks

- [x] 1. Housekeeping: root `LICENSE` (MIT), `.memory/` in `.gitignore`, `docs/requirements.md` "Repo role" and the marketplace description name `memory`. Check: `git check-ignore .memory`; `python3 scripts/validate.py`; `claude plugin validate .`.
- [x] 2. ADR 0026, public paths contract (amends 0008, 0011): marketplace files and sources, plugin names, `user-config/*.md`, `user-agents/Explore.md`, root README anchors `#install`, `#update`, `#develop`, `#recommended-prompt`; `validate.py` checks they exist. Check: validate passes; removing a listed path in a scratch copy fails it.
- [x] 3. ADR 0027, public plugins released from `main` with per-plugin versions (supersedes 0006, amends 0008); Status lines of 0006 and 0008; `docs/requirements.md` Audience row; `CLAUDE.md` (PRs target `dev`, release steps, the `version` rule); README "Update" (auto-update opt-in, releases, changelogs) and "Develop" (branches, release checklist). Check: `grep -n '^Status' docs/adr/000[68]*.md docs/adr/002[67]*.md`; no live doc says "every commit is a version".
- [x] 4. Tooling: `validate.py` iterates the marketplace entries (SemVer `version` per plugin, a `## [version]` section in its `CHANGELOG.md`, `[Unreleased]` allowed, no `version` on marketplace entries) and gets `--release`: fails when a plugin's files (agent-skills: also `ports/`, `user-config/`, `user-agents/`) changed since its last tag while its version still equals that tag's, or when a tag's `plugin.json` version differs from the tag name; `port.py` copies the version into the Copilot manifest, Codex stays without; `cloud-setup.sh` honors `AGENT_SKILLS_REF`. Check: `python3 scripts/port.py`, `python3 scripts/validate.py`, `python3 scripts/validate.py --release`, `claude plugin validate .`.
- [x] 5. First release: versions and first changelog entries; owner confirms versions; PR to `main`, review, merge; annotated tags on the merge commit, pushed; `dev` created from `main`; owner's install moved to `#dev`. Check: `git tag -l '*-v*'`; the owner's install shows the versions after `claude plugin marketplace update mili-ssm`.
- [ ] 6. Option C assessment reported to the owner (viability, need, convenience), no edits.

## Kill criteria

- Copilot stops updating or breaks once its port has a version → drop `version` from the Copilot port, as for Codex.
- The owner releases more than twice a week only to get their own fixes into their sessions → revisit (their install follows `main` by choice, 2026-11-19; a `#dev` install would not update between versions).
