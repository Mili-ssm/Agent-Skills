# Accessibility (WCAG 2.2 AA)

POUR: Perceivable · Operable · Understandable · Robust.

## High-yield success criteria

| SC | Requirement | Quick check |
|---|---|---|
| 1.1.1 Non-text content | Meaningful alt; decorative `alt=""` | Icon buttons have names |
| 1.3.1 Info and relationships | Semantics in markup (headings, lists, labels, tables) | Heading outline makes sense |
| 1.4.3 Contrast | Text 4.5:1; large text 3:1 | axe `color-contrast` |
| 1.4.10 Reflow | Usable at 320 CSS px without 2-D scroll | 375 px screenshot |
| 1.4.11 Non-text contrast | Components and focus indicators 3:1 | Input borders, icons |
| 1.4.12 Text spacing | No loss with increased spacing | — |
| 2.1.1 Keyboard | Everything operable by keyboard | Focus-order capture |
| 2.4.3 Focus order | Logical order | Focus-order capture |
| 2.4.7 Focus visible | Visible indicator | Screenshot while focused |
| 2.4.11 Focus not obscured | Sticky UI never hides focus | — |
| 2.5.7 Dragging | Single-pointer alternative | — |
| 2.5.8 Target size | ≥ 24×24 CSS px or spacing | Small icon buttons |
| 3.3.1 / 3.3.3 Errors | Described in text with a fix | Submit an invalid form |
| 3.3.7 Redundant entry | Never ask twice | Multi-step forms |
| 3.3.8 Accessible authentication | No cognitive tests; paste and password managers allowed | Login |
| 4.1.2 Name, role, value | Custom controls expose ARIA correctly | axe |
| 4.1.3 Status messages | Announced without moving focus | `role="status"` / `aria-live` |

## Rules of ARIA

Native HTML first (`<button>`, `<dialog>`, `<details>`): no ARIA beats bad ARIA. Keep native semantics. ARIA controls must be keyboard operable. Focusable elements are never `aria-hidden`. Interactive elements need accessible names.

## Dynamic content (partial updates, htmx, SPA)

- Target regions announce updates: `aria-live="polite"` or `role="status"`; `assertive` only for urgent errors.
- When a swap replaces the focused element, move focus to a logical target (new heading, first error).
- `aria-busy="true"` on a region while it loads.
- Invalid fields: `aria-invalid="true"` + message linked with `aria-describedby`.
- Back navigation restores scroll and focus.

## Inclusive design (Microsoft)

Recognize exclusion · solve for one, extend to many · learn from diversity. Consider permanent, temporary and situational limits (one arm / injured arm / holding a baby).

## Automated vs. manual

axe-core finds roughly a third of issues. Always check manually: focus-order logic, visible focus, alt meaning, update announcements, keyboard traps, 200% zoom.
