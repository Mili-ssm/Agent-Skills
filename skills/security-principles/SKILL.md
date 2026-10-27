---
name: security-principles
description: Use when threat modeling, reviewing code or designs for security, handling auth, secrets, user input, file uploads, dependencies or sensitive data - STRIDE, OWASP Top 10 and ASVS themes, CWE classes, secure design principles and Python/Rust/web specifics.
---

# Security Principles

Find exploitable paths, not theoretical ones: every finding needs a source (attacker-controlled input), a sink (dangerous operation) and the missing control between them.

## Index

| Need | Reference |
|---|---|
| Threat modeling (STRIDE, trust boundaries, DFD, attack trees) | [threat-modeling.md](references/threat-modeling.md) |
| Review checklist (OWASP themes, ASVS areas, language/web specifics, supply chain) | [checklist.md](references/checklist.md) |

## Secure design principles (Saltzer & Schroeder + modern)

| Principle | Meaning |
|---|---|
| Least privilege | Minimal rights for users, services, tokens, DB roles |
| Defense in depth | Multiple independent controls |
| Fail securely / closed | Errors deny access, never grant it |
| Complete mediation | Check authorization on every access, server-side |
| Secure defaults | Safe out of the box; opt-in to risk |
| Economy of mechanism | Simple, small, reviewable security code |
| Separation of privilege | Critical actions need more than one condition |
| Minimize attack surface | Remove unused endpoints, features, deps |
| Don't trust the client | All client data is attacker-controlled (headers, cookies, hidden fields, HX-* headers) |
| Zero trust | Authenticate and authorize every request regardless of network |
| Use vetted crypto | Never roll your own; libraries with safe defaults |

## Severity

| Level | Criteria |
|---|---|
| critical | Remote, unauthenticated, high impact (RCE, auth bypass, mass data exposure) |
| high | Authenticated or conditional but high impact; or unauthenticated medium impact |
| medium | Requires unusual conditions; limited data/function |
| low | Defense-in-depth gap, hard to exploit |
| info | Hardening suggestion |

Rate by exploitability × impact; state attacker preconditions.

## Process

1. Context: assets, actors, trust boundaries (threat model if none exists).
2. Enumerate entry points: routes, forms, uploads, webhooks, CLI args, env, message queues, deserialization.
3. Trace sources → sinks; check controls (validation, encoding, authz, rate limits).
4. Run available scanners (`pip-audit`, `cargo audit`, `cargo deny`, `bandit`, `semgrep`, secret scanners) and triage results; scanners are leads, not findings.
5. Report exploitable findings with proof path and fix; hardening separately.
