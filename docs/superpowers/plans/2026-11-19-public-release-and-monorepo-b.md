# Public release and monorepo option B

Goal: the plugins of the `mili-ssm` marketplace become public (fewer than ten users, owner 2026-11-19): MIT license, one SemVer version and changelog per plugin, released when changes pile up, and the paths installed users rely on recorded as a contract (architect review 2026-11-19, option B). Option C (self-contained per-plugin packages) is assessed, not executed.

Owner decisions (2026-11-19): license MIT; one version per plugin, not one for the repo; versions are cut when several changes accumulate, not per commit; `.memory/` goes in `.gitignore`; option B step by step.

Decisions taken here (owner left them to the agent):
- Copyright holder `Mili-ssm`; one `LICENSE` at the root covers every plugin.
- Version source: `version` in each `plugins/<name>/.claude-plugin/plugin.json` only; marketplace entries carry none.
- Changelog: `plugins/<name>/CHANGELOG.md` (Keep a Changelog), so it installs with the plugin; tag `<plugin>-vX.Y.Z`, annotated.
- Copilot port copies the version; the Codex port keeps none, because its cache folder is `local` only without a version and the skills print that path (`CODEX_ROOT` in `scripts/port.py`); Codex has no auto-update to steer anyway.
- Proposed first versions, confirmed by the owner before any tag is pushed: agent-skills 1.0.0; memory, tool-fold, plan-progress 0.1.0.

## Tasks

- [x] 1. Housekeeping: root `LICENSE` (MIT), `.memory/` in `.gitignore`, `docs/requirements.md` "Repo role" and the marketplace description name `memory`. Check: `git check-ignore .memory`; `python3 scripts/validate.py`; `claude plugin validate .`.
- [ ] 2. ADR 0026, public paths contract (amends 0008, 0011), plus a `validate.py` check that each listed path exists. Check: validate passes; deleting a listed path in a scratch copy fails it.
- [ ] 3. ADR 0027, public plugins with per-plugin versions (supersedes 0006, amends 0008); Status lines of 0006 and 0008; `CLAUDE.md` rule on `version`; README "Update" (auto-update opt-in, releases) and "Develop" (release steps; the owner's own install updates only on a release). Check: `grep -n '^Status' docs/adr/000[68]*.md docs/adr/002[67]*.md`; no doc still says "every commit is a version" outside accepted ADR bodies.
- [ ] 4. Tooling: `validate.py` iterates the marketplace entries and checks each plugin's SemVer `version`, a matching `## [version]` section in its `CHANGELOG.md`, and no `version` on marketplace entries; `port.py` copies the version into the Copilot manifest and keeps the Codex manifest without one. Check: `python3 scripts/port.py`, `python3 scripts/validate.py` (includes `--check`), `claude plugin validate .`.
- [ ] 5. First release: versions and first changelog entries; PR, review, merge; owner confirms the versions; annotated tags pushed. Check: `git tag -l '*-v*'`; a fresh `claude plugin marketplace update mili-ssm` shows the versions.
- [ ] 6. Option C assessment reported to the owner (viability, need, convenience), no edits.
