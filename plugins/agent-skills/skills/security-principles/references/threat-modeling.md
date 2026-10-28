# Threat modeling

## Four questions (Shostack)

1. What are we working on? (model: DFD)
2. What can go wrong? (STRIDE)
3. What are we going to do about it? (mitigate, eliminate, transfer, accept)
4. Did we do a good job? (validate)

## Data flow diagram

External entity · process · data store · data flow · **trust boundary** (privilege or control changes: browser↔server, server↔DB, service↔third party, user↔admin). Threats concentrate where flows cross boundaries.

## STRIDE

| Threat | Violates | Examples | Typical controls |
|---|---|---|---|
| Spoofing | Authenticity | Stolen session, forged JWT, CSRF | Strong auth, MFA, SameSite cookies, CSRF tokens |
| Tampering | Integrity | Modified hidden fields, params, files | Server-side validation, signatures/MAC, DB constraints |
| Repudiation | Non-repudiation | User denies an action; no audit trail | Audit logs (who/what/when), tamper-evident storage |
| Information disclosure | Confidentiality | IDOR, verbose errors, secrets in logs | Per-object authz, generic errors, encryption, log scrubbing |
| Denial of service | Availability | Unbounded uploads, ReDoS, expensive queries | Limits, timeouts, pagination, rate limiting |
| Elevation of privilege | Authorization | Mass assignment, missing role check, injection → RCE | Allow-listed fields, central authz, sandboxing |

## Attack trees and abuse cases

Root = attacker goal; children = ways to reach it (AND/OR). Mitigate the cheapest attacker paths first. Per feature write abuse cases ("As an attacker I want … so that …") and turn them into negative tests.

## Privacy (LINDDUN, when personal data is involved)

Linking · Identifying · Non-repudiation · Detecting · Data disclosure · Unawareness · Non-compliance. Minimize collection, retention and access; record the lawful basis (GDPR).

## Output

```markdown
| ID | Boundary / element | STRIDE | Threat | Likelihood | Impact | Existing control | Gap → mitigation |
```
