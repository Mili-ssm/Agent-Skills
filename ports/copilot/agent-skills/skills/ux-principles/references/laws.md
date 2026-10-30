# Laws of UX and Gestalt

## Laws with design implications

| Law | Implication |
|---|---|
| Fitts | Big, close targets for frequent actions; screen edges are fast |
| Hick–Hyman | Fewer options per step; progressive disclosure; good defaults |
| Jakob | Follow conventions before inventing |
| Miller / chunking | Chunk information; never rely on memory across steps |
| Doherty threshold (~400 ms) | Optimistic UI, indicators (`hx-indicator`), fast partial updates |
| Tesler (conserved complexity) | Move complexity into the system, not onto the user |
| Postel (input) | Accept many formats (phone, dates); normalize server-side |
| Peak–end rule | Polish success states and completion |
| Serial position | Key navigation items at the ends |
| Von Restorff | One visually distinct primary action |
| Zeigarnik / goal-gradient | Progress indicators; resumable flows; shorten perceived distance |
| Aesthetic–usability effect | Polish raises perceived usability; it never replaces function |
| Choice overload | Curate, recommend, compare in tables |

## Gestalt

| Principle | Use |
|---|---|
| Proximity | Spacing defines groups more than borders |
| Similarity | Same style = same function |
| Common region | Cards/containers group content |
| Continuity | Aligned items read as a sequence |
| Figure–ground | Clear foreground (modals, focus) vs. background |
| Uniform connectedness | Connectors group strongest |
| Prägnanz | Simplest interpretation wins; simplify shapes and layouts |

## Response-time limits (Nielsen, Card et al.)

| Delay | Perception | Response |
|---|---|---|
| < 100 ms | Instant | No indicator |
| 100 ms – 1 s | Noticeable, flow kept | Subtle indicator optional |
| 1 – 10 s | Attention drifts | Skeleton or spinner |
| > 10 s | Task switch | Progress bar, cancel, notify on completion |
