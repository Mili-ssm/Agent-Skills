# Memory plugin: Codex port, core scope

Status: done 2026-11-27, released in memory 0.17.0 (ADR 0036 `## Review 2026-11-27`); code landed before the stage 4 kill read at the owner's request · Decision: [ADR 0036](../../adr/0036-memory-codex-port-core.md)

Owner, 2026-11-27: design and ADR now, code after the kill read (a failed read would waste the port); first version is the **core**: `mem`, the `memory` skill, the session and subagent index hooks, configuration by file. No background passes, no agents, no compaction handoff.

## Evidence: probes of 2026-11-27

Run with `codex-cli 0.171.0-alpha.13.2`, the binary bundled in the owner's VS Code extension (`~/.vscode/extensions/openai.chatgpt-<version>-linux-x64/bin/linux-x86_64/codex`), in a throwaway `CODEX_HOME` with a probe plugin from a local marketplace (`codex plugin marketplace add <dir>`, `codex plugin add probe@<market>`), driven by `codex exec`. The owner's `~/.codex` was not touched.

| Question | Observed | How |
|---|---|---|
| Do plugin hooks run in the CLI (the docs say lifecycle hooks are supported "for plugins installed manually in Codex desktop")? | Yes, once trusted: `SessionStart`, `SubagentStart` and `SessionEnd` all fired | hook appending to a log |
| Without trust? | No hook ran; `exec` gave no warning | same run without `--dangerously-bypass-hook-trust` |
| Does `SessionStart` output reach the model? | Yes, both plain stdout and JSON `hookSpecificOutput.additionalContext`, each as a `developer` message | markers found in the session rollout (`$CODEX_HOME/sessions/…/rollout-*.jsonl`); the model itself refused to quote them ("private instructions") |
| Hook environment | `PLUGIN_ROOT` = installed copy (`$CODEX_HOME/plugins/cache/<market>/<plugin>/<version>`), `PLUGIN_DATA` = `$CODEX_HOME/plugins/data/<plugin>-<market>`, plus `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA`; the session's own `PATH` | `env` in the hook |
| Is the plugin's `bin/` on the model's shell `PATH`? | No (`command not found`) | model ran `command -v probe-bin` |
| Can the Codex manifest point at its own hooks file? | Yes: `"hooks": "./hooks/codex.json"` in `.codex-plugin/plugin.json` runs that file and **not** `hooks/hooks.json` | decoy command in `hooks/hooks.json` never ran |
| `codex exec` pitfall | waits on an open stdin ("Reading additional input from stdin…"): give it `</dev/null` | a run hung until `timeout` |

Docs read the same day (researcher reports, sources in [platform-parity.md](../../platform-parity.md#memory)): `PreCompact`/`PostCompact` ignore plain stdout and take no `additionalContext`; `SessionEnd` defaults to 1 s, at most 3 s; custom agents are standalone TOML files (`~/.codex/agents/`), no `tools` field, plugin-shipped agents undocumented; no plugin options (the owner's `config.toml` holds only enable flags).

## Design

| Need | Codex core | Why |
|---|---|---|
| Where the port lives | `plugins/memory/` itself: add `.codex-plugin/plugin.json` (`skills: "./skills"`, `hooks: "./hooks/codex.json"`) | the manifest's `hooks` field keeps Claude's `hooks.json` out of Codex (probe); no copy of the engine, so no generated duplicate to keep in step |
| Marketplace | a `memory` entry with `path: "./plugins/memory"` in `.agents/plugins/marketplace.json`, written by `scripts/port.py` (the file is generated) | the owner already installs `agent-skills@mili-ssm` from this marketplace in Codex |
| Hooks | `hooks/codex.json`: `SessionStart` → `session-index.sh`; `SubagentStart` → `subagent-start.sh` | the only two the core needs; both already exit 0 with no `CLAUDE_PLUGIN_OPTION_*` set |
| Reaching `mem` | a user command: `mem install-command` (once) writes a launcher to `~/.local/bin/mem` that runs `bin/mem` of the plugin root the last `SessionStart` hook recorded in the plugin's state folder; until then the session text gives `$PLUGIN_ROOT/bin/mem` | owner, 2026-11-27: models call `mem`, never `uv` or a full path, in every tool; `bin/` is not on Codex's `PATH` (probe); a recorded root keeps the command current after updates |
| Store and options | none in Codex: `mem` resolves the store as today (`~/.config/agent-memory/store`, else the default store); defaults for every other option | Codex has no plugin options; one store per machine means Claude and Codex share the memory |
| Text that names Claude parts | session and subagent texts drop lines about Claude agents, `memory-*` subagents and the offload table when the host is Codex | those names do not exist in Codex and would send the model to nothing |
| Trust | the owner trusts the hooks once per plugin version (a changed script needs a new review) | documented Codex behavior; the README says so |
| Codex's own memories (`[memories]` on in the owner's config) | left as they are | mirrors ADR 0023's stance on Claude's auto memory |

Host detection: in a hook, Codex sets `PLUGIN_ROOT` (and `CLAUDE_PLUGIN_ROOT`), Claude is assumed not to set `PLUGIN_ROOT`; task 1 must observe that absence before task 3 builds on it, else detection moves to an explicit `--host codex` in `hooks/codex.json`; `session-index.sh` passes a `--host codex` flag to `mem session-index` when it is set.

## Tasks (after the kill read passes)

Amended after the pre-mortem of 2026-11-27 (each claim checked in the code): `port.py --check` accepts only `agent-skills` in the Codex catalog; `skills/memory/SKILL.md` and the index text (`engine/commands/hooks.py`) send the model to Claude agents and "auto memory"; the owner's Codex marketplace is git-sourced from GitHub, so it sees only what `main` holds.

- [x] 1. Probe before code (results in § Task 1 results), in a throwaway `CODEX_HOME` with a local marketplace on the dev tree: the model runs `$PLUGIN_ROOT/bin/mem search x` under the **default sandbox** (no bypass flags: `uv` writes `~/.cache/uv`, `mem` writes `~/.local/state/agent-memory`, both outside the workspace); hook stdin logged (`cwd`, `source` values); `ls -l` and `du` of the cached copy (`+x` kept, size with `engine/tests`, `evals/`); one byte changed in a hook script, then a new session (is trust revoked?); `SubagentStart` text found in the subagent's rollout; `PLUGIN_ROOT` absent in a Claude hook; `command -v mem` and `echo $PATH` inside a Codex session (is `~/.local/bin` on it?). If `mem` is blocked by the sandbox, decide before coding between `UV_CACHE_DIR`/state inside writable roots, documented `writable_roots`, or the packaged engine (`uv tool install`, ADR 0036).
- [x] 1b. `mem install-command [--remove]` (ruling: the `mem.py` line ceiling rose by 3 lines for its registration; a parser registry outside `mem.py` was not worth it): the launcher, the root record written by both hosts' `SessionStart` hooks, and a session-text line when the command is missing or points at a removed copy. Check: engine tests for install, remove, a stale root; `mem` runs from a shell without the plugin's `PATH`.
- [x] 2. Manifest and hooks file: `.codex-plugin/plugin.json`, `hooks/codex.json` (commands prefixed `MEM_HOST=codex`; `SessionStart` with no matcher, or one listing `startup` and the other sources once seen). Check: probe run shows the index in the rollout; `claude plugin validate plugins/memory` still passes.
- [x] 3. Host-aware texts: `mem session-index --host codex` covers `_INDEX_RULES`, the status-checker line, the curation-due line and the exception fallback; the shell fallback in `session-index.sh` and the subagent JSON say `mem` when the user command is installed, else the absolute path (escaped); "auto memory" maps to Codex's memories or is dropped; `_log_hook` entries gain `host`, so kill reads can filter. Skills: `skills` points at a Codex-safe set, or each skill gets host-neutral wording; a test greps the shipped Codex text for `memory-researcher|memory-recorder|memory-curator|claude -p|auto memory`. Check: engine tests (`uv run --with pytest --with pyyaml --with pytest-xdist pytest plugins/memory/engine/tests -q -n auto`) with a case per host.
- [x] 4. Marketplace entry: generalize `catalogs()` and the catalog check in `scripts/port.py` to one folder per entry; `validate.py` checks `plugins/memory/.codex-plugin/plugin.json` (keys, `hooks` path exists, description equal to Claude's). Check: `python3 scripts/validate.py`, `uv run --with pytest pytest scripts/tests -q` with a test for the memory entry.
- [x] 5. (Automated part passed 2026-11-27: `codex exec` from a local marketplace on `git archive HEAD`, minimal environment, `writable_roots` set: index with the hint reached the model, which ran `mem search` by full path and found the project memory; launcher install, fallback and refusal checked by hand.) (Set up on the owner's machine 2026-11-27: Codex marketplace `mili-ssm` re-added with `--ref feat/memory-codex-port` and `memory@mili-ssm` installed; `writable_roots` added to `~/.codex/config.toml` (backup `config.toml.bak-2026-11-27`); `~/.local/bin/mem` installed. After the trial: re-add the marketplace without `--ref` once the release reaches `main`.) Owner trial in the VS Code extension **from a local marketplace on the dev tree** (or a pushed branch, if `codex plugin marketplace add --ref` serves it), before any merge to `main`: trust the hooks, open a session in a project with `.memory/`, ask a question the memory answers. Check: the owner sees the index and `mem search` runs without per-call approval; the hook log has `host=codex` entries.
- [x] 6. Docs and release, after the trial (README § Codex, CHANGELOG and platform-parity done 2026-11-27; release and ADR review left): plugin README § Codex (install, trust, re-trust after each update, limits), CHANGELOG `[Unreleased]` (flag changes to shared hook scripts), `docs/platform-parity.md` verdict, backlog row; add a `## Review` to ADR 0036 with the trial result.

## Task 1 results (2026-11-27)

Same method as § Evidence, with a `git archive` copy of the tracked `plugins/memory` (what a git marketplace installs) and a probe `hooks/codex.json` that runs `session-index.sh` and `subagent-start.sh`.

| Question | Observed |
|---|---|
| `mem search` under `-s workspace-write`, no bypass | **fails**: `uv` cannot take its lock (`Read-only file system` at `~/.cache/uv`); writable roots are only the workdir, `/tmp`, `$TMPDIR` |
| Same with `-c 'sandbox_workspace_write.writable_roots=["~/.cache/uv","~/.local/state/agent-memory","~/.local/share/agent-memory"]'` (absolute paths) | **works**: project and global memories returned. Chosen fix: the README gives this `config.toml` entry (plus the store folder when `store` is set); no packaged engine needed |
| Hook stdin | `source: "startup"`, `cwd` = the session folder (project `.memory/` found) |
| Index and subagent text | the index reaches the main session; the subagent's rollout holds the three lines and not the index |
| Cached copy | 4.3 MB, `+x` kept |
| Model shell `PATH` with a minimal environment (`env -i PATH=/usr/bin:/bin`) | a login shell: `~/.local/bin` is on it, so `mem install-command` reaches Codex |
| Host detection | decided without a probe: `hooks/codex.json` sets `MEM_HOST=codex` on its commands, so nothing rests on `PLUGIN_ROOT` being absent in Claude |
| Trust revoked by a changed script | not testable in `exec` (only the bypass flag); moves to task 5 |

## Deferred findings (review of `mem install-command`, 2026-11-27, all low)

- `subagent-start.sh` keeps two copies of the message (one heredoc per host); one unquoted heredoc would hold one copy.
- Launcher record parsing is untested for CRLF and roots with spaces (both behaved when run by hand).
- `launcher_missing()` checks only `~/.local/bin/mem` while `subagent-start.sh` uses `command -v mem`; a custom `--bin-dir` off `PATH` makes the Codex hint suggest the default folder.

## Outside the core (later, each its own decision)

Background passes through `codex exec` (six `claude -p` call sites, `engine/core/headless.py` plus `research/` and `corroborate/`); the four agents as TOML; the compaction handoff (no channel: `PreCompact` ignores output); capture and history commit at `SessionEnd` (3 s cap: detached process); hooks for Copilot and Antigravity.

## Kill criteria

- The owner does not use memory from Codex in the two weeks after task 6 (the release: before it, the git-sourced marketplace does not serve the port).
- Trusting the hooks fails in the VS Code extension, or must be redone on every session.
- `mem search` cannot run in the extension's default sandbox without per-call approval and no fix inside the plugin works: stop at task 1 and re-plan.
- The hook log shows no `host=codex` index entries for 3 or more days while the owner uses Codex: hooks or trust are silently off; investigate before judging use.
- Making the skills Codex-safe needs more than one line per skill: a Codex skill set becomes its own decision.
