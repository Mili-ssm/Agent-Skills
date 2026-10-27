# 0003 Interactive work runs in skills, not subagents

Status: accepted · Date: 2026-10-27

## Context

R4 requires asking the owner as many questions as needed. Subagents cannot converse with the user mid-task; they only return a final report.

## Decision

Split intent work:

| Part | Type | Job |
|---|---|---|
| `consistency-auditor` | Agent (read-only) | Scan code/docs/ADRs/git; return findings register + open questions |
| `intent-elicitation` | Skill (main thread) | Consume register; interview via `AskUserQuestion`; record answers in requirements/ADRs |

Same rule for any future workflow needing owner input.

## Consequences

- Noisy scanning stays out of the main context; interviewing keeps full conversational ability.

## Revisit if

Subagents gain a supported way to ask the user questions.
