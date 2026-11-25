# Agent-Skills: maintainer notes

Marketplace `mili-ssm`: the `agent-skills` plugin, the `memory` plugin, two UI mods and generated Copilot/Codex ports. Developed mostly by Claude sessions; this file holds only what the code does not show. The offload table and the routing text belong in the user-level `~/.claude/CLAUDE.md` (sources: `user-config/offload-policy.md` and `user-config/routing.md`, ADR 0012, 0021), never here, because a second copy loads twice.

## Commands

| When | Run |
|---|---|
| Before every commit (no CI or git hook enforces it, N5) | `python3 scripts/validate.py` (also runs `port.py --check`) and `claude plugin validate .` |
| Opening a pull request | `gh pr create --base dev` (GitHub's default branch is `main`, which only releases may reach); a release: `gh pr create --base main --head dev` |
| Before a release pull request (`dev` → `main`) | `python3 scripts/validate.py --release` (a changed plugin without a bump, or a tag that disagrees with its `plugin.json`, fails); fix before opening the pull request |
| After changing agents, skills, commands, `user-config/offload-policy.md` or `user-config/routing.md` | `python3 scripts/port.py` (`--report` prints the mapping) |
| After changing a mod | `claude plugin validate plugins/<mod>`, `claude plugin test plugins/<mod>`; type-check with `tsc -p plugins/<mod>` after one `claude --plugin-dir plugins/<mod>` |
| Measuring a description or prompt change | `claude plugin eval plugins/agent-skills --ablation none --model sonnet -j 4 --runs 2 --max-cost-usd 5 --case '<glob>'` (cases from § Eval protocol; one glob per invocation, `{a,b}` is not supported); offload cases add `--scaffold --allow-tools Bash Edit Write` and a sandbox |

## Generated files: never edit by hand

`ports/**`, `.github/plugin/marketplace.json`, `.agents/plugins/marketplace.json`, `user-config/{offload-policy,routing}.{copilot,codex}.md`, the README block between the `recommended-prompt` markers, the `docs/ports.md` block between the `models` markers. Edit the Claude source, then run `scripts/port.py`.

## Where a change goes

| Change | Edit | Also update |
|---|---|---|
| Skill, agent or command | `plugins/agent-skills/{skills,agents,commands}/` | `port.py`; the README catalog row (validate.py checks names, model and preloads); the eval case when a description changes |
| Offload table | `user-config/offload-policy.md` (single copy) | `port.py`; the `evals/offload/*-with-policy` cases embed it verbatim (validate.py checks) |
| Routing, plan loop and review rules | `user-config/routing.md` (single copy, ADR 0021) | `port.py`; no eval embeds it, so the ADR carries a kill criterion (N6) |
| Memory plugin | `plugins/memory/`; first read "Current state and where to resume" in `docs/superpowers/plans/2026-11-17-memory-plugin.md` | its tests (`uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`); the stage plan's state table; no port (ADR 0023) |
| UI mod | `plugins/<mod>/` and its README | `docs/mods-surfaces.md` for anything a surface did unexpectedly |
| Requirement | `docs/requirements.md` (keep IDs stable: `validate.py` cites them) | a flipped requirement needs an ADR |
| Decision | new `docs/adr/NNNN-kebab-title.md` | ADR rules below |
| Open work: an item opens, closes or changes | its source (plan, study) first | `docs/backlog.md`; any edit there moves its `Updated` and `Expires` dates (expiry rule at its top) |

## Rules the code does not show

- Measure every change to a `description` or to `user-config/offload-policy.md` before merging to `dev` (N6, ADR 0007, 0020) with the § Eval protocol, and record the table in an ADR `## Review YYYY-MM-DD`. Any other prompt change may ship labeled unmeasured, with kill criteria in its ADR.
- One commit per description change, so a regression can be reverted alone.
- Pull requests target `dev`, never `main`: users and cloud sessions install whatever `main` holds (ADR 0027). Release steps: README § Develop.
- Any change under `plugins/<name>/` (for agent-skills also `ports/`, `user-config/`, `user-agents/`), except a pure refactor, adds a line under `## [Unreleased]` in that plugin's `CHANGELOG.md`, written for users (impact, migration).
- The version lives only in `plugins/<name>/.claude-plugin/plugin.json`, never in a marketplace entry; it changes only in a release.
- Paths in `PUBLIC_PATHS` of `validate.py` (marketplace files, `user-config/*.md`, `user-agents/Explore.md`, README anchors) move only with an ADR, a release note in the plugin's changelog and a stub at the old path (ADR 0026).
- Only the seven workers (`WORKERS` in `validate.py`) say "Use proactively" (ADR 0007, 0010).
- Vocabulary (ADR 0007): "owner" for the human, "subagent" for the mechanism, "quality attribute" in full, "findings" for defects, "risks" for plans; ratings `low | medium | high` unless a domain scale is declared.
- Dense English, tables over prose, one home per fact with links elsewhere (ADR 0002). Cite ADRs by number.
- Read-only agents set `omitClaudeMd: true` and never see this file: a rule they need goes into their agent or skill prompt.

## Eval protocol (ADR 0007 Review 2026-10-30)

Run only the cases a change can move, because a full two-sided suite costs about 6× more runs than this:

| What changed | Cases (`--case` matches the case directory or `name:`) |
|---|---|
| A skill `description` | that skill's `trigger/` case, plus every `neg-*` |
| An agent `description` | trigger cases whose grader names it, its `offload-*` cases, plus every `neg-*` |
| A worker's body | its `offload-*` cases |
| `user-config/offload-policy.md` | every `offload-*-with-policy` |
| Skill bodies, references, commands | no suite covers them: read one trace |
| Only `scripts/port.py` or the ports, Claude files unchanged | no eval (owner, 2026-11): the Claude plugin is what the suites measure |

1. Run the new version at `--runs 2`, Sonnet as the main model (the owner's main conversation runs Sonnet or Opus; a Haiku main conversation measures Haiku's routing, not theirs).
2. Compare with the last result recorded for that case in an ADR. A case that is not 2/2 (fired, or silent for `neg-*`), or falls below its record, reruns at 6 runs on both sides (`main` checked out in a worktree), same flags.
3. A drop of 2 or more of 6 reverts that item; record every number either way.

## ADRs (`docs/adr/`)

- Line 3: `Status: accepted · Date: YYYY-MM-DD`, plus `· Supersedes NNNN`, `· Amends NNNN` or `· Amended by NNNN`. Sections: Context, Decision, Alternatives, Consequences, Revisit if.
- Never rewrite an accepted Decision: append `## Review YYYY-MM-DD` (or `## Measurement YYYY-MM-DD`) and update both Status lines.
- Current state in one call: `grep -n '^Status' docs/adr/*.md`; then read only the ADRs you need.

## Reading long files

`python3 plugins/agent-skills/skills/prompt-engineering/scripts/outline.py PATH` prints headings or declarations with line ranges; then read only the range you need. Never store line numbers in the repo: they go stale with every edit (ADR 0014).
