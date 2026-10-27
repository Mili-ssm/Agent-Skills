# 0004 Rubrics over numeric probabilities

Status: accepted · Date: 2026-10-27

## Context

R4 asks how likely a documented decision needs revisiting. Model-generated percentages are uncalibrated and imply false precision.

## Decision

Rate with an observable-signal rubric (`skills/decision-records/references/staleness-rubric.md`) yielding `low | medium | high`, always listing the signals that fired. Same pattern for risk (pre-mortem, change-impact, security).

## Consequences

Ratings are auditable and reproducible; no cross-project numeric comparison.

## Revisit if

A calibrated data source (e.g. historical decision outcomes) becomes available.
