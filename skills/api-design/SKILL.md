---
name: api-design
description: Use when designing, reviewing or changing an HTTP API or endpoint contract (JSON or HTML/hypermedia) - HTTP semantics, status codes, idempotency, RFC 9457 errors, pagination, versioning and compatibility rules.
---

# API Design

An API is a contract; changing it costs every consumer. Design for clarity, correct HTTP semantics and evolvability.

## HTTP semantics

| Method | Safe | Idempotent | Use |
|---|---|---|---|
| GET | yes | yes | Read; never changes state |
| HEAD / OPTIONS | yes | yes | Metadata / CORS |
| POST | no | no | Create, actions, non-idempotent commands |
| PUT | no | yes | Full replace at known URI |
| PATCH | no | not by default | Partial update (JSON Merge Patch RFC 7396 / JSON Patch RFC 6902) |
| DELETE | no | yes | Remove |

## Status codes (common)

| Code | Use |
|---|---|
| 200 / 201 + `Location` / 204 | OK / created / no body |
| 303 See Other | Redirect after POST (PRG pattern) |
| 304 | Conditional GET hit (`ETag`/`If-None-Match`) |
| 400 / 422 | Malformed / semantically invalid input |
| 401 / 403 | Not authenticated / not allowed |
| 404 / 410 | Not found (also to hide existence) / permanently gone |
| 409 / 412 | Conflict / precondition failed (optimistic locking with `If-Match`) |
| 429 + `Retry-After` | Rate limited |
| 500 / 503 | Server bug / temporarily unavailable |

## Errors: RFC 9457 Problem Details (JSON APIs)

```json
{"type": "https://example.com/probs/out-of-stock", "title": "Out of stock", "status": 409,
 "detail": "Item 42 has 0 units", "instance": "/orders/123", "errors": [{"field": "qty", "msg": "max 0"}]}
```

Content type `application/problem+json`. Stable `type` URIs; no stack traces.

## Design rules

| Area | Rule |
|---|---|
| Resources | Plural nouns, hierarchical only for true ownership (`/orders/{id}/items`); actions as sub-resources or POST commands when CRUD doesn't fit |
| Naming | One case convention; consistent field names across endpoints; ISO 8601 UTC timestamps |
| Idempotency | `Idempotency-Key` header for retried POSTs that create/charge |
| Pagination | Cursor-based for large/changing sets (`next` link); limit with max |
| Filtering/sorting | Query params, allow-listed fields |
| Concurrency | `ETag` + `If-Match` for updates |
| Caching | `Cache-Control`, `ETag`, `Vary` (include `HX-Request` when the same URL serves fragment and full page) |
| Security | Authz per resource; no sensitive data in URLs; rate limits |
| Docs | OpenAPI generated from code (FastAPI does it) and reviewed as the contract |

## Hypermedia / HTML endpoints

- HTML over the wire is REST's original HATEOAS: links and forms are the contract.
- Same URL may return full page or fragment; differentiate by `HX-Request` and add `Vary: HX-Request`.
- Validation errors: return the form fragment with errors (422 requires htmx response handling config; 200 with error markup is the simple default).
- Redirects after mutations: PRG for full pages, `HX-Redirect`/`HX-Location` for htmx.
- Keep JSON APIs and HTML endpoints in separate routers when both exist.

## Compatibility (evolution)

| Non-breaking | Breaking |
|---|---|
| Add optional field / endpoint / enum value consumers tolerate | Remove/rename field, change type or meaning, make optional required, change status codes or auth |

Tolerant reader on consumers; Postel at boundaries; version only when breaking (URI `/v2` or media type), with deprecation window (`Deprecation`, `Sunset` headers). Use `change-impact` for breaking changes.
