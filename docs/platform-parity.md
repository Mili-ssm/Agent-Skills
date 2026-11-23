# Platform parity: Claude Code, Codex, Copilot and Antigravity CLIs

What each coding-agent CLI supports of the Claude Code plugin surface, and what porting this marketplace's plugins to it would keep, lose and work around. Documentation only: the ports that exist are described in [ports.md](ports.md) (ADR 0015); nothing here is built.

Verified 2026-11-23 from each vendor's documentation, read in full and fact-checked against local copies, except cells marked "first-pass reading". Refresh only on the events in [§ Refresh](#refresh). A cell reads "not documented" when the pages read say nothing; that is not proof of absence.

---

## Verdicts per plugin

| Plugin | Codex CLI | Copilot CLI | Antigravity CLI |
|---|---|---|---|
| `agent-skills` (skills, commands, agents) | **Ported** (ADR 0015); tool limits are prose, agents install outside the plugin | **Ported** (ADR 0015); same Claude models | **Portable, not built**: skills as is except the two that use `${CLAUDE_SKILL_DIR}`; agents need a model-tier map; commands become user-only skills |
| `memory` (hooks, options, `bin/`, background `claude -p`, 4 agents, 3 skills) | **Portable with losses**: every hook event exists, but `PreCompact` ignores plain stdout (the handoff request needs another channel); no plugin options documented, `SessionEnd` capped at 3 s, hooks need the user's trust review | **Portable with losses**: no `PostCompact`, `preCompact` cannot steer the summary, no plugin options documented; how a plugin hook finds its folder is not documented | **Core only**: `SessionStart` is the only session hook (`Stop` can stand in for session end); no subagent, compaction or session-end hooks |
| `tool-fold`, `plan-progress` (UI mods) | **Not portable**: no UI plugin API | **Not portable**; at most a status-line script (experimental) | **Not portable**; at most a status-line script |

Gemini CLI still ships releases (v0.70.0, 2026-11-19) and serves enterprise users, but stopped serving consumers (AI Pro, Ultra and free individual accounts) on 2026-06-18, while Antigravity CLI is open to everyone since 2026-05-19 ([announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)). Google's column is therefore Antigravity CLI; Gemini CLI appears as a column only in the hook table.

---

## Versions and sources

| Tool | Version read | Main pages |
|---|---|---|
| Claude Code | docs gated up to v2.1.328 | [hooks](https://code.claude.com/docs/en/hooks), [plugins reference](https://code.claude.com/docs/en/plugins-reference), [skills](https://code.claude.com/docs/en/skills), [subagents](https://code.claude.com/docs/en/sub-agents) |
| Codex CLI | docs undated; stable release 0.171.0 (2026-11-20, GitHub releases) | [hooks](https://learn.chatgpt.com/docs/hooks), [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [plugins](https://developers.openai.com/plugins/build/plugins), [skills](https://learn.chatgpt.com/docs/build-skills) |
| Copilot CLI | docs undated; changelog v1.0.114 (2026-11-18) | [hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference), [plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference), [custom agents](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli), [custom instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions) |
| Antigravity CLI | docs undated (headless page cites v1.5.7) | [build plugins](https://antigravity.google/docs/build-plugins/), [plugins](https://antigravity.google/docs/plugins?tab=cli), [hooks](https://antigravity.google/docs/hooks?tab=cli), [subagents](https://antigravity.google/docs/subagents?tab=cli) |
| Gemini CLI | hooks page updated 2026-04-10; release v0.70.0 | [hooks reference](https://geminicli.com/docs/hooks/reference/) |

---

## Packaging

| | Claude Code | Codex CLI | Copilot CLI | Antigravity CLI |
|---|---|---|---|---|
| Manifest | `.claude-plugin/plugin.json` | root `plugin.json`, vendor fields under `extensions.com.openai`; fallback `.codex-plugin/plugin.json` | first found: `.plugin/plugin.json`, `plugin.json`, `.github/plugin/plugin.json`, `.claude-plugin/plugin.json` | root `plugin.json`; `.antigravity-plugin/plugin.json` wins |
| Catalog | `.claude-plugin/marketplace.json` | `.agents/plugins/marketplace.json`; reads `.claude-plugin/marketplace.json` as legacy | same search order as the manifest | official marketplace only; also installs from a GitHub URL or local folder |
| Components a plugin ships | skills, commands, agents, hooks, MCP, LSP, output styles, workflows, `bin/` (themes, monitors experimental) | skills, MCP (`mcp.json`), hooks; agents and commands not listed | portable (Agent Plugins 1.0): skills, `mcp.json`; Copilot-only under `com.github.copilot/`: agents, hooks, commands | skills, agents, rules (`rules/AGENTS.md`, `rules/*.md`), scripts, `hooks.json`, `mcp_config.json`; `commands/` not loaded |
| Reads Claude's layout | — | marketplace only | `.claude-plugin/plugin.json`, `.claude/skills`, `.claude/commands`, hooks in `.claude/settings*.json` | `agy plugin import claude` migrates from the Claude plugins folder |

---

## Skills, commands and agents

| | Claude Code | Codex CLI | Copilot CLI | Antigravity CLI |
|---|---|---|---|---|
| Skill frontmatter honored | full set (`allowed-tools`, `disable-model-invocation`, `model`, `effort`, `context`, …) | `name`, `description`; implicit use off through `agents/openai.yaml` `policy.allow_implicit_invocation` | `name`, `description`, `license`, `allowed-tools` (first-pass reading of the skills page, not fact-checked) | `name`, `description`, `disable-model-invocation`, `license`, `compatibility` |
| Variables in skill bodies | `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`, … | not documented | not documented | not documented (bundled files by relative path) |
| Commands | `commands/*.md` with `$ARGUMENTS` | not shippable by a plugin; skills replace them | manifest `commands` field exists; format not documented | not loaded from plugins; Gemini import turns them into skills |
| Agent file | `agents/*.md` | TOML role in `~/.codex/agents/` or `.codex/agents/`, not in the plugin | `.agent.md`; plugin path `com.github.copilot/agents/` (Agent Plugins 1.0) or `agents/` (legacy manifest) | `agents/*.md` in the plugin |
| Per-agent model | `haiku`, `sonnet`, `opus`, `fable`, ID | GPT model + `model_reasoning_effort` | any listed model ID, Claude included | tier: `inherit`, `flash`, `flash_lite`, `pro` |
| Per-agent effort | yes | yes | not on the current agents page; the port emits `reasoningEffort` (ADR 0015) | not documented (CLI flag `--effort` only) |
| Tool allowlist | `tools`, `disallowedTools` | none; an agent file can only switch whole features off (`features.shell_tool`, …) | `tools` aliases, `strict-tools-list` | `tools`, `commandExecutionPolicy` |
| Skip project instructions (`omitClaudeMd`) | yes | no equivalent | the reverse: `include-custom-instructions` opts in | `inheritCustomizations` (semantics not verified) |
| Turn limit (`maxTurns`) | yes | not documented | not documented | not documented |
| Delegation | by description | only when the user, `AGENTS.md` or a skill asks | by description, `/agent`, `--agent` | `invoke_subagent`, async, nesting up to 10 |

---

## Hooks

### Event map

Our plugins use the bold rows. "≈" marks a near match whose timing differs.

| Claude Code | Codex CLI | Copilot CLI | Antigravity CLI | Gemini CLI |
|---|---|---|---|---|
| **`SessionStart`** | `SessionStart` (plain stdout becomes context) | `sessionStart` (`additionalContext`) | `SessionStart` (`injectSteps`) | `SessionStart` |
| **`SessionEnd`** | `SessionEnd` (1 s default, 3 s max) | `sessionEnd` | — | `SessionEnd` |
| **`SubagentStart`** | `SubagentStart` (stdout becomes context) | `subagentStart` (`additionalContext`; the built-in general-purpose agent emits none) | — | — |
| `SubagentStop` | `SubagentStop` | `subagentStop` | — | — |
| **`PreCompact`** | `PreCompact` | `preCompact` (notification only, no output) | — | `PreCompress` |
| **`PostCompact`** | `PostCompact` | — | — | — |
| `UserPromptSubmit` | `UserPromptSubmit` | `userPromptSubmitted` (config-file output dropped); `userPromptTransformed` | ≈ `PreInvocation` (every model call) | ≈ `BeforeAgent` |
| `PreToolUse` | `PreToolUse` (no `ask`) | `preToolUse` (allow, deny, ask) | `PreToolUse` (six decision values) | `BeforeTool` |
| `PostToolUse` | `PostToolUse` | `postToolUse`, `postToolUseFailure` | `PostToolUse` (returns only `{}`; no output fields documented) | `AfterTool` |
| `Stop` | `Stop` | `agentStop` (8 consecutive blocks end the turn) | `Stop` | ≈ `AfterAgent` |
| `PermissionRequest` | `PermissionRequest` | `permissionRequest` | — | — |
| `Notification` | — (`notify` setting) | `notification` | — | `Notification` |
| 21 more (`Setup`, `FileChanged`, `WorktreeCreate`, …) | — | — | — | — |
| — | `Interrupt`, `PreModelRequest`, `PostModelRequest` | `errorOccurred` | `PostInvocation` | `BeforeModel`, `AfterModel`, `BeforeToolSelection` |

### Contract

| | Claude Code | Codex CLI | Copilot CLI | Antigravity CLI |
|---|---|---|---|---|
| Handler types | command, http, mcp_tool, prompt, agent | command, mcp_tool (prompt, agent parsed but skipped) | command, http, prompt (`sessionStart` only, interactive) | command |
| Default timeout | 600 s (30 s on some events) | 600 s | 30 s | 30 s |
| Exit 2 | blocks on events that can block; elsewhere stderr is shown or ignored | blocks | denies on `preToolUse`, `permissionRequest`; warning elsewhere | any non-zero is logged and ignored: block with JSON `decision: "deny"` |
| Failure | fail-open unless `onFailure: "block"` | — | command `preToolUse` fails closed; timeouts fail open | fail-open |
| Plugin root in hooks | `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `CLAUDE_PLUGIN_OPTION_<KEY>` | `PLUGIN_ROOT`, `PLUGIN_DATA`, plus `CLAUDE_PLUGIN_*` aliases | not documented for hooks (the variables are documented for MCP and agent `mcp-servers`) | none; the hook runs in the plugin root, so relative paths work |
| Payload naming | snake_case, Claude tool names | snake_case; `apply_patch` also matches `Edit`/`Write` | camelCase; PascalCase event names give Claude-style payloads and tool names | camelCase, own tool names (`run_command`, `view_file`) |
| Plugin hooks, conditions | none | only manually installed plugins (not the public directory); the user must review them in `/hooks`, again after each change | none documented | CLI runs them; the IDE page lists none |

---

## Settings, MCP, context, headless and UI

| | Claude Code | Codex CLI | Copilot CLI | Antigravity CLI |
|---|---|---|---|---|
| Plugin options | `userConfig` → `CLAUDE_PLUGIN_OPTION_<KEY>`, `${user_config.KEY}` | none documented (enable flag, per-MCP toggles) | none documented | `variables`, asked at install, expanded in MCP config |
| `bin/` on PATH | yes | not documented | not documented | not documented |
| MCP in a plugin | `.mcp.json` | `mcp.json` | `mcp.json` (1.0) or `.mcp.json` (legacy) | `mcp_config.json`; `${PLUGIN_ROOT}`, `${PLUGIN_DATA}` expanded |
| Instruction files | `CLAUDE.md` (`AGENTS.md` only when no `CLAUDE.md`) | `AGENTS.md` | all merged, no general precedence: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `copilot-instructions.md` | `AGENTS.md`, `GEMINI.md`, `.agents/rules/`; plugin `rules/` |
| Headless | `claude -p` | `codex exec` | `copilot -p` | `agy -p` |
| Status line | command | built-in items only | command (experimental) | command |
| UI plugin API (mods) | yes | no | no | no |
| Claude models | yes | no | yes | Opus 5.5 and Sonnet 5.5 on paid plans ([models page](https://antigravity.google/docs/models?tab=cli), first-pass reading, not fact-checked) |

---

## Porting notes per plugin

### `agent-skills`

- Codex and Copilot: the generated ports stand. Two fields of the Copilot port need re-verifying before its next release, because today's Copilot pages do not document them: `disable-model-invocation` on skills (used to make commands user-only) and `reasoningEffort` on agents.
- Antigravity: skills copy as is, except `ux-principles` and `prompt-engineering`, whose bodies use `${CLAUDE_SKILL_DIR}` (no variable is documented, so use relative paths); commands become skills with `disable-model-invocation: true`; agents keep `tools` but trade `model` for a tier and lose `effort` and `maxTurns` (state them as rules, as for Codex). The routing and offload text could ship inside the plugin as `rules/AGENTS.md`, which no other tool allows.

### `memory`

| Need | Codex | Copilot | Antigravity |
|---|---|---|---|
| Session index at start | `SessionStart` stdout | `sessionStart` `additionalContext` | `SessionStart` `injectSteps` |
| Index for subagents | `SubagentStart` | `subagentStart`, except the general-purpose agent | none: put the three lines in plugin `rules/AGENTS.md` (whether subagents load it is not verified) |
| Handoff before compaction | lost as built: `PreCompact` ignores plain stdout, and no context field for it is documented | lost: `preCompact` has no output | lost |
| Compaction log | `PostCompact` | lost | lost |
| Capture and history commit at end | `SessionEnd`, but 3 s at most: run the commit in a detached process | `sessionEnd` | no session-end event: a debounced `Stop` hook or the next `SessionStart` |
| Agents (4) and skills (3) | as for `agent-skills`: roles outside the plugin, tool limits as rules | as for `agent-skills` | as for `agent-skills` |
| Options (`store`, `auto_*`) | a config file read by `mem` | a config file | `variables` |
| `mem` on PATH | call it by `PLUGIN_ROOT` from hooks; skills need a shim on PATH | not documented how a hook finds the plugin folder; hooks run inside the session sandbox | relative to the plugin root (hooks run there) |
| Background passes (`claude -p`) | `codex exec` | `copilot -p`, with the same Claude models | `agy -p` |

Claude Code itself: a plugin hook's `timeout` does not raise the shared 1.5 s `SessionEnd` budget, so the plugin's 5 s history commit at session end is likely cut short there too; the detached-process fix applies to Claude as well.

The engine (`mem`, Python) is tool-neutral. The work is the hooks, the option wiring, the four agents and the six `claude -p` call sites (memory plugin plan, "Codex port").

### `tool-fold`, `plan-progress`

Neither tool has a UI plugin API. A status-line script could show a usage or plan summary in Copilot (experimental) and Antigravity; Codex allows only built-in status items.

---

## Refresh

Re-verify a tool's column on any of these events, not on a schedule (owner, 2026-11-23):

- Before starting or releasing a port to that tool.
- A release or announcement that changes its plugins, hooks, skills or agents, or a product transition such as Gemini CLI to Antigravity CLI.
- A new model family or tier: also update the model maps in [ports.md](ports.md#models).
- A revisit condition of ADR 0015 fires.

How: one researcher per tool with the rows of this file as its checklist; update the tool's literature notes in the `mem` store from the full page text; a fresh-context fact-check against the local copies; then edit the rows and the "Verified" date at the top.

## Not verified

- No tool was run: every row comes from documentation.
- Antigravity docs carry no dates; its IDE may not run plugin hooks (one forum report).
- Copilot: how plugin hook commands find the plugin folder; the command file format.
- Codex: whether plugins will ship agents; `bin/` on PATH.
