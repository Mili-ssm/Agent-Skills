# plan-progress

Opt-in mod of the [`mili-ssm` marketplace](../../README.md), installed apart from `agent-skills` (ADR 0011). It tracks Superpowers plans.

## What it shows

- Only while a plan exists (`docs/superpowers/plans/`, `docs/plans/`, `plans/`): a borderless card above the prompt: title, `5/10`, percent, then a progress bar (glyphs in the terminal, a thin SVG line elsewhere: 1px faded track and 2px fill in the same color) and, when the plan changes, a short Haiku description of what remains `▶ finish the login route and its tests` (until it arrives, or if it fails, the active task `▶ Task 3 · 2/4`); toast per finished task. No status line
- Two plan shapes: several headings each owning checkboxes (Superpowers; every checkbox is a step, the card counts steps) or a task list (top-level checkboxes are tasks, nested ones the subtasks of the task above them; the card counts tasks, so the total ignores subtasks, and a task without subtasks shows no own `n/m`). Two or more headings with checkboxes pick the first; otherwise the second
- `/plan-progress [path|auto]`: pass a path to pin a plan, or `auto` to follow the newest

## Install

```bash
claude plugin install plan-progress --marketplace Mili-ssm/Agent-Skills
```

In a cloud environment, list it in `AGENT_SKILLS_MODS` (for example `AGENT_SKILLS_MODS="plan-progress"`): [`scripts/cloud-setup.sh`](../../scripts/cloud-setup.sh) installs the mods named there. Update it like the other plugins ([Update](../../README.md#update)).

The mod hooks API is early access and may change between Claude Code releases; a failing hook is skipped and never blocks a session (ADR 0011).

## Develop

From the repository root:

```bash
claude plugin validate plugins/plan-progress
claude plugin test plugins/plan-progress
claude --plugin-dir plugins/plan-progress   # once: lays its types and tsconfig (git-ignored)
tsc -p plugins/plan-progress
```

Which surfaces the UI tests mount on: see [Develop](../../README.md#develop).
