# tool-fold

Opt-in mod of the [`mili-ssm` marketplace](../../README.md), installed apart from `agent-skills` (ADR 0011). It makes offloading to Haiku/Sonnet visible (ADR 0010) and keeps tool output out of the way until asked for.

## What it shows

- Tools, skills and agents in the chat: each call one line (`▸ ● Bash Run the e2e suite`; skills by name), a run of them one group line (`▸ ● qa-review · implementer · Bash  <Haiku summary>`).
- Running agents live only in an "Agentes" pane (beside the chat, or above the prompt in a narrow VS Code panel; `/agents-dock` reopens it): mission, model, task progress or a Haiku `≈%` estimate (after any call, at most every 30 s), as one bordered card each (compact past three), their last calls as a few words on what each does (the model's own description, else Haiku's).
- When one ends it leaves the pane, its chat row shows the folded card and one dim line at the bottom of the chat says it ended (`✓ implementer · sonnet-5-5 · 8m 51s · … · 26 calls · 26 commands`).

- Desktop docks the "Agentes" pane beside the chat; with it closed, running agents draw as cards in the band above the prompt, as VS Code's inline pane does

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
