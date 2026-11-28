# Parity plan: `agent-skills` and `memory` on Copilot and Antigravity

Status: proposed, not started; owner rulings of 2026-11-28 on D1, D2, D5 and D6, with D3 and D4 open; amended once after a pre-mortem (2026-11-28) · Date: 2026-11-28 · Evidence: [parity audit](../../studies/2026-11-28-google-copilot-parity-audit.md)

Goal: a user of GitHub Copilot CLI or Google Antigravity CLI installs `agent-skills` and `memory` from this marketplace and gets every feature the audit rates 1:1 or adaptable, with each loss stated in the README. Features rated not adaptable (compaction handoff, compaction log, mods) are out of scope.

Each stage ends with something usable and has its own stop condition, so the work can stop after any stage. Stages 3 and 5 are refactors with behavior unchanged; the others add outputs.

## Owner decisions

| # | Decision | Ruling (owner, 2026-11-28) or recommendation | Reason |
|---|---|---|---|
| D1 | Google target | **Ruled: Antigravity CLI only** | Google's migration guide sends Gemini CLI users there, and `agy plugin import gemini` does not mention hooks. Gemini CLI only if an enterprise user asks |
| D2 | Order | **Ruled: `agent-skills` on both tools first (stages 1, 2 and 4); `memory` (stages 5 to 7) is decided after them** | Skills and agents need no hooks, so they carry the least risk; `memory` is the costly part. The ruling sets the order; it does not rule on the refactors (D4) |
| D3 | Background model passes on these hosts | Open. Recommendation: keep the Codex rule: capture's pass stays on `claude -p` and capture skips without the binary (ADR 0038); no new runner | A `copilot -p` pass costs a premium request per prompt and neither tool documents how to run a headless prompt with hooks off. Decide with stage 6 |
| D4 | Refactors before the third target (stages 3 and 5) | Open. Recommendation: do both; without stage 3, stage 4 adds a third set of branches to `port.py` instead | ADR 0029 names a third vendor as its revisit trigger; without them each port adds branches in about ten generator functions and in five hook scripts |
| D5 | Access for the probes of stage 1 | **Answered: Copilot through VS Code; no Antigravity** | The Copilot probes run in the owner's VS Code Copilot (its agent writes the session files the audit read); `copilot` on the development machine is VS Code's shim (`/usr/share/code/bin/copilot-shim/copilot`) and printed "GitHub Copilot CLI was not found" on 2026-11-28. No Antigravity probe can run |
| D6 | Who uses the ports | **Answered: the owner will not use Antigravity; the port is for other people** | So the Antigravity port has no local tester: it ships from documentation with that limit stated, as the Copilot and Codex ports did (ADR 0015), and its `memory` stage waits for a tester. Who uses `memory` on Copilot is asked again before stage 5 |

## Stages

Sizes: S under a day of agent work, M one to three days, L more.

### Stage 1: probes (gate for the Copilot stages and every `memory` stage)

Method of the [Codex probes](2026-11-27-memory-codex-port.md#evidence-probes-of-2026-11-27): a throwaway home folder, a probe plugin from a local marketplace, hooks that append their stdin and environment to a log.

- [ ] Copilot probe session in the owner's VS Code Copilot (D5), and in the CLI if the owner installs it; record an evidence table in this file. First row: does VS Code install this marketplace's Copilot port (`chat.plugins.enabled`), or only the CLI. Check: every row below has an observed value, or says which of the two hosts it could not be observed on.
  - Hook environment and working directory: is there a plugin root variable; where does `$COPILOT_PLUGIN_DATA` point.
  - PascalCase event names: the exact stdin of `SessionStart`, `SubagentStart`, `Stop`, `PreCompact`, `SessionEnd`.
  - `sessionStart` and `subagentStart` `additionalContext` reach the model, including for the built-in general-purpose agent.
  - With the sandbox on: can a hook write to a store outside the workspace and start a process that outlives the session.
  - `disable-model-invocation` on a skill, `reasoningEffort` on an agent, and the four model ids of `COPILOT_MODELS`.
  - `events.jsonl` from a current CLI against the [schema observed](../../studies/2026-11-28-google-copilot-parity-audit.md#copilot-session-file-observed-schema) in older sessions; where subagent conversations and compaction markers are stored. The session file records each hook's input and output (`hook.start`, `hook.end`): read payloads there.
  - `copilot -p`: do plugin hooks fire, and is there a way to turn them off.
  - Manifest and hooks file chosen in a folder that holds `.claude-plugin/` beside others (`memory` is served from its source folder): if Copilot loads the Claude `hooks.json`, its plain-text output and `${CLAUDE_PLUGIN_ROOT}` commands fail without a visible error. Also whether it loads the Claude `agents/*.md` directly, which would duplicate generated agents.
  - How a hook command line expands: an environment prefix (`MEM_HOST=x …`) and the variable that resolves the script path.
  - `uv` and the user's `PATH` in the hook environment; a cold `uv` start against the `sessionStart` timeout.
  - Whether `events.jsonl` is flushed when `Stop` and `sessionEnd` fire.
  - Premium requests charged for a subagent call, since the offload policy delegates often.
- [ ] Antigravity CLI probe session, same method. Not runnable today (D5): it runs when a tester with Antigravity appears, and stage 4 does not wait for it. Check: every row has an observed value.
  - Hook working directory and environment (`PLUGIN_ROOT`); non-zero exit; timeout behavior.
  - `SessionStart` `injectSteps` reaches the model; `Stop` payload at turn end and at exit.
  - Plugin `rules/` with `always_on`: loaded for the main agent and for subagents.
  - Agent frontmatter: `skills` preload, `inheritCustomizations`, a Claude model per agent, the built-in tool ids including web search and fetch.
  - Skill frontmatter: is `disable-model-invocation` honored.
  - The schema of `transcript.jsonl`, and whether subagent conversations are in it.
  - `agy -p`: do plugin hooks fire; `--json-schema` output.
  - Whether `agy plugin install` takes a plugin from a subfolder of a git repository, and in which catalog format.
  - Whether `transcript.jsonl` is flushed when `Stop` fires; whether a hook-started process outlives the session, with the sandbox on and off.
- [ ] Refresh [platform-parity.md](../../platform-parity.md) by its own protocol, starting from the audit's correction table. Check: its "Verified" date moves and its "Not verified" list shrinks.

Stop the `memory` stages and the stage 2 hook for a host if: its plugin hooks do not run from an installed plugin, hook output cannot reach the model, or the sandbox refuses store writes from hooks and no setting inside the plugin fixes it. Stage 4 needs no hook and continues. State a premium-request budget before the Copilot probes and stop at it.

### Stage 2: Copilot port of `agent-skills`, fixes (S)

- [ ] Fix whatever stage 1 shows wrong among the three unverified fields (audit S2). Check: `python3 scripts/port.py --check` and a probe session using the regenerated port.
- [ ] Ship the offload table through a `sessionStart` hook in the generated port (audit S1), with the skip check of ADR 0032 against `copilot-instructions.md` so the table loads once per session across both plugins; the README keeps the paste route for users with hooks off. Check: a probe session shows the table once, without a paste and with one. Needs an ADR review section (0015, 0032), a line in the `agent-skills` changelog, and the new hook file in CLAUDE.md § Generated files.

No Claude eval is needed: only `port.py` and the ports change (CLAUDE.md § Eval protocol).

### Stage 3: generator refactor (M)

- [ ] `scripts/port.py` becomes a package with one module per target and no target branch outside it (audit S6); `SOURCE_PLUGINS` and `ROLES_DIR`, which know only Codex, become per-target, because stages 6 and 7 generate `memory` agents for other targets. `scripts/port.py` stays as the entry path (`validate.py` runs it by path). Check: generated files byte-identical before and after; the verifier still rejects a tampered port (rerun the tamper tests of ADR 0015 on both sides, because `--check` passing does not prove the moved verifier is as strict); `uv run --with pytest pytest scripts/tests -q` with assertions unchanged. `test_port.py` patches attributes of `port` 13 times, so its patch targets move with the code: keep that edit in its own commit.

### Stage 4: Antigravity port of `agent-skills` (M)

- [ ] ADR: third target, amending 0015 and 0029; the model tier map and its losses (no effort, no turn limit, two tiers).
- [ ] Google vendor in `shared/models.toml`; generated `ports/antigravity/agent-skills/` with skills, commands as skills, agents, and the offload and routing text as plugin rules. Check: `port.py --check`, `validate.py`, and each generated manifest, agent and rule file holds only fields the Antigravity pages document. The live check (an install where one skill fires and one agent is invoked) runs when a tester appears.
- [ ] README install block, `ports.md` mapping column, changelog line.

Without an Antigravity probe (D5), the port ships labeled "built from documentation, not run" in the README and `ports.md`, with the unverified cells of the audit listed and a request to Antigravity users to report. Each command skill's description starts with the rule that only the user's slash invocation runs it, because user-only cannot be enforced from the documented frontmatter.

Stop if: a tester reports that command skills fire on their own; then ship skills and agents without the 14 commands.

### Stage 5: `memory` host module (M)

Stages 5 to 7 are not approved: the owner decides on them after stages 1 to 4 (D2).

- [ ] One host module per tool in `plugins/memory/engine` owning payload names, hook output format, transcript decoder, session folder layout, runner and instruction-file path; `claude` and `codex` move into it with behavior unchanged (audit S5). It replaces all three host switches (`MEM_HOST`, the first-line sniff of `codex_rollout.is_rollout`, `codex_pass.refuse_codex`) and the `MEM_HOST` branches of the five hook scripts. Check: no test assertion changes. The tests import or patch code that moves (`core.codex_pass` in two test files, `runners.find_codex`) and `test_import_graph.py` pins the package set, so import paths and its `PLANNED_PACKAGES` and `PACKAGE_DEPENDENCIES` tables are edited in a separate first commit; old module paths may re-export for one release.

Start only after both: the branch `feat/memory-seamless-stage-4` is merged (as of 2026-11-28 it edits `test_import_graph.py` and files under `engine/commands/` and `engine/core/`), and the memory kill read of 2026-12-01 is recorded (a failed read would waste every `memory` stage).

### Stage 6: `memory` on Copilot CLI (M core, M capture)

- [ ] ADR amending 0036 and 0015 (0015 says the catalogs list only `agent-skills`; only Codex was amended): scope, losses (index after compaction, handoff, compaction log), D3.
- [ ] Core: a Copilot hooks file (session index, subagent index), options from config files, `mem install-command`, the five agents generated by `port.py`, README § Copilot. Check: a live session shows the index, `mem search` runs, a subagent gets its lines.
- [ ] Capture: record the transcript path at `Stop` (audit S4), capture at `preCompact` and `sessionEnd`, a decoder for `events.jsonl` with synthetic fixtures in the observed shape (never commit a real session: it holds the user's prompts). Check: the decoder's extract lines for a synthetic `events.jsonl` fixture equal the expected lines written in the test, as `test_codex_rollout.py` does for rollouts (the lessons themselves come from a model pass and are not comparable run to run); a session file that fails to decode is skipped with a log line, not a crash; one live capture is read by hand.
- [ ] Release: changelog lines, README § Copilot, the new generated paths in CLAUDE.md § Generated files, then the release steps of README § Develop (users get only what `main` holds, ADR 0027).

### Stage 7: `memory` on Antigravity CLI (M core, M capture)

Waits for a tester with Antigravity (D6): a hook-driven port cannot be verified from documentation.

- [ ] ADR amending 0036 and 0015, same content as stage 6 for this host.
- [ ] Core: `SessionStart` index through `injectSteps`, the fixed lines as a plugin rule, the subagent lines generated into each ported agent body, config-file options, agents. Check: as stage 6.
- [ ] Capture: `Stop` with `fullyIdle`, debounced, plus the idle sweep at the next `SessionStart`; a decoder for `transcript.jsonl`. Check: as stage 6.
- [ ] Release: as stage 6, for this host.

### Stage 8: measurement (S, can run any time after stage 2)

- [ ] A smoke suite over the headless modes (audit S7): three to five trigger and delegation cases per tool, fired or silent per case, recorded in an ADR review section. Check: each case gives the same verdict in 2 of 2 runs, else it reruns at 6 (CLAUDE.md § Eval protocol). Budget: state the premium-request cost before running it and stop at it.

## Order and dependencies

```
1 probes ──┬─> 2 Copilot fixes ───────────────> 8 measurement
           ├─> 3 generator refactor ─┬─> 4 Antigravity agent-skills
           │                         ├─> 6 (memory agents and catalog for Copilot)
           │                         └─> 7 (memory agents for Antigravity)
           └─> 5 host module ────────┬─> 6 memory on Copilot
                                     └─> 7 memory on Antigravity
```

Stages 2, 3, 4, 6 and 7 all edit the generator, so they run in that order, one at a time. Stage 5 touches only `plugins/memory`; once the owner approves the `memory` stages (D2) and its two start conditions hold, it can run beside stages 2 to 4. A change to `user-config/offload-policy.md` on another branch regenerates `ports/`: rebase before measuring a byte-identical check.

## Kill criteria for the whole plan

- Stage 1 cannot run within two weeks of the owner's go (no access): close the plan, keep the audit.
- After stage 6, the user of `memory` on Copilot (to be named before stage 5, D6) runs fewer sessions from Copilot in two weeks than the count the stage 6 ADR sets (the rule of the Codex port plan, made countable): skip stage 7.
- The memory kill read of 2026-12-01 fails: drop stages 5 to 7.
- A vendor release changes the hook contract during a stage: return to stage 1 for that host.

## Not in this plan

Gemini CLI (D1), runners on `copilot -p` and `agy -p` (D3), nested delegation (audit S9), any change to the Claude plugin's behavior, the mods.
