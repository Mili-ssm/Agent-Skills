# tool-fold

Opt-in mod of the [`mili-ssm` marketplace](../../README.md), installed apart from `agent-skills` (ADR 0011). It makes offloading to Haiku/Sonnet visible (ADR 0010) and keeps tool output out of the way until asked for.

## What it shows

- Tools, skills and agents in the chat: each call one line (`▸ ● Bash Run the e2e suite`; skills by name), a run of them one group line (`▸ ● qa-review · implementer · Bash  <Haiku summary>`).
- Running agents live only in an "Agentes" pane (beside the chat, or above the prompt in a narrow VS Code panel; `/agents-dock` reopens it): mission, model, task progress or a Haiku `≈%` estimate (after any call, at most every 30 s), as one borderless card each: line 1 an icon by type (`◆` main agent, `⌕` read/explore, `✎` writers, `▶` runners, `◇` other), the bold name, the model (its `●` colored by family: opus purple, sonnet blue, haiku teal, fable gold, other dim) with the elapsed time dim after it (`● opus-5-5 · 1m 12s`) and, at the right, the key datum (`≈60% · ~3 min` or `3/7`; empty with no estimate); line 2 a thin progress line (an Svg like plan-progress's, a glyph line on the terminal; none without an estimate); line 3 one dim line with the live call (the model's own description, else Haiku's) or the mission. Colors follow the state: running orange, waiting blue, completed green, failed or stopped red.
- When one ends it leaves the pane, its chat row shows the folded card and one dim line at the bottom of the chat says it ended (`✓ implementer · sonnet-5-5 · 8m 51s · … · 26 calls · 26 commands`).
- On Desktop running agents are meant to draw as cards in the band above the prompt, as VS Code's inline pane does, and no pane opens on its own: Desktop does not tell the mod when its docked pane is closed. The cards were not yet seen drawing there (open, [`docs/mods-surfaces.md`](../../docs/mods-surfaces.md)). `/agents-dock` still opens it beside the chat. `/agents-debug` reports what the band and the pane see
- The main agent's wait is one card for all its waits (detail `esperando a check-runner · sleep 60 en segundo plano`, or `a 2 agentes`, `2 procesos`; plugin prefixes stripped; elapsed since the earliest wait; estimate, progress and icon from the process whose estimated end is latest, none when only agents are waited on). Where the "Agentes" pane is up (not on Desktop, which never reports its close) the band draws no cards, and the pane title counts the cards it shows. When its turn ended and it waits on background work (a `Bash` that answered a `backgroundTaskId`, a `Monitor`, a background agent), the "Agentes" pane and the Desktop band list it first, ahead of every other agent, as `◆ Claude · esperando` (bold, blue), the main model, what it waits on as the mission, and, at the right `≈%` (elapsed over the estimate, held at 95% until done, then `≈95% · más de lo previsto` in place of the time left; never while it waits on an agent, whose own card carries it). What it waits on reads as the call's `description`, else, once at launch, Haiku's plain phrase of at most 8 words (Spanish) for the command. The estimate, first that yields wins: (1) a duration Claude's own last message states ("unas 2–3 horas" → 150 min, midpoint of a range), read once by Haiku when the turn ends and applied to the waits that turn started, `✦`; (2) the median of similar finished waits, `⟲`: the last 50 `{ summary, durationMs, at }` kept across sessions in `$.store`, similar when the word overlap (Jaccard over words of 3+ letters, stopwords out) of the summaries is at least 0.5, else Haiku picks similar ones from the latest 20; (3) Haiku's guess of the minutes from the command (same call as the label), `?`. The icon is one dim character before the right datum. A stronger source replaces a weaker one when it arrives; each wait costs at most two small calls, plus one per turn end. With no estimate the card draws the empty track only. Every card with a `≈%` of more than 5% adds the time left (elapsed × (1 − p) / p): `≈60% · ~3 min`, `<1 min`, `~1 h 5 min`. It goes when the task's notification says it ended, or a new turn starts, and returns at that turn's end if work remains. Unverified against a live session: the notification's `<task-id>`/`<status>` tags are read from its text (open, [`docs/mods-surfaces.md`](../../docs/mods-surfaces.md)).

## Install

```bash
claude plugin install tool-fold --marketplace Mili-ssm/Agent-Skills
```

In a cloud environment, list it in `AGENT_SKILLS_MODS` (for example `AGENT_SKILLS_MODS="tool-fold"`): [`scripts/cloud-setup.sh`](../../scripts/cloud-setup.sh) installs the mods named there. Update it like the other plugins ([Update](../../README.md#update)).

The mod hooks API is early access and may change between Claude Code releases; a failing hook is skipped and never blocks a session (ADR 0011).

## Develop

From the repository root:

```bash
claude plugin validate plugins/tool-fold
claude plugin test plugins/tool-fold
claude --plugin-dir plugins/tool-fold   # once: lays its types and tsconfig (git-ignored)
tsc -p plugins/tool-fold
```

Which surfaces the UI tests mount on: see [Develop](../../README.md#develop).
