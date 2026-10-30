---
name: ux-principles
description: Plans, designs and reviews user interfaces and flows with Playwright as the verification loop - task and flow design, screen specs with all states, accessibility plans, acceptance criteria as Playwright checks, plus Nielsen heuristics, laws of UX, WCAG 2.2 AA, deceptive-pattern checks and a script capturing screenshots, axe-core violations and focus order. Use when planning or designing a page, form, component or user flow, defining its UX acceptance criteria, or auditing a running UI; load it before designing so every decision cites a heuristic, law or WCAG criterion.
---

# UX/UI Principles

Design and review interfaces from user tasks, verify them in a real browser with Playwright, and cite the heuristic, law or WCAG criterion behind each decision or finding. Taste alone is not a reason. Explicit entry points: `/agent-skills:ux-design` (plan/design) and `/agent-skills:ux-review` (audit a running UI).

## Index

| Need | Reference |
|---|---|
| Heuristics, cognitive walkthrough, deceptive patterns, Kano, severity scale | [heuristics.md](references/heuristics.md) |
| Laws of UX, Gestalt, response-time limits | [laws.md](references/laws.md) |
| Accessibility: WCAG 2.2 AA, ARIA rules, dynamic content, inclusive design | [accessibility.md](references/accessibility.md) |
| Visual system: tokens, spacing, type, color, states, motion | [visual-system.md](references/visual-system.md) |
| Evidence capture | [scripts/ux_audit.py](scripts/ux_audit.py) |

## Design workflow (main conversation)

Resolve the unknowns of step 1 with your tool for asking the user questions (or a direct question in chat), because subagents cannot ask the owner.

Copy and tick:

```
- [ ] 1 Users and tasks: primary users, jobs-to-be-done, top 3 tasks, success measure, constraints (devices, JS budget)
- [ ] 2 Flows: task flows as Mermaid flowcharts; fewest steps; error and cancel paths
- [ ] 3 Information architecture: screens, navigation, content priority per screen
- [ ] 4 Screen specs: layout regions, components, copy, every state (empty, loading, error, success, overflow), responsive behavior
- [ ] 5 Accessibility plan: landmarks, heading outline, focus order and focus moves after updates, live regions, target sizes
- [ ] 6 Acceptance criteria as Playwright checks
- [ ] 7 After implementation: verify with `ui-verifier` and ux_audit.py; fix; at most 3 rounds, then report what remains
```

One small component or copy change: steps 4–7 only.

Step 6 turns criteria into executable checks:

| Criterion | Playwright check |
|---|---|
| Task completes by keyboard | `page.keyboard.press("Tab")` sequence + `expect(locator).to_be_focused()` |
| Controls have names and roles | `page.get_by_role("button", name="Sign up")` resolves |
| Errors announced inline, input kept | Submit invalid → `expect(page.get_by_role("alert")).to_contain_text(...)`; field value unchanged |
| Partial update moves focus / announces | After swap: `expect(heading).to_be_focused()` or live region text |
| No serious axe violations | `ux_audit.py` summary: 0 serious+critical |
| Works without JS (progressive enhancement) | `browser.new_context(java_script_enabled=False)`; core task still completes |
| Responsive | Screenshots at 375 and 1440 px; no horizontal scroll |

Step 7 (main conversation): dispatch `ui-verifier` with a self-contained brief (app URL or start command, the step-6 checks as flows with expected results, viewports 375x812 and 1440x900, login and test data where a flow needs them) and run `ux_audit.py` for the axe row. Fix what fails and verify again, at most 3 rounds; then report the violations that remain, because repeated failures usually need a decision from the owner.

## Evidence capture

Run the script instead of reading it, because only its summary table matters:

```bash
# Screenshots per viewport, axe-core violations, keyboard focus order; prints a summary table.
python3 ${CODEX_HOME:-$HOME/.codex}/plugins/cache/mili-ssm/agent-skills/local/skills/ux-principles/scripts/ux_audit.py http://localhost:8000/ http://localhost:8000/login --viewports 375x812,1440x900
```

Output goes to a temp dir (printed) unless `--out` is given. Requires Python Playwright; a pre-installed Chromium of another version → `--executable-path` or `$PW_CHROMIUM_PATH` (auto-detects `/opt/pw-browsers/chromium`). Blocked CDN → `--axe-path` to a local `axe.min.js`.

## Review workflow (`ux-reviewer`, or inline for a small page)

1. Identify primary tasks per screen; capture each screen and its states.
2. Walk each task (cognitive walkthrough), then check Nielsen H1–H10.
3. Accessibility: axe violations + manual checks (focus logic, visible focus, alt meaning, announced updates, reflow at 320 px).
4. Visual system: raw values vs. tokens; spacing, type scale, component states.
5. Rate with Nielsen severity 0–4; propose the smallest fix at markup/CSS level.

## Defaults (configurable per project)

- Progressive enhancement and rule of least power: core tasks work with HTML alone; CSS, then minimal JS, add polish, because native elements bring accessibility and robustness without code. A JS-first project says so in step 1 and drops the "works without JS" check; the other checks stay.
