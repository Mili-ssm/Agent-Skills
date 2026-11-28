# Parity audit: `agent-skills` and `memory` on Copilot and Google's CLIs

Status: audit done, nothing built; owner rulings and open decisions in the [plan](../superpowers/plans/2026-11-28-google-copilot-parity.md) · Date: 2026-11-28

What each part of `agent-skills` and `memory` keeps, needs changed, or loses on GitHub Copilot (CLI, VS Code, cloud agent) and on Google's Antigravity CLI and Gemini CLI. It extends [platform-parity.md](../platform-parity.md) (verified 2026-11-23) with a second documentation reading and a code inventory; it does not replace it. No tool was run: vendor cells are from documentation, except the Copilot session-file schema, read from four session files on the development machine. [§ Evidence](#evidence-and-limits) says which cells were checked against page text.

## Conclusion

| Plugin | Copilot CLI | Antigravity CLI | Gemini CLI |
|---|---|---|---|
| `agent-skills` | Ported; two generated fields and the model ids rest on undocumented behavior; the session start hook is now portable | Portable, not built: skills and agents map; models collapse to two tiers; effort and turn limits have no field | Portable, not built: closest agent frontmatter (`max_turns`, model id), but agents are a preview feature and the tool serves enterprise and API-key users only |
| `memory` | Portable with losses, the closest target after Codex: index hooks map 1:1, capture needs a new transcript decoder, compaction handoff is lost | Core plus capture, with timing losses: no session-end, subagent or compaction event; `Stop` and plugin rules stand in | Core likely; transcript access not verified |
| Mods (`tool-fold`, `plan-progress`) | Not adaptable: no UI plugin API | Not adaptable | Not adaptable |

Four findings change the 2026-11-23 verdicts:

1. **Antigravity hooks receive `transcriptPath` and `conversationId`**, and `Stop` carries `fullyIdle` and `terminationReason`. Capture is therefore possible there; the earlier verdict "core only" was too low.
2. **Copilot gives hooks `transcriptPath` on `agentStop`, `subagentStart`, `subagentStop` and `preCompact`, but not on `sessionEnd`**, and a plugin hook "can also read the directory it was loaded from" and write to `$COPILOT_PLUGIN_DATA`. The earlier open point (how a hook finds its folder) is half answered.
3. **Copilot hooks configured with PascalCase event names receive snake_case payloads** (`session_id`, `hook_event_name`), the shape Claude Code sends. The Claude hook scripts and the engine's `--hook` parsers may run there with an output wrapper only.
4. **Copilot's session file is readable and stable enough to decode**: see [§ Copilot session file](#copilot-session-file-observed-schema). Its core event names held from April to October 2026 while fields were added.

Google target: Antigravity CLI (owner, 2026-11-28; D1 in the plan). Gemini CLI still ships (v0.71.1, 2026-11-24) and has the richer hook set, but Google's migration guide sends its users to Antigravity and `agy plugin import gemini` does not mention hooks.

---

## Verdict scale

| Verdict | Meaning |
|---|---|
| **1:1** | Same behavior from the same source text; at most a rename or a format wrapper |
| **Adaptable** | Works through a different mechanism, or with a named loss |
| **Not adaptable** | The host has no mechanism; the feature is lost |
| **Unverified** | The documentation is silent or conflicting; a probe decides |

---

## `agent-skills`: component verdicts

Source counts: 15 skills, 14 commands, 17 agents (`plugins/agent-skills/`). The Copilot port exists (`ports/copilot/agent-skills/`: 29 skills, 17 agents); no Google port exists.

| Component | Copilot CLI | Antigravity CLI | Gemini CLI |
|---|---|---|---|
| Skills (15) | 1:1, built | 1:1, except `ux-principles` and `prompt-engineering`, which use `${CLAUDE_SKILL_DIR}`: rewrite to relative paths | 1:1; `${extensionPath}` replaces the variable |
| Commands (14) | Adaptable, built as user-only skills. **Unverified**: `disable-model-invocation` is documented for VS Code skills but not on the CLI skills page; if the CLI ignores it, the 14 command skills can fire on their own | Adaptable: `commands/` is not loaded and every skill is a slash command. **Unverified**: the current skills page documents only `name` and `description`, so user-only may not be enforceable | 1:1 as `commands/*.toml` (format conversion) |
| Agent text and delegation (17) | 1:1, built; delegation by description | 1:1: `agents/*.md`, `invoke_subagent`, fresh context, nesting to 10 | Adaptable: `agents/*.md`, a preview feature behind `experimental.enableAgents` |
| Agent model | 1:1 in intent (same Claude models). **Unverified**: the models page lists display names only, so all four ids in `COPILOT_MODELS` are unconfirmed, not only `claude-fable-5.2` | Adaptable with loss: `inherit`, `flash`, `pro`. Four Claude levels collapse to two tiers; a per-agent Claude model is not documented | Adaptable: explicit model id |
| Agent effort | **Unverified**: the port emits `reasoningEffort`, which no current page documents | Not adaptable: no field | Not adaptable (`temperature` only) |
| Tool allowlist | 1:1, enforced by `tools`. Copilot 1.0.117 (2026-11-25) added "explicit tool exposure" and made subagents respect their tool list: re-check the generated lists | Adaptable: `tools` with Antigravity ids (`view_file`, `replace_file_content`, `grep_search`, `run_command`); web tool ids are not documented | Adaptable: `tools` |
| `maxTurns` | Stated as a rule, not enforced | Stated as a rule | 1:1: `max_turns` |
| `skills:` preload | Text inlined into the agent | **Unverified**: the agent frontmatter has a `skills` field that may preload; else inline | Inline |
| `omitClaudeMd` | 1:1 through `include-custom-instructions` | **Unverified**: `inheritCustomizations` is no longer on the subagents page | Not documented |
| Offload table at session start (ADR 0032) | Adaptable, not built: `sessionStart` returns `additionalContext`. Today these users paste the table | Adaptable through a better channel: plugin `rules/` with `always_on` activation, no hook. **Unverified**: whether subagents also receive plugin rules | 1:1: the extension's context file (`contextFileName`) |
| Routing text | Generated variant, pasted by the user | Plugin `rules/` | Context file |
| `fff` MCP tools, `Skill`, `Monitor` | Dropped | Dropped | Dropped |
| Evals | None: the descriptions and delegation rules are tuned and measured on Claude only | None | None |

VS Code Copilot and the Copilot cloud agent read the same core files as the CLI (`SKILL.md` skills, `.agent.md` agents, `.github/hooks/*.json`). VS Code installs plugins (`chat.plugins.enabled`) and its page says it "also supports existing Copilot, Claude, and legacy OpenPlugin formats"; whether it installs this marketplace's Copilot port, or the Claude plugin itself, is unverified. Hooks in VS Code are a preview. Plugin support in the cloud agent is not documented.

---

## `memory`: component verdicts

The engine (`mem`, Python through `uv`) is host-neutral. Host coupling sits in the hooks, the options, the transcript decoders and the background model passes. Codex decisions that carry over are cited by ADR.

| Need | Copilot CLI | Antigravity CLI | Gemini CLI |
|---|---|---|---|
| `mem` CLI, store, search; 4 skills | 1:1 | 1:1 | 1:1 |
| 5 agents | As the `agent-skills` agents; `port.py` generates only Codex roles for `memory` today | Same, with tiers | Same |
| Session index at start | 1:1: `sessionStart` `additionalContext` (JSON, not plain stdout) | Adaptable: `SessionStart` `injectSteps` with a `systemMessage`; camelCase input | 1:1: `SessionStart` `additionalContext` |
| Index again after a compaction | Not adaptable: no `postCompact`, and `sessionStart` fires for `startup`, `resume`, `new` only | Adaptable in part: the fixed lines survive as an `always_on` plugin rule; the per-project index is not re-injected. Compaction itself is not documented | Unverified |
| Index for subagents | 1:1: `subagentStart` `additionalContext`, with a `matcher` on the agent name | Adaptable: no subagent event, so generate the three lines into each ported agent body; plugin rules reach subagents only if a probe says so | Adaptable the same way |
| Handoff before compaction | Not adaptable: `preCompact` is "notification only" | Not adaptable: no event | Not adaptable: `PreCompress` returns only a `systemMessage` |
| Compaction log | Not adaptable | Not adaptable | Not adaptable |
| Capture before compaction | Adaptable: `preCompact` gives `transcriptPath`; capture needs no hook output | Not adaptable | Adaptable: `PreCompress` exists; transcript path unverified |
| Capture and history commit at session end | Adaptable: `sessionEnd` has a 30 s default timeout and no documented cap, but no `transcriptPath`. Record the path at every `Stop` under `$COPILOT_PLUGIN_DATA`, or derive it from the session id | Adaptable with a timing loss: no session-end event. Capture on `Stop` when `fullyIdle` is true, debounced, plus the existing idle sweep at the next `SessionStart` (ADR 0038) | Adaptable: `SessionEnd` exists; transcript path unverified |
| Transcript decoding | Adaptable: a third decoder for `~/.copilot/session-state/<id>/events.jsonl`. The schema is not documented but was observed ([§ Copilot session file](#copilot-session-file-observed-schema)); decode by event name and skip unknown events, as the Codex decoder does (ADR 0038) | Adaptable: a fourth decoder for `transcript.jsonl`; schema not documented | Unverified |
| Background model passes (12 engine files resolve the `claude` binary: `grep -l 'find_claude\|which("claude")\|CLAUDE_CODE_EXECPATH'`) | Adaptable: keep the Codex rule, where capture's pass stays on `claude -p` and capture skips without the binary (ADR 0038) and only settle and corroborate have a second runner (ADR 0037); or add a `copilot -p --model … --output-format=json` runner. Each prompt costs one premium request times the model's multiplier | Same rule, or an `agy -p --output-format json --json-schema` runner; quota for headless calls is not documented | `gemini -p --output-format json` |
| Options (15 `userConfig` keys) | Adaptable: one file per option under `~/.config/agent-memory/` (built for Codex, ADR 0038). No plugin options exist | Same: plugin `variables` reach MCP configuration only | Possibly 1:1 through extension `settings`; unverified |
| `mem` on the model's PATH | Adaptable: `mem install-command` (built for Codex, ADR 0036); `bin/` on PATH is not documented | Same | Same |
| The hooks file reaches its scripts | **Unverified**: the Claude file uses `${CLAUDE_PLUGIN_ROOT}` and the Codex file `${PLUGIN_ROOT}` in each command; Copilot's docs give the behavior ("read the directory it was loaded from") but no variable for hook commands, and document `PLUGIN_ROOT` for MCP servers only. Inside a script the plugin's own path is known | **Unverified**: the 2026-11-23 reading says hooks run in the plugin root; a third-party page says v1.5.5 added `PLUGIN_ROOT` | `${extensionPath}` |
| Hooks run inside the session sandbox | Risk: with the sandbox on, hooks follow the shell's sandbox rules, so a write to a store outside the workspace may be refused | Not documented | Not documented |
| Native memory feature to keep apart | Copilot Memory: repository-scoped, opt-in, with citations | `/learn`: proposes rules or skills from session corrections | `save_memory`, `GEMINI.md` |

Carried over without change from Codex: no host can carry the compaction handoff, so the loss is common to every port and not a Copilot or Google defect.

---

## What must change in this repository

| Area | Change | Why | Size |
|---|---|---|---|
| `scripts/port.py` (1,594 lines, one file) | Move the per-target branches into one description per target, and make the per-plugin agent sources target-neutral (`SOURCE_PLUGINS` and `ROLES_DIR` know only Codex). A `Target` dataclass and a `TARGETS` tuple exist, but Copilot and Codex branches sit in about ten functions (`transform`, `Generator.commands`, `manifest`, `instructions`, `agent_file`, `catalogs`, `agents_for`, `stale_token`, both `Verifier` methods) | A third target would add a branch in each; ADR 0029 names "a third vendor is ported" as a revisit trigger | M |
| `shared/models.toml` | A Google vendor: tiers `flash` and `pro`, levels, relative cost | Agents need a model map; the catalog is the home of model facts (ADR 0029) | S |
| `port.py` outputs | Antigravity plugin (`plugin.json`, `skills/`, `agents/`, `rules/`), a tool-id map, rewrites for Claude-only names; `memory` agents for Copilot and Antigravity (only Codex roles exist) | No Google output exists | M |
| `plugins/memory` host selection | A host module per tool that owns payload field names, hook output format, transcript decoder, session folder layout, runner and instruction-file path. Today the host is decided in three unrelated ways: `MEM_HOST=codex` (read in `engine/commands/hooks.py`, `engine/commands/diagnostics.py` and five hook scripts plus `codex-options.sh`), the content of the transcript's first line (`codex_rollout.is_rollout`), and `codex_pass.refuse_codex` in the passes | Two more hosts would multiply each of the three across hooks, capture and runner | M |
| `plugins/memory/hooks/` | A hooks file per host, as `codex.json`: Copilot with PascalCase event names; Antigravity with `SessionStart` and `Stop` | Each host loads its own file | S |
| `plugins/memory/engine/capture/` | Decoders for Copilot `events.jsonl` and Antigravity `transcript.jsonl`, selected as `codex_rollout.is_rollout` is today | Capture reads transcripts | M each |
| `plugins/memory/engine/core/runner.py` | Optional `copilot` and `agy` runners beside `claude` and `codex` | Only if the owner wants passes without Claude | M |
| Docs and records | An ADR per port (amending 0015 and 0036), `platform-parity.md` refreshed by its own protocol, `ports.md`, README install blocks, changelog lines | Repository rules | S |

---

## Suggested improvements to the existing plugins and ports

Ordered by expected gain against cost. None is measured; each names its check.

| # | Suggestion | Gain | Check |
|---|---|---|---|
| S1 | Ship the offload table to Copilot through a `sessionStart` hook in the generated port, as the Claude plugin does (ADR 0032) | Copilot users stop pasting and re-pasting the table after each policy release. It needs the skip check of ADR 0032 against `copilot-instructions.md`, or users who already pasted it load it twice | A probe session shows the table once: without a paste, and with one |
| S2 | Verify the three unverified fields of the Copilot port (`disable-model-invocation`, `reasoningEffort`, the four model ids) in one probe session | The released port may be silently wrong: commands firing on their own, effort ignored, agents falling back to the session model | `copilot -p` with a custom agent, reading the session file for the model used |
| S3 | Give Copilot's hooks PascalCase event names so they receive Claude-shaped payloads | One set of hook scripts and parsers for Claude, Copilot CLI and VS Code Copilot instead of a camelCase branch | A probe hook dumps its stdin |
| S4 | Record the transcript path at every `Stop` into the plugin data folder, and let session-end capture read it from there | One capture trigger design for every host: Copilot (`sessionEnd` lacks the path), Antigravity (no session end) and Claude Code, whose `SessionEnd` budget is 1.5 s ([platform-parity.md](../platform-parity.md#memory)) | Capture finds the transcript after a session ends on each host |
| S5 | Introduce the host module in the `memory` engine before the next port, with behavior unchanged | Removes scattered `MEM_HOST` branches; each new host becomes one folder, in line with the owner ruling of 2026-11-26 on feature packages ([backlog](../backlog.md), A14) | No test assertion changes: only import paths and the package tables of `test_import_graph.py` move |
| S6 | Split `port.py` into a package with one module per target | Same reason on the generator side; the file is past the size where one reason to change holds | Generated files byte-identical before and after, and the verifier still rejects a tampered port |
| S7 | Measure the ports with the tools' headless modes (`copilot -p --output-format=json`, `agy -p --output-format stream-json`): a smoke suite of a few trigger and delegation cases | Ends the "unmeasured" limit of [ports.md](../ports.md#limits); needed before tuning descriptions for Gemini models | The suite runs and reports fired or silent per case; Copilot bills a premium request per prompt |
| S8 | Add "Agent Plugins 1.1.0 is published" to the revisit triggers of ADR 0015. The 1.1.0 working draft adds portable hooks; 1.0 covers skills and MCP only | A published 1.1.0 could let one hooks file serve several tools | A new review section in ADR 0015 |
| S9 | On hosts where subagents may start subagents (Antigravity, nesting to 10; Copilot 1.0.118 pre-release), test letting a worker delegate its own checks | Shorter coordinator turns. The routing text assumes no nesting, so this is a design change | A smoke case from S7 comparing calls and tokens |
| S10 | `plugins/memory/hooks/signal.sh` exists with tests, but neither `hooks.json` nor `codex.json` registers it | Either dead code or unfinished work; confirm with whoever owns seamless stage 4 before any port copies it | `grep -c signal plugins/memory/hooks/*.json` |

---

## Corrections for `platform-parity.md`

Apply these through that file's [Refresh protocol](../platform-parity.md#refresh) (full page text, a fresh-context fact-check), not by copying this table: the rows marked "report" rest on one researcher summary.

| Tool | Cell | 2026-11-23 | Read 2026-11-28 | Basis |
|---|---|---|---|---|
| Antigravity CLI | Verdict for `memory` | "Core only" | Core plus capture, with timing losses: hooks receive `transcriptPath`, and `Stop` reports `fullyIdle` | page text |
| Copilot CLI | Verdict for `memory` | "how a plugin hook finds its folder is not documented" | Data folder documented; a root variable for hook commands still is not | page text |
| Copilot CLI | Session file | not covered | Schema observed, see [§ Copilot session file](#copilot-session-file-observed-schema) | local files |
| Copilot CLI | Plugin root in hooks | not documented | "A hook can also read the directory it was loaded from … and a plugin hook can write to its data directory (`$COPILOT_PLUGIN_DATA`)"; no root variable for hooks | page text |
| Copilot CLI | Hook payload | not listed | `transcriptPath` on `agentStop`, `subagentStart`, `subagentStop`, `preCompact`; `sessionEnd` has `sessionId`, `cwd`, `reason` | page text |
| Copilot CLI | `sessionEnd` | no detail | On `/clear` the hooks run detached with their full `timeoutSec`; a detached hook still running at CLI exit is terminated | page text |
| Copilot CLI | Per-agent model | any listed model id | The models page lists display names only; the agents page shows provider-qualified ids and a `model-policy` field | report |
| Copilot CLI | Releases | v1.0.114 | 1.0.117: explicit tool exposure for custom agents, subagents respect their tool list; 1.0.118-0: subagents that start subagents | report |
| Antigravity CLI | Hook payload | not listed | Common stdin fields `conversationId`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`, `modelName`, `lastUserInput`; `Stop` adds `terminationReason`, `fullyIdle` | page text |
| Antigravity CLI | Per-agent model | `inherit`, `flash`, `flash_lite`, `pro` | `inherit`, `flash`, `pro` | report |
| Antigravity CLI | Skill frontmatter | five fields | The skills page documents `name` and `description` only | report; conflict |
| Antigravity CLI | Rules | loaded from the plugin | Activation modes `always_on`, `model_decision`, `glob`, `manual` | report |
| Antigravity CLI | Releases | v1.5.7 | 1.5.16: `~/.agents/skills` discovery; 1.5.19: `agy conversations list` | report |
| Gemini CLI | Release | v0.70.0 | v0.71.1 (2026-11-24); extension agents are a preview with `max_turns` | report |
| Standard | Agent Plugins | 1.0 | "the 1.1.0 working draft adds portable hooks" | page text |

---

## Evidence and limits

| Source | What it gave | Limit |
|---|---|---|
| Code inventory, 2026-11-28 | `port.py` structure, `memory` host coupling, component counts | Two counts in the first inventory were wrong and were corrected by listing the folders |
| Seven documentation readings, 2026-11-28 | Vendor cells | Summaries of fetched pages, not verbatim; vendor pages carry no dates |
| Page text checked directly, 2026-11-28 | Copilot hooks reference, Copilot plugin reference, Antigravity hooks page, Agent Plugins README | The rows marked "page text" above |
| This machine | Four Copilot `events.jsonl` files (2026-04 to 2026-10), read for event names and field names only; `agy`, `gemini` and `codex` are not installed | The sessions come from the Copilot agent inside VS Code (`producer: copilot-agent`), the newest from version 1.0.95, not from a current CLI; Antigravity's transcript format remains unknown |

Pages: [Copilot hooks](https://docs.github.com/en/copilot/reference/hooks-reference), [Copilot plugins](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference), [Copilot headless](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference), [Copilot requests](https://docs.github.com/en/copilot/concepts/billing/copilot-requests), [VS Code agent plugins](https://code.visualstudio.com/docs/agent-customization/agent-plugins), [VS Code hooks](https://code.visualstudio.com/docs/agent-customization/hooks), [Antigravity hooks](https://antigravity.google/docs/hooks?tab=cli), [Antigravity subagents](https://antigravity.google/docs/subagents?tab=cli), [Antigravity build plugins](https://antigravity.google/docs/build-plugins/), [Antigravity headless](https://antigravity.google/docs/cli/headless/), [Gemini CLI extensions](https://geminicli.com/docs/extensions/reference/), [Gemini CLI hooks](https://geminicli.com/docs/hooks/reference/), [Agent Plugins spec](https://github.com/agentplugins/agent-plugins-spec).

## Copilot session file: observed schema

Read on 2026-11-28 from four files under `~/.copilot/session-state/<session-id>/events.jsonl` (0.2 to 10 MB), two compared in full: one from 2026-04 and one from 2026-10 (`copilotVersion` 1.0.95). Field names only; no content was read. A session folder also holds `workspace.yaml` and `checkpoints/index.md`.

| Part | Observed |
|---|---|
| Line envelope | `id`, `parentId`, `timestamp`, `type`, `data` |
| Session | `session.start` (`sessionId`, `selectedModel`, `copilotVersion`, `context` with `cwd`, `gitRoot`, `repository`, `branch`); `session.shutdown` (`shutdownType`, `totalPremiumRequests`, `modelMetrics`) |
| Conversation | `user.message` (`content`, `transformedContent`); `assistant.message` (`content`, `reasoningText`, `model`); `assistant.turn_start`, `assistant.turn_end`; `system.message` |
| Tools | `tool.execution_start` (`toolName`, `arguments`, `toolCallId`); `tool.execution_complete` (`result`, `success`, `error`) |
| Hooks | `hook.start` (`hookType`, `input`) and `hook.end` (`output`, `success`) for every hook run. Nine hook types appear in one October session. Input keys per type match the documentation: `sessionStart` has `sessionId`, `cwd`, `source`, `initialPrompt`; `agentStop` adds `transcriptPath` and `stopReason`; `sessionEnd` has `sessionId`, `cwd`, `reason` and no `transcriptPath` |
| Subagents | A `parentAgentTaskId` field on `user.message`; how subagent conversations are stored is not established |
| Drift, April to October | Event names above unchanged; new fields on most events; new events `hook.*`, `permission.*`, `session.usage_record` |

Two uses: the decoder can attribute a session to a project from `session.start`, which the sweep needs (ADR 0038); and a probe can read each hook's exact payload and output from the session file instead of logging them from the hook.

Not established by any source: whether Antigravity's IDE runs plugin hooks; the multipliers of Copilot's cheapest models; whether a hook-started process outlives a Copilot or Antigravity session; whether either tool can run a headless prompt with plugins and hooks off, which a background pass needs so that it does not trigger capture on itself.
