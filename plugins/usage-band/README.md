# usage-band

Opt-in mod of the [`mili-ssm` marketplace](../../README.md), installed apart from `agent-skills` (ADR 0011). It makes offloading to Haiku/Sonnet and its cost visible (ADR 0010).

## What it shows

- Live status line per interaction cycle (your prompt to your next): how long Claude has worked on it, tokens per model, and calls, skills and agents of the main loop and its agents (`⏱ 1h52m · opus ▇▇▇▇▇ 17.3M · sonnet ▇▇▁▁▁ 6.4M · 412 calls · 2 skills · 8 agents`)
- The clock stops when no turn of the main loop or of an agent is open and no agent still works: the mark turns to `✓` and one dim line is printed (`✓ … │ Σ 3h10m · 41.7M`, the session's busy time and tokens). A hand-back that wakes Claude again resumes the same cycle without counting the pause.
- If you write while Claude still works, that line is printed above your message instead
- `/usage-band` for the cycle and a session summary

## Install

```bash
claude plugin install usage-band --marketplace Mili-ssm/Agent-Skills
```

In a cloud environment, list it in `AGENT_SKILLS_MODS` (for example `AGENT_SKILLS_MODS="usage-band"`): [`scripts/cloud-setup.sh`](../../scripts/cloud-setup.sh) installs the mods named there. Update it like the other plugins ([Update](../../README.md#update)).

The mod hooks API is early access and may change between Claude Code releases; a failing hook is skipped and never blocks a session (ADR 0011).

## Develop

From the repository root:

```bash
claude plugin validate plugins/usage-band
claude plugin test plugins/usage-band
claude --plugin-dir plugins/usage-band   # once: lays its types and tsconfig (git-ignored)
tsc -p plugins/usage-band
```

Which surfaces the UI tests mount on: see [Develop](../../README.md#develop).
