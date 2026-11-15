# 0021 `user-config/` is the single source of the owner's user-level rules

Status: accepted · Date: 2026-11-15 · Amends 0012

## Context

ADR 0012 keeps one copy of the offload policy, `user-config/offload-policy.md`, which the owner pastes into the user-level `~/.claude/CLAUDE.md` and which the `offload-*-with-policy` evals embed verbatim.

By 2026-11-15 the owner's deployed file had grown apart from it: three review rows (before an outward step, a process review, several narrow reviews), the reviewer brief fields and a round limit existed only there, and the policy's closing line was missing. The evals measured a text that was not the deployed one, and those rules had no history.

## Decision

- The rules for delegation, routing and review live in `user-config/offload-policy.md` and `user-config/routing.md`. The owner's user-level file is those two files verbatim plus personal sections (language, response style, plan habits, research hub).
- The review rows move into `routing.md`, under "Reviews and proof of done". `offload-policy.md` does not change, because the evals embed it.
- A rule that appears first in the owner's file is ported here before it is relied on.

## Alternatives

| Option | Rejected because |
|---|---|
| The owner's file as the source, mirrored here | The evals would keep measuring a text that may not be deployed |
| Keep both and let `validate.py` report the difference | Shows the drift without ending it |
| A third file, `review-policy.md` | `scripts/port.py` reads only the two existing files; a third needs port changes for no gain |

## Consequences

- The owner re-pastes both files after this change; until then the old and new rules coexist.
- The review rows now reach the Copilot and Codex ports and the README prompt block.
- `routing.md` is longer, and it loads in every session.
- The review rows are unmeasured (N6): no eval embeds `routing.md`.

## Revisit if

`scripts/port.py` handles more source files; or a review row is reverted under the kill criteria below.

### Kill criteria

Proposed with this record; the owner has not set them.

| Signal in a trace | Action |
|---|---|
| A push or a pull request with no `skeptical-reviewer` dispatch before it, in 2 traces | Restore that row's wording from the owner's earlier file |
| More than one review with the same focus on the same change | Tighten the row (ADR 0017 Review 2026-11-15) |
