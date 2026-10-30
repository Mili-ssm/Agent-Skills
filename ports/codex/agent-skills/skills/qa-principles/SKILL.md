---
name: qa-principles
description: Test design and test strategy toolkit - ISTQB techniques, SFDPOT and HICCUPPS heuristics, property-based, stateful and mutation testing, test doubles, test smells and flaky-test causes. Use when deciding which test cases to write for a function or feature, assessing a test suite or strategy, hunting coverage gaps, or fixing flaky tests, but not for the red-green-refactor loop itself (Superpowers test-driven-development); load it before answering so each case names its technique and the risk it covers.
---

# QA Principles

Testing answers "what could go wrong, and would we notice?". Complements TDD (Superpowers, if installed): TDD decides **when** to write a test; this skill decides **what** to test and **how well**.

## Index

| Workflow step | Open | For |
|---|---|---|
| 1 Risk map, 2 Inventory | [strategy.md](references/strategy.md) | Shapes, sizes, risk-based testing, E2E scope |
| 3 Design | [test-design.md](references/test-design.md) | Partitions, boundaries, decision tables, states, pairwise, SFDPOT, HICCUPPS oracles, properties |
| 4 Quality | [test-quality.md](references/test-quality.md), [strategy.md](references/strategy.md) | FIRST, AAA, doubles, smells, DAMP; flaky-test root causes |
| 5 Strength | [strategy.md](references/strategy.md) | Mutation testing, contract, stateful/simulation and other techniques by need |

## Principles that drive the workflow

- Goodhart's law: coverage counts lines executed, not defects caught, and as a target it stops measuring; pair it with mutation score.
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

## Assessment workflow (the `qa-engineer` agent runs it in full; inline for one function or feature)

1. **Risk map**: rate each feature or module `low | medium | high`, noting the signals behind each level:
   - likelihood from churn, complexity and defect history, relative to the rest of the codebase;
   - impact: high = data, money, security or core flow; medium = secondary flow; low = cosmetic;
   - risk: high when impact is high and likelihood is not low; low when both are low; medium otherwise.
2. **Inventory** tests per feature and size (main conversation: `explorer` (built-in role) maps them, `check-runner` runs them); find untested high-risk areas.
3. **Design** missing cases, naming the technique; properties for logic with invariants, stateful properties for APIs with sequences.
4. **Quality**: test smells, over-mocking, assertion-free tests, flakiness sources.
5. **Strength**: mutation testing on high-risk modules; each surviving mutant is a missing assertion.
6. **Report** gaps as ready-to-implement cases.

<example>
| ID | Area | Technique | Input / precondition | Expected | Size |
|----|------|-----------|----------------------|----------|------|
| T4 | discount() | BVA | total=99.99, member, no coupon | no member discount (threshold 100) | small |
</example>
