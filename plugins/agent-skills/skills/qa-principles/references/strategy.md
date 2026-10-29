# Test strategy

## Shapes

| Model | Emphasis | Fits |
|---|---|---|
| Pyramid (Cohn) | Many unit, fewer integration, few E2E | Logic-heavy libraries, Rust crates |
| Trophy (Dodds) | Integration-heavy on a static-analysis base | Web apps where wiring is the risk |
| Honeycomb | Service integration | Microservices |

Choose by where defects actually occur.

## Sizes (Google) over levels

| Size | Constraints | Typical |
|---|---|---|
| Small | One process, no I/O, no sleep; hermetic | Unit, property |
| Medium | One machine; localhost services, real DB in container | Integration via ASGI/test server |
| Large | Multi-machine or external systems | E2E, staging |

Hermetic tests (all dependencies controlled) are deterministic; non-hermetic ones belong to a separate, retry-aware suite.

## Risk-based testing

Rate risk with the levels in the workflow (SKILL.md, step 1); new technology also raises likelihood, and legal or trust exposure raises impact. Depth proportional to risk; record accepted untested risk.

## Techniques by need

| Need | Technique |
|---|---|
| Producer/consumer agreement | Contract tests (consumer-driven, OpenAPI checks) |
| Legacy behavior to preserve | Characterization / golden master / approval tests |
| Concurrency or distributed logic | Stateful property tests; deterministic simulation testing (seeded clock, scheduler and I/O; replay failures by seed) |
| Resilience | Fault injection, chaos experiments with a hypothesis and abort condition |
| Parser/decoder robustness | Fuzzing |
| Production confidence (shift right) | Canary analysis, synthetic monitoring, feature-flag rollouts |
| Test strength | Mutation testing on high-risk modules (score = killed/total; review surviving mutants manually, some are equivalent) |

## E2E scope (Playwright)

- Critical journeys only; push edge cases down to medium tests.
- Locate by role/label/text (`get_by_role`), because CSS/XPath break on refactors.
- Wait on conditions (`expect`, auto-wait); fixed sleeps and `networkidle` cause flakes.
- Isolate data per test so tests run in parallel.
- Server-rendered/htmx apps: assert on the swapped DOM; also test with JS disabled for progressive enhancement.

## Flaky tests

| Root cause | Fix |
|---|---|
| Timing / async races | Await conditions; deterministic clocks |
| Shared state / order dependence | Isolated fixtures; random order |
| External services | Fakes or contract tests |
| Time, randomness, locale | Inject clock, seed RNG, pin locale/TZ |
| Resource leaks | Proper teardown; detect with repeated runs |

Quarantine is a temporary label with an owner and a date; the defect stays open until fixed.

Static analysis (`pyright`, `ruff`, compiler, `clippy`) removes whole defect classes cheaply; count it in the strategy.
