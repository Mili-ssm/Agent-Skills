# Staleness / revisit rubric

Applies to ADRs, documented requirements and implicit decisions found in code. Output: `revisit: low | medium | high` + fired signals + one question that would resolve it.

## Signals

| # | Signal | Weight | How to detect |
|---|---|---|---|
| S1 | Code contradicts the decision | high | Read code paths the decision governs |
| S2 | A stated assumption no longer holds (scale, team, platform, dependency, law) | high | Compare assumption with current config, deps, metrics |
| S3 | High churn in governed code since decision date | high | `git log --since=<date> --oneline -- <paths> \| wc -l` vs. churn before |
| S4 | Decision superseded in practice but not on paper (new pattern coexists) | high | Grep for both old and new approach |
| S5 | Major version change of a dependency the decision relies on | medium | Lockfiles / manifests vs. decision text |
| S6 | No rationale or alternatives recorded | medium | Missing Context/Alternatives sections |
| S7 | Old (>18 months) with no review mark | medium | Date line, `git log -1 -- <adr>` |
| S8 | Behavior not pinned by tests | low | Search tests for the governed behavior |
| S9 | Author/owner no longer active | low | `git shortlog -sn -- <paths>` |

## Aggregation

| Result | Rule |
|---|---|
| high | ≥ 1 high signal, or ≥ 3 medium |
| medium | 1–2 medium, or ≥ 2 low |
| low | otherwise |

Contradiction (S1) is always reported as a finding, independent of rating.

## Finding format

```markdown
| ID | Decision (source) | Revisit | Signals | Evidence | Question for owner |
|----|-------------------|---------|---------|----------|--------------------|
| D3 | Use SQLite (docs/adr/0002) | high | S2, S3 | deploy.yaml:12 runs 3 replicas | Is multi-replica deployment intended long-term? |
```
