---
name: change-impact
description: Maps the blast radius of a significant change - callers, contracts, data, docs, consumers, breaking changes, migration strategy (expand/contract, flags, strangler), rollout, rollback and point of no return. Use when planning or about to implement a rename, schema or API change, dependency swap, removal or boundary refactor, or when asked what a change will affect and how to roll it out safely.
---

# Change Impact Analysis

Run before writing the implementation plan, because the plan inherits the blast radius. Unclear motivation → run `intent-elicitation` in `change` mode first.

## Workflow

Copy and tick:

```
- [ ] 1 State the change and its motivation in one sentence each
- [ ] 2 Map the blast radius (evidence per row)
- [ ] 3 Classify compatibility
- [ ] 4 Choose migration and rollout strategy
- [ ] 5 Risks, rollback, point of no return
- [ ] 6 Verification plan
- [ ] 7 Docs and ADRs to update in the same change
```

**2. Blast radius** (Hyrum's law: every observable behavior may have a consumer):

| Dimension | How to find |
|---|---|
| Direct callers / importers | Grep symbol, module, route, template names |
| Public contracts | HTTP routes, CLI flags, library API, events, file formats, env vars, error messages |
| Data | Schemas, migrations, stored formats, caches, serialized objects |
| Config / infra | Settings, CI, deployment manifests, feature flags |
| Tests | Covering tests; tests that must change |
| Docs / ADRs | Claims and decisions made false (large scope: dispatch `consistency-auditor` in `change` mode) |
| People / systems | Consumers outside the repo, other teams, scheduled jobs |
| Non-functional | Performance, security surface, accessibility, cost |

**3. Compatibility**: `patch` (no contract change) · `minor` (additive) · `major` (breaking: list each break and who it hits).

**4. Strategy**:

| Strategy | Use when |
|---|---|
| Direct change | Internal, all callers in repo, covered by tests |
| Parallel change (expand → migrate → contract) | Contracts or schemas with live consumers |
| Branch by abstraction | Replace an internal component incrementally on trunk |
| Strangler fig | Replace a subsystem route by route |
| Feature flag (release, ops, experiment, permission — Hodgson) | Risky behavior; fast off-switch; remove release flags after rollout |
| Dark launch / shadow traffic | Validate under real load without user impact |
| Canary / blue-green / progressive delivery | Limit exposure; promote on healthy metrics |
| Dual write + backfill | Data model change with zero downtime |

**5. Risks**: rate `low | medium | high`, each with its evidence; rollback path per step; name the point of no return (destructive migration, external announcement) or "none".

**6. Verification**: characterization tests before touching legacy code; tests to add/adjust; rollout metrics and abort thresholds.

## Output

```markdown
## Change
<sentence> · Motivation · Compatibility: patch | minor | major
## Blast radius
| Dimension | Affected item | Evidence | Action |
## Breaking changes
| Break | Affected consumers | Mitigation |
## Strategy
Ordered steps, each independently deployable and revertible
## Risks
| Risk | Rating | Evidence | Mitigation | Rollback |
Point of no return: <step | none>
## Verification · Docs/ADRs to update · Open questions for owner
```

## Rules

- Back every affected item with evidence; "probably used somewhere" → grep it or list it as an open question.
- Prefer sequences of small reversible steps.
- A decision-level change produces an ADR (`decision-records`).
