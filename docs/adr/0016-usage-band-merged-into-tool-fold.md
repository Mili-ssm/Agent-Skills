# 0016 usage-band merged into tool-fold's main card

Status: accepted · Date: 2026-11-01 · Amends 0011

## Context

`usage-band` (a card per interaction cycle: elapsed time, calls, skills, agents, what Claude does, a Haiku conclusion) and `tool-fold`'s main agent card (`◆ Claude · trabajando|esperando`, elapsed time, the call it makes) sat one above the other on Desktop and VS Code. Both showed an elapsed time, an agent count and an activity line, and they disagreed: one counted since the wait began, the other since the prompt.

## Decision

`usage-band` is retired; `tool-fold`'s main card absorbs it. The card has at most four lines:

| Line | Content |
|---|---|
| Header | `◆ Claude · trabajando\|esperando\|en segundo plano\|listo`, the model, the time of the whole request since the owner's prompt (across turns and waits), at the right the process estimate when waiting |
| Track | the thin progress line (empty while working, estimate while waiting, full when done) |
| Activity | usage-band's Haiku phrase for what Claude does (`▸`), its conclusion once done (`✓`); while waiting on a process the process label shows until a phrase exists |
| Stats (dim) | context share first with a fill icon (`○ ◔ ◑ ◕ ●` by quarters; green under 50% used, amber to 80%, red above), calls, skills, agents used in the whole request with one dot per model family, session Σ time · tokens |

- States: orange `trabajando`; blue `esperando` / `en segundo plano` (estimate as before); green `listo` after the response, **kept until the owner's next prompt** (no 5 s removal for this card; subagent finish lingering is unchanged).
- Ported from usage-band: cycle tracking (busy time, calls, skills, agents, tokens per model), the doing and conclusion Haiku calls (at most one per 30 s after new calls, one per idle moment), `cleanPhrase`, `formatContext`, session totals. Dropped: its own card, status line, printed log lines and `/usage-band`.
- The agent count appears only on the stats line (cycle total) and the divider `── Agentes N ──` (cards shown).

## Alternatives

- Keep both and read across mods: couples two independent mods (ADR 0011).
- Merge with `plan-progress`: rejected earlier, its scope is a plan, not a request.

## Consequences

- One fewer install; owners uninstall `usage-band` (`claude plugin uninstall usage-band`).
- tool-fold's state gains `cycle` and `session` (one more Haiku call stream, same rates as before).
- The pane and the band no longer empty when idle: the done card stays until the next prompt.

## Revisit if

The done card clutters the pane after long idle periods, or Haiku phrases prove unreliable on the main card.
