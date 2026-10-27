# Requirements quality

## Characteristics (ISO/IEC/IEEE 29148)

| Characteristic | Test |
|---|---|
| Necessary | Removing it loses something the owner needs |
| Unambiguous | One interpretation only; no vague terms |
| Verifiable | A test or inspection can prove it |
| Consistent | No conflict with other requirements, ADRs or constraints |
| Complete | Includes conditions, actors and expected response |
| Feasible | Achievable within constraints |
| Traceable | Has an ID and source (owner answer, ADR, regulation) |
| Singular | States one thing |
| Implementation-free | States what, not how (unless a constraint) |

## Ambiguity markers

Vague: *fast, easy, user-friendly, robust, scalable, flexible, secure, minimal, appropriate, support, handle, etc., and/or, as needed, if possible, normally*. Replace with measurable criteria or concrete behavior.

## EARS templates (Mavin et al.)

| Pattern | Template |
|---|---|
| Ubiquitous | The `<system>` shall `<response>`. |
| Event-driven | When `<trigger>`, the `<system>` shall `<response>`. |
| State-driven | While `<state>`, the `<system>` shall `<response>`. |
| Unwanted behavior | If `<condition>`, then the `<system>` shall `<response>`. |
| Optional feature | Where `<feature is included>`, the `<system>` shall `<response>`. |
| Complex | While `<state>`, when `<trigger>`, the `<system>` shall `<response>`. |

Example: *When a form submission fails validation, the server shall return the form fragment with inline error messages and preserved input within 300 ms p95.*

## User stories (when the team uses them)

INVEST: Independent · Negotiable · Valuable · Estimable · Small · Testable. Acceptance criteria as Given-When-Then.

## Classification

| Kind | Example | Changes when |
|---|---|---|
| Functional requirement | Export CSV of orders | Owner needs change |
| Quality requirement | p95 < 300 ms | SLO renegotiated |
| Constraint | Must run on Python 3.12, no new JS | External force changes |
| Assumption | < 1000 daily users | Evidence contradicts → revisit dependents |
| Preference | Prefers tables over prose | Owner says so |
