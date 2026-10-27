---
name: ux-principles
description: Reviews pages, forms, components and user flows (live URLs or HTML/CSS snippets) for usability and accessibility using Nielsen heuristics with a severity scale, laws of UX, WCAG 2.2 AA, deceptive-pattern checks and visual-system rules, plus a Playwright script for screenshots, axe-core and focus order. Use when asked to review, critique or improve a UI, form or flow for usability, UX, accessibility or a11y; load it before answering so findings cite the violated heuristic or WCAG criterion with a severity.
---

# UX/UI Principles

Judge interfaces by evidence (screenshots, axe results, focus order), cite the heuristic, law or WCAG criterion violated, and rate severity. Taste alone is not a finding.

## Index

| Need | Reference |
|---|---|
| Heuristics, cognitive walkthrough, deceptive patterns, severity scale | [heuristics.md](references/heuristics.md) |
| Laws of UX, Gestalt, response-time limits | [laws.md](references/laws.md) |
| Accessibility: WCAG 2.2 AA, ARIA rules, dynamic content, inclusive design | [accessibility.md](references/accessibility.md) |
| Visual system: tokens, spacing, type, color, states, motion | [visual-system.md](references/visual-system.md) |
| Evidence capture | [scripts/ux_audit.py](scripts/ux_audit.py) |

## Evidence capture

Run (do not read) the script:

```bash
# Screenshots per viewport, axe-core violations, keyboard focus order; prints a summary table.
python3 <skill-dir>/scripts/ux_audit.py http://localhost:8000/ http://localhost:8000/login --viewports 375x812,1440x900
```

Output goes to a temp dir (printed) unless `--out` is given. Requires Python Playwright; a pre-installed Chromium of another version → `--executable-path` or `$PW_CHROMIUM_PATH` (auto-detects `/opt/pw-browsers/chromium`). Blocked CDN → `--axe-path` to a local `axe.min.js` (`npm pack axe-core`).

## Review workflow

The `ux-reviewer` agent follows this workflow; use it inline for one screen.

1. **Tasks**: primary user tasks per screen (routes, templates, headings).
2. **Capture** each screen and the states that matter: empty, loading, error (submit invalid form), filled, long content.
3. **Walk** each task (cognitive walkthrough), then check Nielsen H1–H10.
4. **Accessibility**: axe violations + manual checks axe cannot do (focus order sense, visible focus, alt meaning, announced updates, reflow at 320 px).
5. **Visual system**: raw values vs. tokens; spacing, type scale, component states.
6. **Rate** with Nielsen severity 0–4; propose the smallest fix at markup/CSS level.

## Defaults (configurable per project)

- Progressive enhancement and rule of least power: core tasks work with HTML alone; CSS, then minimal JS, add polish.
- Response time: instant < 100 ms; show progress past ~400 ms (Doherty); optimistic UI for safe actions.
- Every interactive element: visible focus, ≥ 24×24 CSS px target, accessible name.
- Errors inline next to the field, saying how to fix, with input preserved.
- Partial updates announced (`aria-live`) and focus moved to the new content when the focused element is replaced.
