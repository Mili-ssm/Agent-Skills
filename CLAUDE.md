# Agent-Skills: maintainer notes

Marketplace `mili-ssm`: the `agent-skills` plugin, three UI mods and generated Copilot/Codex ports. Developed mostly by Claude sessions; this file holds only what the code does not show. The offload table belongs in the user-level `~/.claude/CLAUDE.md` (source: `user-config/offload-policy.md`, ADR 0012), never here, because a second copy loads twice.

## Commands

| When | Run |
|---|---|
| Before every commit (no CI or git hook enforces it, N5) | `python3 scripts/validate.py` (also runs `port.py --check`) and `claude plugin validate .` |
| After changing agents, skills, commands or `user-config/offload-policy.md` | `python3 scripts/port.py` (`--report` prints the mapping) |
| After changing a mod | `claude plugin validate plugins/<mod>`, `claude plugin test plugins/<mod>`; type-check with `tsc -p plugins/<mod>` after one `claude --plugin-dir plugins/<mod>` |
| Measuring a description or prompt change | `claude plugin eval plugins/agent-skills --ablation none --model sonnet -j 4 --runs 2 --max-cost-usd 5 --case '<glob>'` (cases from § Eval protocol; one glob per invocation, `{a,b}` is not supported); offload cases add `--scaffold --allow-tools Bash Edit Write` and a sandbox |

## Generated files: never edit by hand

`ports/**`, `.github/plugin/marketplace.json`, `.agents/plugins/marketplace.json`, `user-config/offload-policy.{copilot,codex}.md`. Edit the Claude source, then run `scripts/port.py`.

## Where a change goes

| Change | Edit | Also update |
|---|---|---|
| Skill, agent or command | `plugins/agent-skills/{skills,agents,commands}/` | `port.py`; the README catalog row (validate.py checks names, model and preloads); the eval case when a description changes |
| Offload table | `user-config/offload-policy.md` (single copy) | `port.py`; the `evals/offload/*-with-policy` cases embed it verbatim (validate.py checks) |
| UI mod | `plugins/<mod>/` and its README | `docs/mods-surfaces.md` for anything a surface did unexpectedly |
| Requirement | `docs/requirements.md` (keep IDs stable: `validate.py` cites them) | a flipped requirement needs an ADR |
| Decision | new `docs/adr/NNNN-kebab-title.md` | ADR rules below |

## Rules the code does not show

- Measure every description or prompt change before merging to `main` (N6, ADR 0007) with the § Eval protocol, and record the table in an ADR `## Review YYYY-MM-DD`. A change shipped without it is labeled unmeasured, with kill criteria.
- One commit per description change, so a regression can be reverted alone.
- No `version` in any `plugin.json` or marketplace entry: every commit is a version (ADR 0006).
- Only the six workers (`WORKERS` in `validate.py`) say "Use proactively" (ADR 0007, 0010).
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

1. Run the new version at `--runs 2`, Sonnet as the main model (the owner's main conversation runs Sonnet or Opus; a Haiku main conversation measures Haiku's routing, not theirs).
2. Compare with the last result recorded for that case in an ADR. A case that is not 2/2 (fired, or silent for `neg-*`), or falls below its record, reruns at 6 runs on both sides (`main` checked out in a worktree), same flags.
3. A drop of 2 or more of 6 reverts that item; record every number either way.


- Line 3: `Status: accepted · Date: YYYY-MM-DD`, plus `· Supersedes NNNN`, `· Amends NNNN` or `· Amended by NNNN`. Sections: Context, Decision, Alternatives, Consequences, Revisit if.
- Never rewrite an accepted Decision: append `## Review YYYY-MM-DD` (or `## Measurement YYYY-MM-DD`) and update both Status lines.
- Current state in one call: `grep -n '^Status' docs/adr/*.md`; then read only the ADRs you need.

## Reading long files

`python3 plugins/agent-skills/skills/prompt-engineering/scripts/outline.py PATH` prints headings or declarations with line ranges; then read only the range you need. Never store line numbers in the repo: they go stale with every edit (ADR 0014).
