# 0015 Generated ports for GitHub Copilot and OpenAI Codex

Status: accepted · Date: 2026-10-30 · Amends 0011

## Context

The owner wants `agent-skills` usable from GitHub Copilot and OpenAI Codex, with one hard limit: Claude Code must behave exactly as before. The mods stay Claude-only.

Verified on 2026-10-30, from Copilot's docs source (`github/docs`), Codex's source (`openai/codex` at f2ac998) and Claude Code's docs:

| Fact | Copilot CLI | Codex |
|---|---|---|
| Skills (`SKILL.md`) | Yes; plugin `skills/` | Yes; plugin `skills/`, named `<plugin>:<skill>` |
| Agents in a plugin | `com.github.copilot/agents/*.agent.md` (Agent Plugins 1.0) | No: plugin manifests carry no agents; role files go in `~/.codex/agents/*.toml` |
| Per-agent model | Yes, including the same Claude models | Yes (GPT models) |
| Per-agent tool allowlist | Yes (`tools` aliases) | No; only `[features] shell_tool = false` |
| Commands | Run as skills (`disable-model-invocation`) | Command files with `$ARGUMENTS` are skipped at install |
| Catalog lookup (first found wins) | … `.github/plugin/` before `.claude-plugin/` | `.agents/plugins/` before `.claude-plugin/` |
| Path variables in bodies | None documented | None |

Claude Code reads only `.claude-plugin/marketplace.json`, the plugins its entries list, `CLAUDE.md` / `AGENTS.md` and `.claude/`; it reads nothing under `ports/`, `.github/plugin/` or `.agents/`.

## Decision

- `scripts/port.py` generates, from the Claude sources, one plugin per tool under `ports/` plus a catalog in each tool's own lookup path, listing only `agent-skills`. Nothing under `plugins/` or `.claude-plugin/` changes.
- Agents, skills and commands are translated, not rewritten: same text, plus the substitutions and appendices that keep their meaning where a tool lacks a Claude feature (preloaded skills inlined; tool and read-only limits stated as rules where Codex cannot enforce them; `maxTurns` as a stated limit). Copilot keeps the same Claude models; Codex uses the nearest GPT tier.
- `port.py --check` regenerates and compares, then parses the generated files back and checks equivalence field by field; `validate.py` runs it, so a change to a Claude source without regenerating fails.
- The offload policy gets generated variants for Copilot's and Codex's user-level instruction files. No `AGENTS.md` or `CLAUDE.md` is generated anywhere, because Claude Code would load it.

## Alternatives

| Option | Rejected because |
|---|---|
| Shared files for every tool (Agent Plugins manifest beside `.claude-plugin/`) | Skill bodies need tool-specific paths; editing them would change Claude |
| Hand-written ports | Drift; nothing proves equivalence |
| A root `AGENTS.md` with the policy | Claude Code reads `AGENTS.md`; it would change this repo's sessions |
| Porting the mods | No mods API in Copilot or Codex |

## Consequences

- Generated copies duplicate the skills in the repo; `--check` keeps them in step.
- Copilot and Codex behavior is unmeasured: no eval tool, and the descriptions were tuned on Claude.
- In Codex, read-only and tool limits are rules, not enforcement: its only per-role switch, `shell_tool = false`, would also remove file reads, so no current agent gets it. `omitClaudeMd` has no equivalent.
- Model names in `MODEL_MAP` age; update them with each tool's model list.

## Revisit if

Copilot or Codex documents path variables in skill bodies, Codex plugins gain agents or tool allowlists, or the Agent Plugins spec adds portable agents.

## Verification 2026-10-30

- Claude Code unchanged: `git diff origin/main -- plugins .claude-plugin user-config/offload-policy.md` is empty, and the SHA-256 of all 178 files Claude Code loads matches the pre-change baseline. Claude evals were not re-run, because their inputs did not change.
- `port.py --check` passes. Tamper tests (an edited, deleted or extra generated file; a stale source; one per mapping rule; generator bugs that leave no drift) each fail it and name the file.
- An independent review (a Sonnet subagent that had not seen the generator) compared all 15 agents, the skills, the commands and both policies across the two tools and found the ports equivalent with notes. Fixed after it:
  - Preloaded skills now state their base directory, so relative links resolve.
  - Codex read-only rule now allows temp dirs and build caches, as the sources do.
  - Codex tool rules name capabilities, not Claude tool names.
  - Claude-only names were mapped: `(Haiku)` and the other model tags in Codex, `Explore`, `AskUserQuestion`, "Delegation rules in CLAUDE.md", and `/agent-skills:` in Copilot.
- Not verified: running either tool. Formats come from Copilot's docs source and Codex's source code.

## Review 2026-10-30

The owner added a root `CLAUDE.md` with maintainer notes for the Claude sessions that develop this repo. It holds no offload table, which stays user-level, and no `CLAUDE.md` or `AGENTS.md` is generated for the ports; the decision above stands.
