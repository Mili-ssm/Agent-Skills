---
name: qa-principles
description: Use when designing test cases, assessing a test suite or test strategy, hunting coverage gaps, fixing flaky tests or judging test quality - ISTQB test design techniques, risk-based strategy, property-based and mutation testing, test doubles and test smells.
---

# QA Principles

Testing answers "what could go wrong, and would we notice?". Coverage measures lines executed, not behavior verified. Complements Superpowers TDD: TDD decides **when** to write a test; this skill decides **what** to test and **how well**.

## Index

| Need | Reference |
|---|---|
| Deriving test cases (partitions, boundaries, decision tables, states, pairwise) | [test-design.md](references/test-design.md) |
| Strategy (pyramid/trophy, risk-based, contract, property, mutation, E2E scope) | [strategy.md](references/strategy.md) |
| Test quality (FIRST, AAA, test doubles, test smells, flakiness) | [test-quality.md](references/test-quality.md) |

## Seven testing principles (ISTQB)

1. Testing shows presence of defects, not their absence.
2. Exhaustive testing is impossible → prioritize by risk.
3. Early testing saves cost (shift left).
4. Defects cluster (Pareto) → test hotspots harder.
5. Pesticide paradox → vary and extend tests over time.
6. Testing is context dependent.
7. Absence-of-errors fallacy: passing tests ≠ useful system.

## Tooling map

| Concern | Python | Rust | Web |
|---|---|---|---|
| Runner | `pytest` | `cargo test`, `cargo nextest` | Playwright Test / `pytest-playwright` |
| Property-based | `hypothesis` | `proptest`, `quickcheck` | — |
| Mutation | `mutmut`, `cosmic-ray` | `cargo-mutants` | — |
| Coverage | `coverage.py` (`--branch`) | `cargo llvm-cov` | Playwright coverage (Chromium) |
| Snapshot | `syrupy`, `inline-snapshot` | `insta` | Playwright screenshots |
| Fuzzing | `atheris`, `hypothesis` | `cargo fuzz` | — |
| HTTP | `httpx` + ASGI transport | `reqwest` + test server | Playwright `request` |

## Assessment process

1. **Risk map**: list features/modules; rate likelihood (churn, complexity, history) × impact (money, data, security, UX).
2. **Inventory** tests per feature and level (unit/integration/E2E); find untested high-risk areas.
3. **Design** missing cases with test-design techniques; prefer properties for logic with invariants.
4. **Quality**: scan for test smells, over-mocking, assertion-free tests, flakiness sources.
5. **Strength**: run mutation testing on high-risk modules if tooling exists; surviving mutants = missing assertions.
6. **Report** gaps as ready-to-implement cases.
