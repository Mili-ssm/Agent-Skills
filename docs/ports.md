# Using agent-skills from GitHub Copilot and OpenAI Codex

`agent-skills` is written for Claude Code. `scripts/port.py` generates equivalent copies for GitHub Copilot CLI and OpenAI Codex under `ports/` (ADR 0015). The mods (`tool-fold`, `usage-band`, `plan-progress`) are Claude-only and are not listed for other tools.

> Generated files: never edit `ports/`, `.github/plugin/marketplace.json`, `.agents/plugins/marketplace.json` or `user-config/offload-policy.{copilot,codex}.md` by hand. Change the Claude source, then run `python3 scripts/port.py`; `scripts/validate.py` fails while they are stale.

## Install

### GitHub Copilot CLI

```bash
copilot plugin marketplace add Mili-ssm/Agent-Skills
```

```bash
copilot plugin install agent-skills@mili-ssm
```

Then add the offload table to your user instructions: copy [`user-config/offload-policy.copilot.md`](../user-config/offload-policy.copilot.md) into `~/.copilot/copilot-instructions.md` (or `$COPILOT_HOME/copilot-instructions.md`).

### OpenAI Codex

```bash
codex plugin marketplace add Mili-ssm/Agent-Skills
```

```bash
codex plugin install agent-skills@mili-ssm
```

Codex plugins cannot carry agents, so copy the role files from the installed plugin:

```bash
mkdir -p ~/.codex/agents && cp ~/.codex/plugins/cache/mili-ssm/agent-skills/local/agents/*.toml ~/.codex/agents/
```

Then add [`user-config/offload-policy.codex.md`](../user-config/offload-policy.codex.md) to `~/.codex/AGENTS.md`. Repeat the copy after each plugin update.

## What maps to what

| Claude Code | Copilot CLI | Codex |
|---|---|---|
| Skill | Same skill; paths point to the installed copy | Same skill (`agent-skills:<skill>`); paths point to the installed copy |
| Command `/agent-skills:<cmd>` | Skill `/<cmd>`, user-only (`disable-model-invocation`) | Skill `agent-skills:<cmd>`, implicit invocation off (`agents/openai.yaml`) |
| Agent | `.agent.md`: same text, same Claude model and effort, tool allowlist | Role file: same text, nearest GPT model, same effort |
| `skills:` preload | Skill text appended to the agent | Same |
| `tools` / `disallowedTools` | Enforced by `tools` | Stated as rules. `shell_tool = false` would enforce "no shell", but Codex also reads files through its shell, so it applies only to an agent without Bash, Read, Grep and Glob (none today) |
| `omitClaudeMd` | `include-custom-instructions` | No equivalent |
| `maxTurns` | Stated as a rule | Stated as a rule |
| Mods, evals | — | — |

`python3 scripts/port.py --report` prints the full mapping; `--check` proves it, file by file.

## Models

| Claude | Copilot | Codex |
|---|---|---|
| `haiku` | `claude-haiku-5.5` | `gpt-6-luna` (fast, affordable) |
| `sonnet` | `claude-sonnet-5.5` | `gpt-6.1-sol` (default) |
| `opus` | `claude-opus-5.5` | `gpt-6-astra` (frontier) |

As of 2026-10; change `MODEL_MAP` in `scripts/port.py` when the tools' model lists change. Copilot falls back to the session model when a listed model is unavailable.

## Limits

- Unmeasured: neither tool has an eval command, and the descriptions and delegation rules were tuned on Claude.
- Paths assume the default install folders; with a custom `COPILOT_HOME` or `CODEX_HOME` the generated commands use that variable.
- Verified from Copilot's docs source and Codex's source code on 2026-10-30, not by running either tool.
