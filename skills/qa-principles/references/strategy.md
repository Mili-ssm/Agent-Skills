# Test strategy

## Shapes

| Model | Emphasis | Fits |
|---|---|---|
| Pyramid (Cohn) | Many unit, fewer integration, few E2E | Logic-heavy libraries, Rust crates |
| Trophy (Dodds) | Integration-heavy, static analysis base | Web apps where wiring is the risk |
| Honeycomb | Integration of services | Microservices |

Choose by where defects actually occur, not dogma.

## Risk-based testing

Risk = likelihood × impact. Likelihood: complexity, churn, new tech, defect history. Impact: money, data loss, security, legal, user trust. Test depth proportional to risk; document accepted untested risk.

## Levels

| Level | Verifies | Doubles allowed |
|---|---|---|
| Unit | Logic in isolation | Fakes for I/O |
| Integration | Real collaborators (DB, filesystem, HTTP app via ASGI) | External third parties only |
| Contract | Producer/consumer agree on schema (Pact, OpenAPI checks) | Consumer side |
| E2E | User journeys through real UI | None (or sandbox external services) |
| Non-functional | Performance, security, accessibility | Varies |

## E2E scope (Playwright)

- Critical user journeys only (login, checkout, core CRUD); push edge cases down to integration.
- Locators by role/label/text (`get_by_role`), not CSS/XPath.
- Wait on conditions (auto-wait, `expect`), never fixed sleeps or `networkidle`.
- Isolate data per test; parallel-safe.
- Server-rendered/htmx apps: assert on swapped DOM; also test with JS disabled for progressive enhancement.

## Mutation testing

Introduces small faults (mutants); a surviving mutant means no test detects that change. Mutation score = killed / total. Run on high-risk modules, not whole repos (slow). Equivalent mutants exist; review survivors manually.

## Flaky tests

| Root cause | Fix |
|---|---|
| Timing / async races | Await conditions; deterministic clocks |
| Shared state / order dependence | Isolate fixtures; random order (`pytest-randomly`) |
| External services | Fakes or contract tests |
| Time, randomness, locale | Inject clock, seed RNG, fix locale/TZ |
| Resource leaks | Proper teardown; detect with repeat runs (`pytest --count`, `nextest --retries` only to detect) |

Quarantine is a temporary label with an owner and date, never a fix.

## Static analysis as test layer

Type checkers (`pyright`, `mypy`, Rust compiler), linters (`ruff`, `clippy`), and `#[deny]` lints catch whole defect classes cheaply; count them in the strategy.
