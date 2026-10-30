---
name: observability
description: Telemetry design method in four steps (map the request path, define wide-event and log fields, set SLIs and SLOs, alert on burn rate) with wide events (canonical log lines), structured logs, OpenTelemetry traces and metrics, RED/USE, cardinality and privacy rules, Python and Rust tooling. Use when deciding what to log, measure, trace or alert on, adding monitoring, dashboards or health checks, or preparing a service so production incidents can be debugged quickly; it designs the telemetry ahead of incidents, while diagnosing a live failure belongs to Superpowers systematic-debugging.
---

# Observability

Goal: answer "what is broken, for whom, since when, and why" from telemetry alone, without shipping new code. This skill designs the telemetry ahead of incidents; finding the cause of a failure that is happening now is debugging (Superpowers `systematic-debugging`, if installed).

## Method

Copy and tick (copy the step names as a checklist, tick each when it completes):

1. **Map** the request or job path and its failure points: follow one request or job from entry to completion and mark each I/O boundary, queue, retry and timeout, because those are where it fails or slows down and where a record must exist even when the path errors.
2. **Define the wide-event and log fields**: choose the signals below, then fix the fields: request and trace ids, tenant or user hash, route, duration, outcome, error class.
3. **Set SLIs and SLOs** for each user-facing path: SLI = good events / all events (e.g. requests < 300 ms and non-5xx); SLO = target over a window (99.5% / 30 days); error budget = 1 − SLO, spent on change, with a release freeze when exhausted. Pick metrics by what is measured: RED (rate, errors, duration) for request-driven services, USE (utilization, saturation, errors) for resources, the golden signals (latency, traffic, errors, saturation) for user-facing systems.
4. **Alert on SLO burn**: page on multi-window burn rate, not on single spikes; every alert is actionable and carries one runbook line.

## Signals

| Signal | Answers | Rules |
|---|---|---|
| Wide event / canonical log line (Stripe) | Everything about one request in one queryable record | One structured event per request/job at completion: route, status, duration, user/tenant hash, feature flags, DB time, retries, error class. Also emit on timeout/exception paths so failures leave a record |
| Logs | Notable moments inside a unit of work | JSON, stable keys, trace ID on every line |
| Metrics | Cheap aggregates over time | Low-cardinality labels; counters, latency histograms, gauges |
| Traces | Where time went across components | W3C `traceparent` propagation; spans at I/O boundaries; exemplars link metrics to traces |

Standard: OpenTelemetry (API + SDK + OTLP). High-cardinality fields (user, request ID) belong in events and traces, never in metric labels.

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

## Output

One row per signal, in this format:

<example>
| Signal | Where | Fields / metric | SLO / alert | Runbook |
|---|---|---|---|---|
| Wide event `request` | middleware, on completion and on exception | route, status, duration_ms, tenant_hash, db_ms, retries, error_class | none (queried, not alerted) | none |
| Latency histogram | middleware | `http_request_duration_seconds{route, status_class}` | 99.5% of `/checkout` requests < 300 ms over 30 days; page on fast and slow burn | Check DB pool saturation, then the last deploy |
</example>

## Non-obvious tooling

| Need | Python | Rust |
|---|---|---|
| Structured/wide events | `structlog` | `tracing` + `tracing-subscriber` (JSON) |
| OpenTelemetry | `opentelemetry-instrumentation-fastapi` | `tracing-opentelemetry` |
| Metrics endpoint | `prometheus-client` | `metrics-exporter-prometheus` |
