# Requirements quality

## Characteristics (ISO/IEC/IEEE 29148)

| Characteristic | Test |
|---|---|
| Necessary | Removing it loses something the owner needs |
| Unambiguous | One interpretation only |
| Verifiable | A test or inspection can prove it |
| Consistent | No conflict with other requirements, ADRs, constraints |
| Complete | Conditions, actor and expected response present |
| Feasible | Achievable within constraints |
| Traceable | Has an ID and a source (owner answer, ADR, regulation) |
| Singular | States one thing |
| Implementation-free | States what, not how (unless it is a constraint) |

## Ambiguity markers

*fast, easy, user-friendly, robust, scalable, flexible, secure, minimal, appropriate, support, handle, etc., and/or, as needed, if possible, normally*. Replace with a measurable criterion or concrete behavior.

## EARS templates (Mavin et al.)

| Pattern | Template |
|---|---|
| Ubiquitous | The `<system>` shall `<response>`. |
| Event-driven | When `<trigger>`, the `<system>` shall `<response>`. |
| State-driven | While `<state>`, the `<system>` shall `<response>`. |
| Unwanted behavior | If `<condition>`, then the `<system>` shall `<response>`. |
| Optional feature | Where `<feature is included>`, the `<system>` shall `<response>`. |
| Complex | While `<state>`, when `<trigger>`, the `<system>` shall `<response>`. |

<example>
When a form submission fails validation, the server shall return the form fragment with inline error messages and the submitted values within 300 ms p95.
</example>

User stories (if the team uses them): INVEST; acceptance criteria as Given-When-Then.

## Classification

| Kind | Example | Changes when |
|---|---|---|
| Functional requirement | Export orders as CSV | Owner needs change |
| Quality requirement | p95 < 300 ms | SLO renegotiated |
| Constraint | Python 3.12, no new JS | External force changes |
| Assumption | < 1000 daily users | Evidence contradicts it → revisit dependents |
| Preference | Tables over prose | Owner says so |
