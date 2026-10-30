# Styles and patterns

## Architectural styles

| Style | Fits when | Cost / risk |
|---|---|---|
| Layered | Simple CRUD, small team | Leaky layers, anemic domain |
| Hexagonal (ports & adapters, Cockburn) | Domain logic worth isolating; many I/O adapters | Indirection; overkill for scripts |
| Clean / Onion | As hexagonal, stricter rings | Mapping boilerplate between rings |
| Vertical slice | Features vary in complexity; change is per feature | Duplication across slices; shared rules need a home |
| Modular monolith | Most products; enforced modules, one deployable | Needs boundary enforcement (fitness functions) |
| Microservices | Independent deploy/scale per team at org scale | Distributed-systems tax, data consistency, ops |
| Event-driven | Decoupled reactions, async workflows, audit | Debuggability, eventual consistency, ordering |
| Pipes and filters | Transformation chains | Shared state awkward |
| Hypermedia-driven application (HDA) | Server-rendered UI with partial updates (htmx) | Rich offline/client state is harder |
| Microkernel / plugin | Stable core, many optional extensions | Plugin API is a long-lived contract (Hyrum) |
| Cell-based | Blast-radius isolation at scale | Routing and data partitioning complexity |

Styles combine (e.g. modular monolith of vertical slices with hexagonal cores).

## Domain-Driven Design (Evans, Vernon)

| Strategic | Tactical |
|---|---|
| Ubiquitous language, bounded context, context map (shared kernel, customer/supplier, conformist, anticorruption layer, open host, published language), core/supporting/generic subdomains, Event Storming for discovery | Entity, value object, aggregate (consistency boundary, reference by ID), domain event, repository, domain service |

## Reliability and integration

| Pattern | Use |
|---|---|
| Sans-IO | Protocol/parsing logic as pure state machines; I/O adapters per runtime (sync/async, Python/Rust) |
| Idempotent consumer + outbox | Exactly-once effects over at-least-once delivery |
| Saga (orchestration/choreography) | Multi-step workflows without distributed transactions |
| Circuit breaker, bulkhead, timeout, retry with backoff + jitter | Contain failing dependencies |
| Backpressure, load shedding | Stay up under overload instead of queueing forever |
| Supervision / let it crash (Erlang) | Restart isolated workers from known state instead of defensive code everywhere |
| CQRS, event sourcing | Read/write models diverge; audit history matters (costly: use only when demanded) |
| Strangler fig, anticorruption layer, BFF, API gateway | Migration and integration boundaries |

Enterprise (Fowler, PoEAA) and GoF patterns are assumed known; many GoF patterns collapse into functions/closures in Python and Rust.

## Language idioms

| Python | Rust |
|---|---|
| `Protocol` for structural interfaces | Traits; generics vs. `dyn Trait` trade-off |
| Dependency injection via parameters / FastAPI `Depends` | Newtype for domain invariants |
| Dataclasses / Pydantic as value objects; parse at the edge | Typestate (state in the type) |
| Context managers for resources | RAII, ownership as resource policy |
| Modules over singletons; avoid metaclass magic | `Result` + `?`; `thiserror` (lib) / `anyhow` (bin) |
| Generators for pipelines | Iterators; enums for closed sets |
