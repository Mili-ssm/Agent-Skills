# Heuristics and inspection methods

## Nielsen's 10 usability heuristics

| # | Heuristic | Check |
|---|---|---|
| H1 | Visibility of system status | Loading, progress, saved/failed states visible and timely |
| H2 | Match with the real world | User vocabulary, natural order |
| H3 | User control and freedom | Undo, cancel, back, exit from flows |
| H4 | Consistency and standards | Same action = same look and word; platform conventions |
| H5 | Error prevention | Constraints, confirmation for destructive acts, safe defaults |
| H6 | Recognition over recall | Options visible; nothing to memorize across screens |
| H7 | Flexibility and efficiency | Shortcuts, bulk actions, remembered choices |
| H8 | Aesthetic and minimalist design | Every element supports the task |
| H9 | Recover from errors | Plain message, cause, fix; input preserved |
| H10 | Help and documentation | Contextual help where tasks are complex |

## Nielsen severity

| 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Not a problem | Cosmetic | Minor | Major | Catastrophe (fix before release) |

Severity = frequency × impact × persistence.

## Cognitive walkthrough

Per step of a task, ask: (1) Will the user try to achieve this effect? (2) Will they notice the correct control is available? (3) Will they associate it with the effect? (4) Will they see progress after acting? A "no" is a finding at that step. Norman's gulfs: execution ("how do I do it?") and evaluation ("did it work?").

## Deceptive patterns (Brignull) to flag

| Pattern | Signal |
|---|---|
| Confirmshaming | Decline option guilt-trips ("No, I like paying more") |
| Hidden costs / drip pricing | Fees appear at the last step |
| Sneak into basket / preselection | Extras or consent boxes pre-checked |
| Roach motel | Easy sign-up, hard cancellation |
| Nagging | Repeated interruptions for the same request |
| Misdirection / disguised ads | Visual weight steers away from the user's goal |
| Trick questions | Double negatives in consent |
| Forced action | Unrelated action required to continue |

Ethics check: could users spend more money, share more data or commit to more than they intended?

## Kano model (prioritizing improvements)

Basic (expected; absence angers), performance (more is better), delighters (unexpected; absence is fine). Fix basics before adding delighters.

## Forms checklist

Visible labels (never placeholder-only) · one column · related fields grouped · optional fields marked · validate on blur or submit, not per keystroke · correct `type`/`inputmode`/`autocomplete` · one obvious primary action, destructive action set apart.
