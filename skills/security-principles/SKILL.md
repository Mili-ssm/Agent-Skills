---
name: security-principles
description: Security review checklist that traces attacker input to dangerous sinks and rates exploitability - STRIDE, OWASP Top 10 and ASVS themes, and Python, Rust and htmx sinks with safe fixes. Use when asked whether code, an endpoint or a design is safe, or to check for vulnerabilities (injection, XSS, CSRF, SSRF, auth flaws), secrets, uploads or redirects; load it before answering so findings follow its source-sink format and severity scale.
---

# Security Principles

Report exploitable paths, not theoretical ones: every finding names a **source** (attacker-controlled input), a **sink** (dangerous operation) and the **missing control** between them. Scanner hits without such a path are mostly false positives.

## Index

| Need | Reference |
|---|---|
| Threat modeling: four questions, DFD, STRIDE, attack trees, LINDDUN | [threat-modeling.md](references/threat-modeling.md) |
| Review checklist: OWASP themes, ASVS areas, Python/Rust/web sinks, supply chain, secrets | [checklist.md](references/checklist.md) |

## Secure design principles

| Principle | Meaning |
|---|---|
| Least privilege / least authority | Minimal rights for users, services, tokens, DB roles |
| Defense in depth | Independent layered controls |
| Fail closed | Errors deny access |
| Complete mediation | Authorize every access server-side, per object |
| Secure by default | Safe out of the box; risk is opt-in |
| Economy of mechanism | Small, reviewable security code |
| Minimize attack surface | Remove unused endpoints, features, dependencies |
| Distrust the client | Headers, cookies, hidden fields, `HX-*` headers are attacker-controlled |
| Canonicalize, then validate | Normalize paths, encodings, Unicode before checks |
| Avoid confused deputies | A privileged component acts only with the caller's authority |
| Check-and-use atomically | Prevent TOCTOU races (files, balances, permissions) |
| Vetted crypto | Libraries with safe defaults; never custom primitives |

## Severity

| Level | Criteria |
|---|---|
| critical | Remote, unauthenticated, high impact (RCE, auth bypass, mass data exposure) |
| high | Authenticated/conditional with high impact, or unauthenticated medium impact |
| medium | Unusual preconditions; limited data or function |
| low | Defense-in-depth gap, hard to exploit |
| info | Hardening suggestion |

Rate by exploitability × impact and state the attacker's preconditions.

## Review workflow

The `security-reviewer` agent follows this workflow; use it inline for a snippet or endpoint.

1. Context: assets, actors, trust boundaries (threat model if none exists).
2. Entry points: routes, forms, uploads, webhooks, CLI args, env, queues, deserialization, templates rendering user data.
3. Trace sources → sinks; check validation, encoding, authorization, rate limits.
4. Triage available scanner output as leads.
5. Report exploitable findings with proof path and minimal fix; hardening separately.

<example>
| # | Severity | Title | Source → sink | Missing control | Evidence | Fix |
|---|----------|-------|---------------|-----------------|----------|-----|
| 1 | critical | SQL injection | `cfg['name']` from request body → `db.execute(f"...")` | parameterization | app.py:5 | `db.execute("... WHERE name = ?", (name,))` |
</example>
