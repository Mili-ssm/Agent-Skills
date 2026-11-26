# usage-ledger mod Implementation Plan

Status: unknown · no `plugins/usage-ledger`, branch or pull request found, and no backlog entry; never executed or not recorded

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Before Task 1, run `agent-skills:pre-mortem` on this plan (owner's working agreement).

**Goal:** A new opt-in mod, `usage-ledger`, that shows the tokens spent by the main agent and its subagents in this session, at a verbosity the owner picks, to judge how offloading performs.

**Architecture:** A separate plugin under `plugins/usage-ledger/`, built like `plan-progress` (one `hooks/register.tsx` entry, pure logic in `.ts` files). It listens to `turn.complete` (token usage), `agent.spawn` (subagent type and model), `tool.call` (`Agent` dispatches, `Skill` calls) and `session.append` (the owner's prompt resets the "since last message" ledger). Settings persist in `$.store` and change through `/usage-ledger <args>`. Output goes to the command's text reply (every surface) and to a pane beside the chat.

**Tech Stack:** TypeScript/TSX mod hooks API (`claude-code`, `claude-code/testing`), `claude plugin test`.

**Spec:** this file, § Design (owner decisions in conversation, 2026-11-25). No separate spec.

## Current state and where to resume

| Task | State |
| --- | --- |
| 0 Branch | pending |
| 1 Skeleton + probe | pending |
| 2 Ledger model | pending |
| 3 Settings | pending |
| 4 Event wiring | pending |
| 5 Views | pending |
| 6 Skill tokens | pending (needs the Task 1 probe answers; so does Task 4) |
| 7 Price (optional) | pending |
| 8 Docs, ADR, marketplace | pending |

## Design (owner decisions, 2026-11-25)

| # | Decision | Kind |
| --- | --- | --- |
| D1 | A new mod, not a setting inside `tool-fold`: enabling or disabling the plugin is the on/off switch; `tool-fold` stays untouched (its `agents.tsx` split, backlog A8, is pending and must not be mixed in) | technical, soft (revisit if the owner wants it on `tool-fold`'s main card) |
| D2 | Count only the main agent and subagents. Exclude mod side calls (`$.model.complete` from any mod) and loops the engine does not list: reuse `tool-fold`'s rule, an `agentId` counts only if `$.agent.list()` lists it (`plugins/tool-fold/hooks/cycle.ts`, `isListedLoop`) | functional, hard |
| D3 | Verbosity `level`: `session` (whole session) or `last` (whole session plus "since your last message") | functional, hard |
| D4 | Breakdown is independent of the level and applies to every block shown: `agent` and `model` are separate on/off flags; both on shows both tables | functional, hard |
| D5 | Extras, each an on/off flag, modular: `dispatches` (Agent calls, total and per subagent type), `calls` (turn counts per agent and per model, shown as a column of the breakdown tables), `skills` (count per skill name and, if observable, tokens; Task 6) | functional, hard |
| D6 | Tokens are shown in four classes, never one total alone: input, cache write, cache read, output. Cache reads cost about a tenth of input, so a single total misleads (study 2026-11-23: main session 47% of weighted tokens, 70% of dollars) | functional, hard |
| D7 | Price is an optional flag `price`, off by default, computed from a dated table in the mod (Task 7). Tokens are the primary datum | functional, soft |
| D8 | Defaults: `level=session`, `agent=off`, `model=off`, all extras off. Settings persist across sessions in `$.store` | technical, soft |
| D9 | UI text in Spanish (like `tool-fold`); code, identifiers, docs, commits in English | hard (owner's language rule) |
| D10 | A "turn" is one `turn.complete` event. Whether that is one API request or a whole agent turn is unverified until the Task 1 probe; label the column `turnos` and document what it counts | technical, soft |

### Command grammar (`/usage-ledger`)

| Input | Effect | Reply |
| --- | --- | --- |
| (empty) | opens the pane | the report as text |
| `level session` \| `level last` | sets `level` | `nivel: …` plus the report |
| `agent on\|off`, `model on\|off`, `dispatches on\|off`, `calls on\|off`, `skills on\|off`, `price on\|off` | sets that flag | the new settings line plus the report |
| `settings` | none | the settings line |
| `reset` | clears both ledgers (not the settings) | `contadores a cero` |
| `debug` | none | raw counters and the last 5 raw events (Task 1 probe) |
| anything else | none, settings unchanged | the help text listing this grammar |

### Report layout (text; the pane draws the same rows with `Box`/`Text`)

```text
Consumo · sesión            in 12k · cw 80k · cr 2.1M · out 45k
Desde tu último mensaje     in 1.2k · cw 9k · cr 310k · out 4k      (level=last only)
  Por agente                                         turnos   (agent=on; turnos if calls=on)
    principal · opus-5-5    in … · cw … · cr … · out …   12
    implementer · sonnet-5-5 ×2   …                       9
  Por modelo                                                  (model=on)
    opus-5-5                …                            12
Dispatches: 5 · implementer 2 · check-runner 3                (dispatches=on)
Skills: 3 · writing-plans 1 · memory 2 · ~14k tokens          (skills=on; tokens only if Task 6 finds a source)
Precio lista API: $4.12 (tabla 2026-11-25)                    (price=on)
```

The breakdown tables appear under each block shown (session, and since-last when `level=last`).

## Global Constraints

- New plugin at `plugins/usage-ledger/`, version `0.1.0` in `.claude-plugin/plugin.json` only (never in a marketplace entry); `CHANGELOG.md` with the heading format `validate.py` requires (see `plugins/plan-progress/CHANGELOG.md`).
- No edits under `plugins/tool-fold/` or `plugins/plan-progress/`. Copy helpers you need (`family`-style model naming, `formatTokens`) into the new mod; a cross-plugin import would couple two independently installed plugins.
- Model key in tables: the model id without the `claude-` prefix (`opus-5-5`), not the family.
- Agent row key: `<name> · <modelKey>`, where name is `principal` for `agentId === undefined`, else the `subagentType` recorded at `agent.spawn` for that `agentId`, else `subagente` when the spawn was not seen. Two runs of one type on different models are two rows.
- `TurnUsage` is the host type, imported as `import type { TurnUsage } from 'claude-code'` (as `plugins/tool-fold/hooks/cycle.ts` does): `model`, `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`. A turn's model is `usage.model`; without `usage`, the model recorded at spawn, else `desconocido`.
- Before every commit: `python3 scripts/validate.py` and `claude plugin validate .`; for the mod: `claude plugin validate plugins/usage-ledger`, `claude plugin test plugins/usage-ledger`, and the type check: run `claude --plugin-dir plugins/usage-ledger` once (it lays the git-ignored types and tsconfig), then `tsc -p plugins/usage-ledger`.
- Pull requests target `dev` (`gh pr create --base dev`), never `main`.
- No `agent-skills` description changes, so no eval run is needed (CLAUDE.md § Eval protocol).

## Review Focus

1. A `turn.complete` with no `usage` → counted as a turn, tokens unchanged, no crash (Task 4 test).
2. A `turn.complete` whose `agentId` had no `agent.spawn` seen (mod enabled mid-session, resumed session) → row `subagente`, still counted (Task 4 test).
3. Malformed or old-shape settings in `$.store` (wrong types, unknown keys, a string) → defaults, no throw (Task 3 test).
4. Unknown command argument or missing `on|off` → help text, settings unchanged (Task 3 test).
5. Only if Task 7 ships: a model id absent from the price table with `price=on` → its tokens shown, the total marked partial (`Precio lista API: ≥ $… (parcial)`) (Task 7 test).

---

### Task 0: Branch

- [ ] **Step 0 (controller):** run `agent-skills:pre-mortem` on this plan; fold accepted amendments into the plan before Task 1.
- [ ] **Step 1:** `git switch dev && git pull && git switch -c feat/usage-ledger`. This plan file is untracked on the owner's previous branch (`feat/repo-tooling`); it moves with the switch. Commit it first: `git add docs/superpowers/plans/2026-11-25-usage-ledger-mod.md && git commit -m "docs(plans): usage-ledger mod plan"`.

### Task 1: Skeleton and live probe

**Files:**

- Create: `plugins/usage-ledger/.claude-plugin/plugin.json` (fields as `plan-progress`'s: name, version `0.1.0`, description `Mod: token usage of the main agent and its subagents, by agent and model, at a chosen verbosity.`, author, repository, `"types": "./types/index.d.ts"`)
- Create: `plugins/usage-ledger/hooks/hooks.json` → `{ "modules": ["./register.tsx"] }`
- Create: `plugins/usage-ledger/hooks/register.tsx`, `plugins/usage-ledger/types/index.d.ts` (atom typing, as `plan-progress/types/index.d.ts`)
- Create: `plugins/usage-ledger/CHANGELOG.md`, `plugins/usage-ledger/README.md` (stub; filled in Task 8)
- Test: `plugins/usage-ledger/tests/probe.test.tsx`

**Interfaces:**

- Produces: `export const register: Register`; command `usage-ledger` registered with `$.command.register({ name: 'usage-ledger', description: … })`; a session-only ring `probeAtom` of the last 5 raw events `{ kind: 'turn.complete' | 'agent.spawn' | 'tool.call' | 'session.append', agentId?: string, summary: string }`.

- [ ] **Step 1:** Write `probe.test.tsx`: simulate `session.start`, one `turn.complete` with `usage` (all four classes) and `agentId: undefined`, one `tool.call` `{ tool: 'Skill' }`; run `/usage-ledger debug`; assert the reply text contains `turn.complete` and `Skill`. Test patterns: `plugins/plan-progress/tests/plan.test.tsx` (events via `$.session.start`, `$.turn.complete`, `$.tool.call`; stub `session.surfaces`).
- [ ] **Step 2:** Run `claude plugin test plugins/usage-ledger` → FAIL.
- [ ] **Step 3:** Implement the skeleton: handlers on `turn.complete`, `agent.spawn`, `tool.call`, `session.append` that call `next(e)` first and never throw (wrap in `.catch(() => undefined)`, as `tool-fold` does), record a one-line summary into `probeAtom`, and the `debug` command branch. For `session.append`, the summary holds `door`, `agentId` and the content length in characters, never the content.
- [ ] **Step 4:** Run the test → PASS; run the validate commands of § Global Constraints.
- [ ] **Step 5:** Commit `feat(usage-ledger): mod skeleton with a debug probe`.
- [ ] **Step 6 (controller gate, owner check, live; not an implementer step):** the controller asks the owner to run one session with `claude --plugin-dir plugins/usage-ledger` (with `tool-fold` also enabled, so its Haiku side calls happen), dispatch one subagent and load one skill, then paste `/usage-ledger debug`. The controller records in `docs/mods-surfaces.md`, section `usage-ledger probe` (one row each, observed or not): (a) does `turn.complete` fire once per API request or once per agent turn; (b) does a subagent's `turn.complete` carry the same `agentId` as its `agent.spawn` result; (c) does a skill's loaded text arrive as a `session.append` (with which `door`, and its length) after the `Skill` call; (d) do mod side calls (`$.model.complete`) emit `turn.complete`, and with what `agentId`. Tasks 2–3 may proceed meanwhile; Task 4 and Task 6 wait for the answers.

### Task 2: Ledger model (pure)

**Files:**

- Create: `plugins/usage-ledger/hooks/ledger.ts`
- Test: `plugins/usage-ledger/tests/ledger.test.tsx`

**Interfaces:**

- Produces:
  - `type Tokens = { input: number; cacheWrite: number; cacheRead: number; output: number }`
  - `type Bucket = { tokens: Tokens; turns: number }`
  - `type Ledger = { total: Bucket; byAgent: Record<string, Bucket & { model: string; dispatches: number }>; byModel: Record<string, Bucket>; dispatches: number; skills: Record<string, { calls: number; tokens: number | null }> }`
  - `EMPTY_LEDGER: Ledger`
  - `addTurn(l: Ledger, agentRow: string, model: string, usage: TurnUsage | undefined): Ledger` (`agentRow` is the full row key of § Global Constraints; `model` is chosen by the caller as stated there; the function never reads `usage.model`)
  - `addDispatch(l: Ledger, agentRow: string, model: string): Ledger` (creates the row with zero tokens and `turns: 0` if absent)
  - `addSkill(l: Ledger, name: string, tokens: number | null): Ledger` (`calls` +1; tokens: `null` + `null` = `null`, `null` + n = n, n + m = n + m)
  - `modelKey(model: string): string` (strip `^claude-`)
  - `formatTokens(n: number): string` (copy of `tool-fold`'s: `950`, `12k`, `1.2M`)

- [ ] **Step 1:** Tests: `addTurn(l, 'principal · opus-5-5', 'opus-5-5', { input_tokens: 10, cache_creation_input_tokens: 20, cache_read_input_tokens: 300, output_tokens: 4, model: 'claude-opus-5-5' })` updates `total`, `byAgent['principal · opus-5-5']` (with `model: 'opus-5-5'`), `byModel['opus-5-5']` with those four values and `turns: 1`; `addTurn` with `usage` undefined → `turns` +1, tokens unchanged; `addDispatch` twice for `'implementer · sonnet-5-5'` → `dispatches: 2`, that row's `dispatches: 2`, `turns: 0`; `addSkill('memory', null)` then `addSkill('memory', 500)` then `addSkill('memory', 200)` → `{ calls: 3, tokens: 700 }`; `addSkill('x', null)` twice → `tokens: null`; inputs are not mutated.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(usage-ledger): ledger model`.

### Task 3: Settings

**Files:**

- Create: `plugins/usage-ledger/hooks/settings.ts`
- Test: `plugins/usage-ledger/tests/settings.test.tsx`

**Interfaces:**

- Produces:
  - `type Settings = { level: 'session' | 'last'; agent: boolean; model: boolean; dispatches: boolean; calls: boolean; skills: boolean; price: boolean }`
  - `DEFAULTS: Settings` (D8)
  - `parseStored(raw: unknown): Settings` (each valid field kept, anything else from `DEFAULTS`)
  - `applyArgs(s: Settings, args: string): { settings: Settings; action: 'open' | 'set' | 'show' | 'reset' | 'debug' | 'help' }` (grammar in § Design)
  - `loadSettings($): Promise<Settings>`, `saveSettings($, s: Settings): Promise<void>` on `$.store` key `usage-ledger.settings`
  - `HELP_TEXT: string` (Spanish, lists the grammar)

- [ ] **Step 1:** Tests: `parseStored(undefined)`, `parseStored('x')`, `parseStored({ level: 'all', agent: 'yes' })` → `DEFAULTS`; `parseStored({ level: 'last', agent: true, extra: 1 })` → defaults with those two; `applyArgs(DEFAULTS, 'level last')` → `level: 'last'`, `action: 'set'`; `'agent on'`, `'skills off'` set flags; `''` → `open`; `'settings'` → `show`; `'reset'`, `'debug'` map; `'agent'`, `'foo on'`, `'level weekly'` → `help` with settings unchanged; arguments are case-insensitive and whitespace-tolerant.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(usage-ledger): settings and command grammar`.

### Task 4: Event wiring

**Files:**

- Modify: `plugins/usage-ledger/hooks/register.tsx`
- Test: `plugins/usage-ledger/tests/wiring.test.tsx`

**Interfaces:**

- Consumes: Task 2 (`addTurn`, `addDispatch`, `addSkill`, `EMPTY_LEDGER`), Task 3 (`loadSettings`, `saveSettings`, `applyArgs`).
- Produces: atoms `sessionLedger` and `lastLedger` (both `Ledger`, session-scoped, `shape: 'ledger-1'`); `agentTypes` atom `Record<agentId, { type: string; model: string }>` filled from `agent.spawn` (`e.subagentType`, the `next(e)` result's `agentId` and `model`, as `plugins/tool-fold/hooks/agents.tsx` reads them in its `agent.spawn` handler); `pendingSkill` atom `Record<agentKey, string>` (`agentKey` = `agentId` or `'main'`), set by a `Skill` call, read and cleared by Task 6, cleared at that agent's next `turn.complete`.
- Dispatches are counted at `agent.spawn` (a spawn with `deny` or no `agentId` counts none), because the spawn carries both type and model; `tool.call` `Agent` is not counted.
- Read the probe answers in `docs/mods-surfaces.md` § `usage-ledger probe` first. If (b) is no, subagent turns land on `subagente · <model>` and the README states it. If (d) shows side calls with `agentId === undefined`, exclude them by counting a main `turn.complete` only when its `turnId` was opened by a `turn.start` without `agentId` (side calls open none; adjust to what the probe shows and test it).

- [ ] **Step 1:** Tests, each driving events through the test harness: main `turn.complete` → `principal · <model>` row in both ledgers; an `agent.spawn` for `implementer` and then a `turn.complete` with that `agentId` → `implementer · <model>` row and `dispatches: 1`; a `turn.complete` with an `agentId` never spawned and listed by the `$.agent.list` stub → `subagente · <model>`; an `agentId` not listed by `$.agent.list` → ignored (D2); the side-call exclusion chosen above → ignored; a main `session.append` with `door: 'prompt'` → `lastLedger` back to `EMPTY_LEDGER`, `sessionLedger` unchanged; `tool.call` `{ tool: 'Skill', fields: { skill: 'memory' } }` → `skills.memory.calls: 1`, tokens `null`, `pendingSkill.main: 'memory'` (field name as `tagOf` in `plugins/tool-fold/hooks/register.tsx`); a `turn.complete` without `usage` → turn counted (Review Focus 1); `/usage-ledger reset` empties both ledgers and keeps settings.
- [ ] **Step 2–4:** FAIL → implement (every handler: `next(e)` first, its own work in `.catch(() => undefined)`) → PASS.
- [ ] **Step 5:** Commit `feat(usage-ledger): count turns, dispatches and skills per agent and model`.

### Task 5: Views (text reply and pane)

**Files:**

- Create: `plugins/usage-ledger/hooks/view.tsx`
- Modify: `plugins/usage-ledger/hooks/register.tsx` (command branches `open`, `set`, `show`; pane render)
- Test: `plugins/usage-ledger/tests/view.test.tsx`

**Interfaces:**

- Consumes: `Ledger`, `Settings`, `formatTokens`.
- Produces: `type PriceFn = (model: string, t: Tokens) => number | null` (declared here so Task 7 only plugs one in); `reportLines(session: Ledger, last: Ledger, s: Settings, price?: PriceFn): string[]` (pure; the § Design layout); the pane `on('ui.render', { component: 'Pane', requestId: 'usage-ledger' }, …)` drawing the same lines with `Box`/`Text` from `$.ui.resolve(e)`; opening the pane follows `tool-fold`'s `/agents-dock` handler and its `openDock` helper in `plugins/tool-fold/hooks/agents.tsx`.

- [ ] **Step 1:** Tests on `reportLines`: defaults → exactly one line starting `Consumo · sesión` with the four classes; `level=last` adds `Desde tu último mensaje`; `agent=on` adds `Por agente` under each block, with `×N` when that agent has dispatches; `calls=off` hides the turn column, `calls=on` shows it; `model=on` adds `Por modelo`; `dispatches=on` adds the `Dispatches:` line; `skills=on` adds `Skills:` and omits `~… tokens` when every skill's tokens are `null`; empty ledgers → `Consumo · sesión  sin datos todavía`. One harness test: `/usage-ledger` returns the report text and the pane renders a `Text` matching `/Consumo · sesión/`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(usage-ledger): report as command text and pane`.
- [ ] **Step 6 (owner check, live):** the owner opens the pane on their surfaces (terminal, VS Code, Desktop) and toggles two flags; record anything unexpected in `docs/mods-surfaces.md`.

### Task 6: Skill tokens (depends on Task 1 Step 6 answer (c))

**Files:** Modify `plugins/usage-ledger/hooks/register.tsx`; Test `plugins/usage-ledger/tests/wiring.test.tsx`.

Answer (c) is in `docs/mods-surfaces.md` § `usage-ledger probe`.

- [ ] **Step 1:** If (c) is **yes**: a `session.append` from the same agent, matching the door the probe found, while `pendingSkill[agentKey]` is set, gives the size of that skill (then clear `pendingSkill[agentKey]`); tokens ≈ `Math.ceil(chars / 4)` (label `~`, an estimate) via `addSkill(l, name, tokens)`. Test: `Skill` call then a matching append of 4000 chars → `skills.<name>.tokens: 1000`. If (c) is **no**: skip the code, leave tokens `null`, and state the limit in the README (count only). Either way record the outcome in this plan's state table.
- [ ] **Step 2:** Commit `feat(usage-ledger): estimate tokens of loaded skills` (or `docs(usage-ledger): skill tokens not observable`).

### Task 7 (optional, owner may drop): Price

**Files:** Create `plugins/usage-ledger/hooks/prices.ts`; Test `plugins/usage-ledger/tests/prices.test.tsx`; Modify `view.tsx`.

**Interfaces:** `PRICES: Record<string, { input: number; cacheWrite: number; cacheRead: number; output: number }>` (keyed by `modelKey(model)`; `priceOf` applies `modelKey` before the lookup) in USD per million tokens, with `PRICES_DATE` and `PRICES_SOURCE` (URL) constants; `priceOf: PriceFn` (type from Task 5's `view.tsx`).

- [ ] **Step 1:** Fill the table from the official pricing page (load the `claude-api` skill or dispatch `agent-skills:researcher`; never from memory) for every model in `shared/models.toml`. Cache write uses the 5-minute rate; state that choice in a comment.
- [ ] **Step 2:** Tests: known model → exact sum of the four classes × rates; unknown model → `null`, report line `Precio lista API: ≥ $… (parcial)` (Review Focus 5); `price=off` → no price line.
- [ ] **Step 3:** FAIL → implement → PASS; commit `feat(usage-ledger): optional API list price`.

### Task 8: Docs, ADR, marketplace

**Files:**

- Modify: `.claude-plugin/marketplace.json` (entry like `plan-progress`'s: name, `source: "./plugins/usage-ledger"`, description; no version)
- Modify: `README.md` (catalog row next to `tool-fold` and `plan-progress`)
- Write: `plugins/usage-ledger/README.md` (purpose, install, command grammar, report example, limits: D10 turn meaning, skill tokens estimate or absent, prices dated, mod side calls excluded); `plugins/usage-ledger/CHANGELOG.md` `## [Unreleased]` entry
- Create: `docs/adr/0032-usage-ledger-mod.md` (Status line 3; Context: offload evaluation needs per-agent, per-model tokens; Decision: D1, D2, D6, D8; Alternatives: a setting inside `tool-fold`, an offline transcript script only (`docs/studies/scripts/usage_counts.py` stays for cross-session analysis); Revisit if: the host exposes per-request usage or a settings API for mods, or `tool-fold`'s card should show it)
- Modify: `docs/backlog.md` (an item under a new `## Mod usage-ledger` section pointing at this plan; update `Updated`/`Expires`)

- [ ] **Step 1:** Write the files; load `docs-principles` first (owner rule for agent-read docs).
- [ ] **Step 2:** Run `python3 scripts/validate.py`, `claude plugin validate .`, `claude plugin validate plugins/usage-ledger`, `claude plugin test plugins/usage-ledger` → all pass.
- [ ] **Step 3:** Commit `docs(usage-ledger): README, ADR 0032, catalog and marketplace entry`; tick the state table; then the final narrow reviews and `gh pr create --base dev` only when the owner asks.
