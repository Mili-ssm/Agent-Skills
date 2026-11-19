# Using agent-skills from GitHub Copilot and OpenAI Codex

`agent-skills` is written for Claude Code. `scripts/port.py` generates equivalent copies for GitHub Copilot CLI and OpenAI Codex under `ports/` (ADR 0015). The mods (`tool-fold`, `plan-progress`) are Claude-only and are not listed for other tools.

> Generated files: never edit `ports/`, `.github/plugin/marketplace.json`, `.agents/plugins/marketplace.json` or `user-config/{offload-policy,routing}.{copilot,codex}.md` or the README block between the `recommended-prompt` markers by hand. Change the Claude source, then run `python3 scripts/port.py`; `scripts/validate.py` fails while they are stale.

## Install

Install steps for Copilot CLI and Codex are in the [README](../README.md#install); the recommended prompt (offload table and routing) is in [its section](../README.md#recommended-prompt).

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
| Claude-only names in the text (`Explore`, `AskUserQuestion`, "CLAUDE.md" for delegation rules) | Mapped to Copilot's equivalents; `/agent-skills:<x>` becomes `/<x>` | Mapped to Codex's; model tags such as "(Haiku)" become the GPT model |
| Mods, evals | — | — |

`python3 scripts/port.py --report` prints the full mapping; `--check` proves it, file by file.

## Models

Copilot runs the same Claude models: model and effort pass through (`haiku` → `claude-haiku-5.5`, `sonnet` → `claude-sonnet-5.5`, `opus` → `claude-opus-5.5`, `fable` → `claude-fable-5.2`; GitHub's docs give Fable only as a display name, so that id is unconfirmed). Codex maps the (model, effort) pair together (owner, 2026-11; cost-optimized equivalences):

| Claude model | low | medium | high | xhigh | max |
|---|---|---|---|---|---|
| `haiku` | `gpt-6-luna` low | `gpt-6-luna` low | `gpt-6-luna` medium | `gpt-6-luna` high | `gpt-6-luna` xhigh |
| `sonnet` | `gpt-6-luna` high | `gpt-6.1-terra` low | `gpt-6.1-terra` medium | `gpt-6.2-sol` low | `gpt-6.1-terra` xhigh |
| `opus` | `gpt-6.2-sol` low | `gpt-6.2-sol` low | `gpt-6.2-sol` medium | `gpt-6.2-astra` low | `gpt-6.2-sol` xhigh |
| `fable` | `gpt-6.2-astra` low | `gpt-6.2-astra` medium | `gpt-6.2-astra` high | `gpt-6.2-astra` xhigh | `gpt-6.2-astra` max |

Each Claude pair maps to the cheapest Codex pair that matches or beats it. The two vendors' plans have different budgets, so prices are never compared across vendors: each scale below is relative to the cheapest model of its own vendor, so matching tiers (luna and Haiku, terra and Sonnet, sol and Opus, astra and Fable) have a similar place on each scale, a rough proxy for capability too; single cells trade some cost for capability.

| Codex model | Relative cost per token |
|---|---|
| `gpt-6-luna` | 1 |
| `gpt-6.1-terra` | 10 |
| `gpt-6.2-sol` | 20 |
| `gpt-6.2-astra` | 80 |

| Claude model | Relative cost per token |
|---|---|
| Haiku 5.5 | 1 |
| Sonnet 5.5 | 20 |
| Opus 5.5 | 40 |
| Fable 5.2 | 80 |

Codex: plan credits per token (`learn.chatgpt.com/docs/pricing`, 2026-11-19; `gpt-6.1-sol` costs the same as `gpt-6.2-sol`). Claude: API list price per token (Haiku 5.5 $0.10/$0.50 per 1M up to 100K-token prompts, Sonnet $2/$10, Opus $4/$20, Fable $8/$40; Anthropic pricing, 2026-11). Effort does not change the price per token, only how many tokens a task uses. Each tier uses its newest listed version; terra has no 6.2 release, so it stays on `gpt-6.1-terra`. Owner 2026-11-19: the cells that gave terra `high` give `gpt-6.2-sol` `low`, the cell that gave sol `high` gives `gpt-6.2-astra` `low`, and Fable maps 1:1 by effort to astra; no agent uses those cells, which are kept current anyway; agents can only set `low`, `medium` or `high` today (`EFFORTS` in `scripts/port.py`), so `xhigh` and `max` need that list widened first. Models as of 2026-11-19 (`codex-rs/models-manager/models.json`); change `CODEX_PAIRS` in `scripts/port.py` when the tools' model lists change. A pair missing from the table fails `port.py --check`. Copilot falls back to the session model when a listed model is unavailable.

## Limits

- Unmeasured: neither tool has an eval command, and the descriptions and delegation rules were tuned on Claude.
- Paths assume the default install folders; with a custom `COPILOT_HOME` or `CODEX_HOME` the generated commands use that variable.
- Verified from Copilot's docs source and Codex's source code on 2026-10-30, not by running either tool.
