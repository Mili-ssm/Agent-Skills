# 0037 The memory plugin's background passes choose their runner: Claude Code or Codex

Status: accepted · Date: 2026-11-27 · Amends 0036

## Context

ADR 0036 ported the memory plugin's core to Codex and left the background passes out: every model session the engine starts is `claude -p`, built by `engine/core/headless.py` (settle, capture, integrate, synthesize, corroborate) or by `research/pipeline.py` (memory, web and writing steps). On 2026-11-27 the owner proposed a `runner` choice, `claude` or `codex`, given per call, with a default set in configuration and as a plugin option, so no flag is needed day to day.

What `codex exec` offers against what the passes use (docs and probes of 2026-11-27, [Codex port plan](../superpowers/plans/2026-11-27-memory-codex-port.md)):

| `claude -p` feature the passes rely on | `codex exec` |
|---|---|
| `--model`, `--effort` | `--model`; effort through `-c model_reasoning_effort=…` |
| `--tools` / `--allowedTools`: no shell, only the tools a step needs | no per-tool control; `-s read-only` still lets the model run read-only commands, so a step cannot be kept from reading the store |
| `--max-budget-usd` | none: only time limits; plan credits are reported as tokens |
| `--output-format stream-json` (the callers parse it) | `--json` with a different event schema; `--output-schema`, `-o` |
| `--plugin-dir`, `--agent` | none (agents are TOML files in `~/.codex/agents/`) |
| no plugin hooks inside the session (`--setting-sources project`) | the owner's plugins and hooks load, including this plugin's own `SessionStart`, unless disabled |
| WebSearch and WebFetch for the research web step | a web search tool exists; whether it returns page text good enough for quotes is unverified |

## Decision

- **One setting, `runner`** (`claude` | `codex`), resolved per run in this order: the `--runner` flag of each pass command → `MEM_RUNNER` → the config file `~/.config/agent-memory/runner` (as `store` is) → the Claude plugin option `runner` → `claude`. The hooks pass the option as its own variable (`MEM_RUNNER_OPTION`), explicitly to every pass they start, so it ranks below the config file; Codex has no plugin options, so the config file is its default.
- **A runner layer in `engine/core`** builds the argv and normalizes the output (final text, files written, cost or tokens, tool uses the research audit needs) for both runners; the builders keep describing a session the same way (`headless.Session`).
- **First scope: the passes whose sessions use no tool** (settle, integrate, corroborate: they read a file and write a verdict file). Synthesis and the `mem-auto` curator run `Bash(mem <sub>*)` and write the store through it, and the research web step depends on seeing no store; `codex exec` cannot take the shell away, so these stay on `claude` until a later decision.
- **Codex sessions run isolated as far as `codex exec` allows**: `--ephemeral`, `-s read-only` (or `workspace-write` limited to the run folder for steps that write a file), cwd in the run's own folder, hooks disabled, the owner's AGENTS.md and MCP servers left out, stdin closed, and `HOME`/`XDG_CONFIG_HOME` pointed at the run folder with no `MEM_STORE`, because Codex's login shell re-sources the owner's profile and would put `mem` back on `PATH`.
- **The Codex binary is found at run time** (`MEM_CODEX`, else `codex` on `PATH`, else the newest `~/.vscode*/extensions/openai.chatgpt-*/bin/*/codex`), never stored: the extension's folder changes with each update.
- **Models map by tier** (Haiku → `gpt-6-luna`, Sonnet → `gpt-6.1-terra`, Opus → `gpt-6.2-sol`) from a table inside the engine, kept equal to `shared/models.toml` by a repository test (the installed plugin has no `shared/`).
- **Budgets**: a Codex session reports tokens, not money; the runner layer reports cost 0 plus tokens, and every budget site (`mem-auto`, integrate, settle, corroborate) counts a token cap for Codex runs, so a loop still ends; "no result" means no final message or a non-zero exit, not a missing cost.

## Alternatives

| Option | Rejected because |
|---|---|
| A flag only, no default | the owner asked for a default so daily use needs no flag |
| Infer the runner from the host that started the pass | passes started by Claude hooks may still be meant for Codex models (cost), and the reverse; an explicit setting is predictable |
| Codex agents (TOML) instead of prompts | agents live in the user's `~/.codex/agents/`, outside the plugin; the passes already carry their prompts |
| Codex for every step now, isolation accepted | the research web step's separation is a security property (page text never meets the store); weakening it needs the owner's explicit choice |
| Wait for Codex per-tool controls | no date; the passes that need no isolation gain now |

## Consequences

- Passes run on either vendor's plan; the session-start lines and run logs name the runner.
- Every builder moves to the runner layer; tests gain a Codex argv and output case per builder.
- Codex runs have no money cap, only time and tokens; a kill criterion watches cost.
- Ships behind its default (`claude`): nothing changes until the owner sets `runner`.

## Revisit if

- Codex gains per-tool control, a budget cap or a no-plugins flag that makes isolation equal.
- The trial in the plan shows Codex judgments worse than Claude's on the same inputs.
- The owner wants the isolated steps on Codex.

## Review 2026-11-27

Built the same day (plan tasks 1–5; [plan](../superpowers/plans/2026-11-27-memory-runner.md) holds every table). What changed from the Decision, by the owner's rulings after measurement:

- **Scope**: settle and corroborate only. Integrate left the Codex scope: on the same seeds Codex appended 0 of 17 sentences in the first trial and its diagnosis run, and 0, 1, 0 with the fix below (Claude 14 and 16); a diagnosis showed its place step never proposed one (it reads "what that part covers" as only what the part's sentences already say), and a model-neutral fix (each part's `subject` as data) did not close the gap while it made Claude's replies fail their format in 2 of 3 runs, so it was reverted.
- **Settle on Codex** merged the same pair, one that loses content, in the first trial and the diagnosis run (Claude 0). A rule that a merge must lose nothing fixed Codex (0 wrong in 3 runs) but lowered Claude's recall (16, 17, 16 of 20 against 18), so it applies to Codex sessions only (`entry/settle.py` `CODEX_ADDENDUM`); Claude's prompt is unchanged.
- **A `codex` default never disables a pass**: Claude-only passes ignore a default with a note and refuse only an explicit `--runner codex`.
- **Isolation, observed**: inside a Codex session `mem` was not found and the real store could not be written; a private `CODEX_HOME` was needed because `--ignore-user-config` keeps the owner's `~/.codex/AGENTS.md`; the run folder's credential link is removed after each run, and a token Codex refreshes by replacing the file is copied back.
- Ships with `claude` as the default (the owner's setting on 2026-11-27); Codex is documented as experimental. Total trial spend: about 0.2 USD on Claude and at least 0.63M Codex tokens recorded in the plan (the diagnosis and rerun runs' tokens were not recorded; plan credits).
