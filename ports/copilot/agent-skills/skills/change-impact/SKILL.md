---
name: change-impact
description: Maps the blast radius of a significant change - callers, contracts, data, docs, consumers, breaking changes, migration strategy (expand/contract, flags, strangler), rollout, rollback and point of no return. Use when planning or about to implement a rename, schema or API change, dependency swap, removal or boundary refactor, or when asked what a change will affect and how to roll it out safely.
---

# Change Impact Analysis

Run before writing the implementation plan, because the plan inherits the blast radius. Unclear motivation → run `intent-elicitation` in `change` mode first.

## Workflow

Copy and tick (copy the step names as a checklist, tick each when it completes):

**1. Change**: state the change and its motivation in one sentence each.

**2. Blast radius** (Hyrum's law: every observable behavior may have a consumer), with evidence per row:

| Dimension | How to find |
|---|---|
| Direct callers / importers | Grep symbol, module, route, template names (repo-wide → dispatch `explore` (built-in agent)) |
| Public contracts | HTTP routes, CLI flags, library API, events, file formats, env vars, error messages |
| Data | Schemas, migrations, stored formats, caches, serialized objects |
| Config / infra | Settings, CI, deployment manifests, feature flags |
| Tests | Covering tests; tests that must change |
| Docs / ADRs | Claims and decisions made false (large scope: dispatch `consistency-auditor` in `change` mode) |
| People / systems | Consumers outside the repo, other teams, scheduled jobs |
| Non-functional | Performance, security surface, accessibility, cost |

Above ~20 rows, group by directory. State the search commands used (for example `rg -n 'user_id'`), so the owner can rerun them.

Light path: when the step 2 rows show one module, every caller in the repo, covering tests and no public contract (route, CLI flag, env var, file format, error message), skip steps 3–5 and finish with 6 and 7.

**3. Compatibility**: `patch` (no contract change) · `minor` (additive) · `major` (breaking: list each break and who it hits).

**4. Strategy**:

| Strategy | Use when |
|---|---|
| Direct change | Internal, all callers in repo, covered by tests |
| Parallel change (expand → migrate → contract) | Contracts or schemas with live consumers; an interface with many callers |
| Branch by abstraction (abstraction → route callers → new implementation behind it → switch → delete old) | Replace an internal component incrementally on trunk |
| Strangler fig (intercept the entry point → move features one by one → retire legacy) | Replace a subsystem or legacy app route by route |
| Feature flag | Risky behavior; fast off-switch; remove release flags after rollout |
| Dark launch / shadow traffic | Validate under real load without user impact |
| Canary / blue-green / progressive delivery | Limit exposure; promote on healthy metrics |
| Dual write + backfill | Data model change with zero downtime |

**5. Risks**: rate each `low | medium | high` with its evidence, using the criteria below; rollback path per step; name the point of no return (destructive migration, external announcement) or "none".

| Rating | Criteria |
|---|---|
| high | Data loss or corruption, an irreversible step, security exposure, or external consumers broken without mitigation |
| medium | Internal callers broken, or a coordinated deploy or migration with rollback available |
| low | Local, covered by tests, trivially reversible |

**6. Verification**: characterization tests before touching legacy code; run suites through `check-runner`; tests to add/adjust; rollout metrics and abort thresholds.

**7. Docs and ADRs**: list the docs and ADRs the change makes false and update them in the same change.

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

- Back every affected item with evidence, because the plan inherits every gap in this map; "probably used somewhere" → grep it or list it as an open question.
- Prefer sequences of small reversible steps, because each one can be rolled back alone.
- A decision-level change produces an ADR (`decision-records`).
