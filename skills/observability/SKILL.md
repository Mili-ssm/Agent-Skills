---
name: observability
description: Use when adding or reviewing logging, metrics, tracing, health checks, alerting or SLOs - structured logs, OpenTelemetry, RED/USE and golden signals, SLI/SLO/error budgets, cardinality and privacy rules, with Python and Rust tooling.
---

# Observability

Goal: answer "what is broken, for whom, since when, and why" from telemetry alone, without deploying new code.

## Three signals

| Signal | Answers | Rules |
|---|---|---|
| Logs | What happened, with context | Structured (JSON), one event per line, stable keys, correlation/trace ID on every line |
| Metrics | How much / how often, cheaply over time | Low-cardinality labels; counters, histograms (latency), gauges |
| Traces | Where time went across components | Propagate W3C `traceparent`; spans for I/O boundaries |

Standard: OpenTelemetry (API + SDK + OTLP exporter) for all three.

## What to measure

| Method | For | Metrics |
|---|---|---|
| RED (Wilkie) | Request-driven services | Rate, Errors, Duration (histogram, p50/p95/p99) |
| USE (Gregg) | Resources (CPU, memory, disk, pools, queues) | Utilization, Saturation, Errors |
| Golden signals (Google SRE) | User-facing systems | Latency, traffic, errors, saturation |

## SLOs

- **SLI**: ratio of good events (e.g. requests < 300 ms and non-5xx / all requests).
- **SLO**: target over a window (99.5% / 30 days). **Error budget** = 1 − SLO; spend it on change, freeze when exhausted.
- Alert on burn rate (multi-window), not on every spike; alerts must be actionable and link a runbook.

## Logging rules

| Do | Don't |
|---|---|
| Levels: ERROR (needs action), WARN (degraded, recoverable), INFO (business events, lifecycle), DEBUG (diagnostics, off in prod) | Log and re-raise the same error at every layer |
| Include: event name, IDs (request, user hash, entity), outcome, duration | Log secrets, tokens, passwords, full PII, request bodies by default |
| Log at boundaries (incoming request, outgoing call, job start/end) | Unbounded values in metric labels (user IDs, URLs with IDs) |
| Use UTC ISO 8601 timestamps | String-concatenate messages (breaks querying) |

## Health

- `/livez` (process alive), `/readyz` (dependencies OK, ready for traffic); cheap, unauthenticated, no sensitive detail.
- Startup and shutdown logged; graceful shutdown drains requests.

## Tooling

| Need | Python | Rust |
|---|---|---|
| Structured logs | `structlog` or stdlib `logging` + JSON formatter | `tracing` + `tracing-subscriber` (JSON) |
| Traces/metrics | `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi` | `opentelemetry`, `tracing-opentelemetry` |
| Metrics endpoint | `prometheus-client` | `metrics` + `metrics-exporter-prometheus` |
| Errors | Sentry SDK | Sentry SDK |

## Review checklist

Can you trace one request end to end? Is every error logged once with context? Are latency histograms per route? Are labels bounded? Is there an SLO for the main user journey? Do alerts have runbooks?
