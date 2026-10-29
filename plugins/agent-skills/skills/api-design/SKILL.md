---
name: api-design
description: HTTP contract rules for JSON and hypermedia endpoints - status-code choices, idempotency keys, RFC 9457 errors, pagination, caching, concurrency control, versioning and compatibility (Hyrum's law). Use when designing, reviewing or changing an API, endpoint, route, webhook or response format, including retry behavior and error formats.
---

# API Design

An API is a contract; every change costs every consumer, and with enough consumers every observable behavior becomes part of it (Hyrum's law). Method semantics and common status codes are assumed known; this skill covers the decisions that usually go wrong.

## Status-code decisions

| Situation | Code |
|---|---|
| Redirect after a form POST (PRG) | 303 See Other |
| Malformed vs. semantically invalid input | 400 vs. 422 |
| Not authenticated vs. not allowed vs. hiding existence | 401 vs. 403 vs. 404 |
| State conflict / stale write | 409 / 412 with `If-Match` |

## Errors: RFC 9457 Problem Details (JSON APIs)

Members: `type` (stable URI), `title`, `status`, `detail`, `instance`, plus extensions such as `errors: [{field, msg}]` for validation. Serve as `application/problem+json`; no stack traces.

## Design rules

| Area | Rule |
|---|---|
| Resources | Plural nouns; nest only for true ownership (`/orders/{id}/items`); non-CRUD actions as POST commands or sub-resources |
| Naming | One case convention; same field names across endpoints; ISO 8601 UTC timestamps |
| Retries | `Idempotency-Key` header on POSTs that create or charge; PUT/DELETE idempotent by design |
| Pagination | Cursor-based for large or changing sets (`next` link); enforced max limit |
| Filtering/sorting | Query params over allow-listed fields |
| Concurrency | `ETag` + `If-Match` on updates |
| Caching | `Cache-Control`, `ETag`; `Vary` on every header that changes the response |
| Security | Per-resource authz; no secrets in URLs; rate limits |
| Contract | OpenAPI generated from code and reviewed as the contract; consumer-driven contract tests for key consumers |

## Hypermedia / HTML endpoints

Default for htmx projects (configurable):

- HTML over the wire is REST's HATEOAS: links and forms are the contract (rule of least power: no client-side state machine needed).
- One URL may serve a full page or a fragment: branch on `HX-Request` and send `Vary: HX-Request`.
- Validation errors: return the form fragment with errors. htmx 2.x skips swapping 4xx/5xx responses by default, so either return 200 with error markup (simple default) or configure `htmx.config.responseHandling` for 422.
- After mutations: PRG for full pages; `HX-Redirect`/`HX-Location` for htmx.
- Keep JSON APIs and HTML endpoints in separate routers.

## Compatibility

| Non-breaking | Breaking |
|---|---|
| Add optional field, endpoint, or an enum value consumers tolerate | Remove/rename a field; change type, meaning, status codes, auth, ordering or error format; make optional required |

Consumers use tolerant readers; version only for breaking changes (`/v2` or media type) with a deprecation window (`Deprecation`, `Sunset` headers). Breaking changes go through `change-impact`.

## Review output

One row per violation, naming the rule from the tables above:

<example>
| Endpoint | Rule violated | Fix |
|---|---|---|
| POST /orders | Retries: a charging POST without `Idempotency-Key` | Accept the header and replay the stored response for a repeated key |
</example>
