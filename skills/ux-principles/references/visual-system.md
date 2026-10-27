# Visual system

## Tokens

Color, spacing, type, radius, shadow and motion live in CSS custom properties (`--space-2`, `--color-text-muted`). Components consume tokens, never raw values. Dark mode remaps tokens instead of overriding components.

## Spacing

Base grid 4 or 8 px (scale 4, 8, 12, 16, 24, 32, 48, 64). Space inside a group < space between groups (proximity). Same relationship → same token.

## Typography

| Rule | Guidance |
|---|---|
| Modular scale | Ratio 1.2–1.333 (14, 16, 20, 24, 32) |
| Body size | ≥ 16 px |
| Line length | 45–75 characters (`max-width: 65ch`) |
| Line height | 1.4–1.6 body; 1.1–1.3 headings |
| Hierarchy | Size + weight + color; ≤ 2 families, 3–4 weights |

## Color

Roles, not hues (`primary`, `danger`, `surface`, `text-muted`, `border`). Contrast per WCAG. Meaning never by color alone (add icon or text). 60-30-10 as a starting split.

## Hierarchy and layout

One primary action per view; secondary actions visibly weaker. F/Z scanning for text-heavy vs. sparse pages. Few alignment lines. Design the mobile layout explicitly instead of shrinking desktop.

## Component states (design each)

| State | Notes |
|---|---|
| Default, hover, active | Hover is never the only signifier (touch) |
| Focus-visible | Distinct, 3:1 contrast |
| Disabled | Explain why where possible |
| Loading | Indicator; prevent double submit |
| Empty | Explain and offer the next action |
| Error | Message + recovery |
| Success | Confirm and show the next step |
| Overflow | Long text, many items, missing images |

## Motion

Purposeful (orientation, feedback), 150–300 ms, ease-out on enter; respect `prefers-reduced-motion`.
