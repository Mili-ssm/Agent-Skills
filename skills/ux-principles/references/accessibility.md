# Accessibility (WCAG 2.2 AA)

## POUR

Perceivable · Operable · Understandable · Robust.

## High-yield success criteria

| SC | Requirement | Quick check |
|---|---|---|
| 1.1.1 Non-text content | Meaningful alt; decorative `alt=""` | Images, icon buttons have names |
| 1.3.1 Info and relationships | Semantics in markup (headings, lists, labels, tables) | Heading outline makes sense |
| 1.4.3 Contrast (minimum) | Text 4.5:1; large text 3:1 | axe `color-contrast` |
| 1.4.10 Reflow | Usable at 320 CSS px wide without 2D scroll | 375 px screenshot |
| 1.4.11 Non-text contrast | UI components/focus indicators 3:1 | Borders of inputs, icons |
| 1.4.12 Text spacing | No loss when spacing increased | — |
| 2.1.1 Keyboard | All functionality via keyboard | Focus order capture |
| 2.4.3 Focus order | Logical order | Focus order capture |
| 2.4.7 Focus visible | Visible focus indicator | Screenshot while focused |
| 2.4.11 Focus not obscured (min) | Focused item not hidden by sticky UI | — |
| 2.5.7 Dragging movements | Single-pointer alternative to drag | — |
| 2.5.8 Target size (min) | ≥ 24×24 CSS px or spacing | Small icon buttons |
| 3.3.1 / 3.3.3 Error identification / suggestion | Errors described in text with fix | Submit invalid form |
| 3.3.7 Redundant entry | Don't ask twice for same info | Multi-step forms |
| 3.3.8 Accessible authentication (min) | No cognitive tests; allow paste/password managers | Login |
| 4.1.2 Name, role, value | Custom controls expose ARIA correctly | axe |
| 4.1.3 Status messages | Status announced without focus move | `role="status"`/`aria-live` |

## Rules of ARIA

1. Native HTML first (`<button>`, `<dialog>`, `<details>`) — no ARIA is better than bad ARIA.
2. Don't change native semantics unless required.
3. All interactive ARIA controls keyboard operable.
4. No `role="presentation"`/`aria-hidden` on focusable elements.
5. Interactive elements need accessible names.

## Dynamic content (partial page updates, htmx, SPA)

- Announce updates: target region with `aria-live="polite"` (or `role="status"`); `assertive` only for urgent errors.
- After content swap that replaces the focused element, move focus to a logical target (heading of new content, first error).
- Loading: `aria-busy="true"` on region during request.
- Validation errors: link input to message with `aria-describedby`; set `aria-invalid="true"`.
- Preserve scroll/focus on back navigation.

## Automated vs. manual

axe-core catches ~30–40% of issues. Always also check: focus order logic, visible focus, alt text meaning, announcement of updates, keyboard traps, zoom 200%.
