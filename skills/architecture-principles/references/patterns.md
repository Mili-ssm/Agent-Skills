# Styles and patterns

## Architectural styles

| Style | Fits when | Cost / risk |
|---|---|---|
| Layered | Simple CRUD, small team | Layers leak; domain anemic |
| Hexagonal (ports & adapters, Cockburn) | Domain logic worth isolating; many I/O adapters | Indirection; overkill for scripts |
| Clean / Onion | Same as hexagonal, stricter rings | Boilerplate mapping between rings |
| Modular monolith | Most products; clear modules, one deployable | Needs enforced boundaries |
| Microservices | Independent scaling/deploy per team; org scale | Distributed systems tax, ops, data consistency |
| Event-driven | Decoupled reactions, async workflows, audit | Debuggability, eventual consistency, ordering |
| Pipes and filters | Data transformation chains | Shared state awkward |
| Functional core / imperative shell | Logic-heavy code, high testability | Discipline at boundaries |

## Domain-Driven Design (Evans, Vernon)

| Strategic | Tactical |
|---|---|
| Ubiquitous language, bounded context, context map (shared kernel, customer/supplier, conformist, anticorruption layer, open host, published language), core/supporting/generic subdomains | Entity, value object, aggregate (consistency boundary, reference by ID), domain event, repository, domain service, factory |

## Enterprise (Fowler, PoEAA)

Transaction script · Domain model · Service layer · Repository · Unit of work · Data mapper vs. Active record · Identity map · Gateway · DTO · Lazy load.

## Integration / distributed

CQRS · Event sourcing · Saga (choreography/orchestration) · Outbox · Idempotent consumer · Circuit breaker · Bulkhead · Retry with backoff + jitter · Strangler fig · Backend-for-frontend · API gateway · Anticorruption layer.

## GoF (most useful today)

| Category | Patterns |
|---|---|
| Creational | Factory method, Abstract factory, Builder |
| Structural | Adapter, Facade, Decorator, Composite, Proxy |
| Behavioral | Strategy, Observer, Command, State, Template method, Iterator, Chain of responsibility |

Many collapse into first-class functions/closures in Python and Rust.

## Language idioms

| Python | Rust |
|---|---|
| `Protocol` for structural interfaces | Traits; generics vs. `dyn Trait` trade-off |
| Dependency injection via parameters / FastAPI `Depends` | Newtype for domain invariants |
| Dataclasses / Pydantic as value objects | Typestate (state in the type) |
| Context managers for resources | RAII, ownership as resource policy |
| Modules as singletons; avoid metaclass magic | `Result`/`?` error flow; `thiserror` (lib) / `anyhow` (bin) |
| Generators for pipelines | Iterators; enums for closed sets |
