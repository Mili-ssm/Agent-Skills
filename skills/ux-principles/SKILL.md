---
name: ux-principles
description: Use when designing, reviewing or auditing a user interface, page, form or flow - Nielsen heuristics, laws of UX, Gestalt, WCAG 2.2 accessibility, visual system rules, plus a Playwright script capturing screenshots, axe-core violations and keyboard focus order as evidence.
---

# UX/UI Principles

Judge interfaces by evidence (screenshots, axe results, focus order), cite the heuristic or law violated, and rate severity. Taste is not a finding.

## Index

| Need | Reference |
|---|---|
| Heuristics (Nielsen, Shneiderman, Norman) + severity scale | [heuristics.md](references/heuristics.md) |
| Laws of UX + Gestalt | [laws.md](references/laws.md) |
| Accessibility (WCAG 2.2 AA, POUR, dynamic content) | [accessibility.md](references/accessibility.md) |
| Visual system (tokens, spacing, type, color, states, layout) | [visual-system.md](references/visual-system.md) |
| Evidence capture script | [scripts/ux_audit.py](scripts/ux_audit.py) |

## Evidence capture

```bash
# Screenshots per viewport, axe-core violations, keyboard focus order → ./ux-audit/
python3 <skill-dir>/scripts/ux_audit.py http://localhost:8000/ --out ux-audit
# Several pages and a custom viewport set:
python3 <skill-dir>/scripts/ux_audit.py http://localhost:8000/ http://localhost:8000/login --viewports 375x812,1440x900
```

Requires Python Playwright with Chromium. Pre-installed browser of another version → `--executable-path` (or `$PW_CHROMIUM_PATH`). axe-core loads from jsDelivr; offline/blocked → `--axe-path` to a local `axe.min.js` (`npm pack axe-core`).

## Review process

1. **Goal**: primary user tasks per screen (ask or infer from routes/templates).
2. **Capture**: run the script on each screen and relevant states (empty, loading, error, filled, long content).
3. **Heuristic walk**: per screen, check the 10 Nielsen heuristics against the primary task.
4. **Accessibility**: axe violations + manual checks axe cannot do (focus order sense, visible focus, meaningful alt, announcements of dynamic updates).
5. **Visual system**: consistency of spacing, type scale, color tokens, component states.
6. **Rate** with Nielsen severity 0–4; propose concrete fixes (markup/CSS level, minimal JS).

## Defaults worth enforcing

- Progressive enhancement: core tasks work without JS; enhancement adds speed.
- Feedback < 100 ms (instant), < 1 s (flow kept), > 1 s show progress (Doherty threshold ~400 ms).
- Every interactive element: visible focus, ≥ 24×24 CSS px target (WCAG 2.5.8), accessible name.
- Errors: inline, next to the field, say how to fix, preserve input.
- Dynamic region updates announced (`aria-live`) and focus managed after swaps.
