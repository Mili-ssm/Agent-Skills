---
name: qa-principles
description: Test design and test strategy toolkit - ISTQB techniques, SFDPOT and HICCUPPS heuristics, property-based, stateful and mutation testing, test doubles, test smells and flaky-test causes. Use when deciding which test cases to write for a function or feature, assessing a test suite or strategy, hunting coverage gaps, or fixing flaky tests.
---

# QA Principles

Testing answers "what could go wrong, and would we notice?". Coverage counts lines executed, not defects caught (Goodhart: as a target it stops measuring). Complements TDD (Superpowers, if installed): TDD decides **when** to write a test; this skill decides **what** to test and **how well**.

## Index

| Need | Reference |
|---|---|
| Deriving cases: partitions, boundaries, decision tables, states, pairwise, SFDPOT, HICCUPPS oracles, properties | [test-design.md](references/test-design.md) |
| Strategy: shapes, risk-based, sizes, contract, stateful/simulation, mutation, E2E scope, flakiness | [strategy.md](references/strategy.md) |
| Test quality: FIRST, AAA, doubles, smells, DAMP | [test-quality.md](references/test-quality.md) |

## Principles that drive the workflow

- Exhaustive testing is impossible → prioritize by risk (likelihood × impact).
- Defects cluster → test churn hotspots harder.
- Pesticide paradox → vary and extend tests; property-based and exploratory testing find what fixed cases miss.
- Beyoncé rule: if you depend on a behavior, put a test on it.

## Non-obvious tooling

| Concern | Python | Rust |
|---|---|---|
| Property-based / stateful | `hypothesis` (`RuleBasedStateMachine`) | `proptest`, `proptest-state-machine` |
| Mutation | `mutmut` | `cargo-mutants` |
| Snapshot / approval | `syrupy`, `inline-snapshot` | `insta` |
| Fuzzing | `atheris`, `hypothesis` | `cargo fuzz` |
| Random order / flake detection | `pytest-randomly`, `pytest-repeat` | `cargo nextest` (`--retries` only to detect) |
| Branch coverage | `coverage.py --branch` | `cargo llvm-cov` |

## Assessment workflow

The `qa-engineer` agent follows this workflow; use it inline for one function or feature.

1. **Risk map**: features/modules × likelihood (churn, complexity, defect history) × impact (money, data, security, UX).
2. **Inventory** tests per feature and size; find untested high-risk areas.
3. **Design** missing cases, naming the technique; properties for logic with invariants, stateful properties for APIs with sequences.
4. **Quality**: test smells, over-mocking, assertion-free tests, flakiness sources.
5. **Strength**: mutation testing on high-risk modules; each surviving mutant is a missing assertion.
6. **Report** gaps as ready-to-implement cases.

<example>
| ID | Area | Technique | Input / precondition | Expected | Size |
|----|------|-----------|----------------------|----------|------|
| T4 | discount() | BVA | total=99.99, member, no coupon | no member discount (threshold 100) | small |
</example>
