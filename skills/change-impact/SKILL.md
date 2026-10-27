---
name: change-impact
description: Use before planning or implementing a significant change (new feature touching shared code, refactor of boundaries, dependency or schema change, API change, removal) - maps blast radius, breaking changes, decisions and docs made stale, migration and rollback strategy.
---

# Change Impact Analysis

Run before `writing-plans`. Output feeds the plan; unclear intent → run `intent-elicitation` in `change` mode first.

## Process

1. **State the change** in one sentence plus its motivation. Unclear motivation is the first finding.
2. **Map the blast radius** (evidence per row):

| Dimension | How to find |
|---|---|
| Direct callers / importers | Grep symbol, module, route, template names |
| Public contracts | HTTP routes, CLI flags, library API, events, file formats, env vars |
| Data | Schemas, migrations, stored formats, caches, serialized objects |
| Config / infra | Settings, CI, deployment manifests, feature flags |
| Tests | Tests covering touched code; tests that will need to change |
| Docs / ADRs | Claims and decisions that become false (dispatch `consistency-auditor` in `change` mode for large scope) |
| People / systems | Consumers outside the repo, other teams, scheduled jobs |
| Non-functional | Performance, security surface, accessibility, cost |

3. **Classify compatibility** (SemVer reasoning): `patch` (no contract change) · `minor` (additive) · `major` (breaking). For breaking: list each break and who it hits.
4. **Choose a migration strategy**:

| Strategy | Use when |
|---|---|
| Direct change | Internal, all callers in repo, covered by tests |
| Parallel change (expand → migrate → contract) | Contracts or schemas with live consumers |
| Branch by abstraction | Replace an internal component incrementally on trunk |
| Strangler fig | Replace a subsystem route by route |
| Feature flag / dark launch | Risky behavior; need fast off-switch |
| Dual write / backfill | Data model changes with zero downtime |

5. **Risk and rollback**: top risks (likelihood × impact, `low/med/high` with evidence); rollback path per step; point of no return (irreversible steps such as destructive migrations) called out explicitly.
6. **Verification plan**: tests to add/adjust, characterization tests before touching legacy code, monitoring signals during rollout.
7. **Docs and decisions**: ADRs to supersede or write, docs to update in the same change.

## Output

```markdown
## Change
<sentence> · Motivation · Compatibility: patch | minor | major

## Blast radius
| Dimension | Affected item | Evidence | Action needed |

## Breaking changes
| Break | Affected consumers | Mitigation |

## Strategy
<chosen strategy + why; ordered steps, each independently deployable/revertible>

## Risks
| Risk | Rating | Evidence | Mitigation | Rollback |
Point of no return: <step or "none">

## Verification
## Docs / ADRs to update
## Open questions for owner
```

## Rules

- Every affected item needs evidence; "probably used somewhere" → grep or list as open question.
- Prefer sequences of small reversible steps over one large step.
- Decision-level changes produce an ADR (`decision-records`).
