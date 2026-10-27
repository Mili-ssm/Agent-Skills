# Threat modeling

## Four questions (Shostack)

1. What are we working on? (model: DFD)
2. What can go wrong? (STRIDE)
3. What are we going to do about it? (mitigate, eliminate, transfer, accept)
4. Did we do a good job? (validate)

## Data flow diagram elements

External entity · process · data store · data flow · **trust boundary** (where privilege or control changes: browser↔server, server↔DB, service↔third party, user↔admin). Threats concentrate at boundary crossings.

## STRIDE

| Threat | Violates | Examples | Typical controls |
|---|---|---|---|
| Spoofing | Authenticity | Stolen session, forged JWT, CSRF | Strong auth, MFA, SameSite cookies, CSRF tokens |
| Tampering | Integrity | Modified hidden fields, request params, files | Server-side validation, signatures, MAC, DB constraints |
| Repudiation | Non-repudiation | User denies action, no audit trail | Audit logs (who/what/when), tamper-evident logging |
| Information disclosure | Confidentiality | IDOR, verbose errors, logs with secrets, directory listing | Authz per object, generic errors, encryption, log scrubbing |
| Denial of service | Availability | Unbounded uploads, regex DoS, expensive queries | Limits, timeouts, pagination, rate limiting |
| Elevation of privilege | Authorization | Mass assignment, missing role check, injection → RCE | Allow-list fields, central authz, sandboxing |

## Attack trees

Root = attacker goal; children = ways to achieve it (AND/OR). Prune by cost/skill; mitigate cheapest attacker paths first.

## Abuse cases

For each feature: "As an attacker, I want to … so that …". Turn into negative tests.

## Output format

```markdown
| ID | Boundary / element | STRIDE | Threat | Likelihood | Impact | Existing control | Gap → mitigation |
```

## Privacy (LINDDUN, when personal data is involved)

Linking · Identifying · Non-repudiation · Detecting · Data disclosure · Unawareness · Non-compliance. Minimize collection, retention and access; document lawful basis (GDPR).
