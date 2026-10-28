---
name: observability
description: Telemetry design - wide events (canonical log lines), structured logs, OpenTelemetry traces and metrics, RED/USE, SLOs with burn-rate alerts, cardinality and privacy rules, Python and Rust tooling. Use when deciding what to log, measure, trace or alert on, adding monitoring, dashboards or health checks, or preparing a service so production incidents can be debugged quickly.
---

# Observability

Goal: answer "what is broken, for whom, since when, and why" from telemetry alone, without shipping new code.

## Signals

| Signal | Answers | Rules |
|---|---|---|
| Wide event / canonical log line (Stripe) | Everything about one request in one queryable record | One structured event per request/job at completion: route, status, duration, user/tenant hash, feature flags, DB time, retries, error class. Also emit on timeout/exception paths so failures leave a record |
| Logs | Notable moments inside a unit of work | JSON, stable keys, trace ID on every line |
| Metrics | Cheap aggregates over time | Low-cardinality labels; counters, latency histograms, gauges |
| Traces | Where time went across components | W3C `traceparent` propagation; spans at I/O boundaries; exemplars link metrics to traces |

Standard: OpenTelemetry (API + SDK + OTLP). High-cardinality fields (user, request ID) belong in events and traces, never in metric labels.

## What to measure

| Method | For | Metrics |
|---|---|---|
| RED (Wilkie) | Request-driven services | Rate, Errors, Duration (p50/p95/p99 histograms) |
| USE (Gregg) | Resources: CPU, memory, pools, queues | Utilization, Saturation, Errors |
| Golden signals (Google SRE) | User-facing systems | Latency, traffic, errors, saturation |

## SLOs and alerts

- SLI = good events / all events (e.g. requests < 300 ms and non-5xx).
- SLO = target over a window (99.5% / 30 days); error budget = 1 − SLO, spent on change, release freeze when exhausted.
- Alert on multi-window burn rate, not single spikes; every alert is actionable and links a runbook.

## Logging rules

| Do | Because |
|---|---|
| ERROR = needs action, WARN = degraded but recovered, INFO = business events and lifecycle, DEBUG off in prod | Levels must map to responses |
| Log each error once, where it is handled, with context | Re-logging at every layer floods and duplicates |
| Log at boundaries: incoming request, outgoing call, job start/end | Where latency and failures originate |
| Log IDs and hashes; exclude secrets, tokens, passwords, full PII, raw bodies | Logs are widely readable and retained |
| Structured fields, never string concatenation | Keeps logs queryable |
| UTC ISO 8601 timestamps | Cross-service correlation |
| Sample tail-based (keep errors and slow requests) | Head sampling drops the interesting cases |

## Health

`/livez` (process alive) and `/readyz` (dependencies OK): cheap, unauthenticated, no sensitive detail. Graceful shutdown drains in-flight requests.

## Non-obvious tooling

| Need | Python | Rust |
|---|---|---|
| Structured/wide events | `structlog` | `tracing` + `tracing-subscriber` (JSON) |
| OpenTelemetry | `opentelemetry-instrumentation-fastapi` | `tracing-opentelemetry` |
| Metrics endpoint | `prometheus-client` | `metrics-exporter-prometheus` |
