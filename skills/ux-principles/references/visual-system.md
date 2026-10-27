# Visual system

## Design tokens

Single source for color, spacing, type, radius, shadow, motion as CSS custom properties (`--space-2`, `--color-text-muted`). Components consume tokens, never raw values. Dark mode = token remap, not per-component overrides.

## Spacing

| Rule | Value |
|---|---|
| Base grid | 4 or 8 px; scale e.g. 4, 8, 12, 16, 24, 32, 48, 64 |
| Internal ≤ external | Space inside a group < space between groups (Gestalt proximity) |
| Consistency | Same relationship → same token |

## Typography

| Rule | Guidance |
|---|---|
| Modular scale | Ratio 1.2–1.333 (e.g. 14, 16, 20, 24, 32) |
| Body size | ≥ 16 px on web |
| Line length | 45–75 characters (`max-width: 65ch`) |
| Line height | 1.4–1.6 body; 1.1–1.3 headings |
| Hierarchy | Size + weight + color; max 2 families, 3–4 weights |

## Color

- Roles, not hues: `primary`, `danger`, `surface`, `text`, `text-muted`, `border`.
- Contrast per WCAG (text 4.5:1, UI 3:1).
- Never color alone to convey meaning (add icon/text).
- 60-30-10 distribution as a starting heuristic.

## Hierarchy and layout

- One primary action per view (Von Restorff); secondary actions visually weaker.
- F/Z scanning patterns for text-heavy vs. sparse pages.
- Alignment to a grid; fewer alignment lines = calmer layout.
- Content-first responsive design: mobile layout defined, not derived by shrinking.

## Component states (each must be designed)

| State | Notes |
|---|---|
| Default, hover, active | Hover never the only signifier (touch) |
| Focus-visible | Distinct, 3:1 contrast |
| Disabled | Explain why when possible; avoid disabled submit without reason |
| Loading | Indicator; prevent double submit |
| Empty | Explain and offer next action |
| Error | Message + recovery |
| Success | Confirm and indicate next step |
| Overflow | Long text, many items, missing images |

## Motion

Purposeful (orientation, feedback), 150–300 ms, ease-out for entering; respect `prefers-reduced-motion`.
