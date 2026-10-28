# Staleness rubric

Rates ADRs, documented requirements and implicit decisions found in code. Output: revisit rating `low | medium | high` + fired signals + the one question that would resolve it.

Ratings use levels, never percentages: no calibration data exists, so a number would imply precision the evidence lacks.

## Signals

| # | Signal | Weight | How to detect |
|---|---|---|---|
| S1 | Code contradicts the decision | high | Read the code paths it governs |
| S2 | A stated assumption no longer holds (scale, team, platform, dependency, law) | high | Compare with current config, deps, metrics |
| S3 | High churn in governed code since the decision date | high | `git log --since=<date> --oneline -- <paths> \| wc -l` vs. churn before |
| S4 | Superseded in practice but not on paper (new approach coexists) | high | Grep both approaches |
| S5 | Major version change of a dependency it relies on | medium | Lockfiles/manifests vs. decision text |
| S6 | No rationale or alternatives recorded | medium | Missing Context/Alternatives |
| S7 | Older than 18 months, never reviewed | medium | Date line, `git log -1 -- <adr>` |
| S8 | Behavior not pinned by tests | low | Search tests for the governed behavior |
| S9 | Author/owner no longer active | low | `git shortlog -sn -- <paths>` |

## Aggregation

| Rating | Rule |
|---|---|
| high | ≥ 1 high signal, or ≥ 3 medium |
| medium | 1–2 medium, or ≥ 2 low |
| low | otherwise |

S1 is also always reported as a contradiction finding.

<example>
| ID | Decision (source) | Revisit | Signals | Evidence | Question for owner |
|----|-------------------|---------|---------|----------|--------------------|
| D3 | Use SQLite (docs/adr/0002) | high | S2, S3 | deploy.yaml:12 runs 3 replicas | Is multi-replica deployment intended long-term? |
</example>
