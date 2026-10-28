# Security review checklist

## OWASP Top 10 themes

| Theme | Check |
|---|---|
| Broken access control | Authz on every route and object (IDOR); deny by default; no decisions from client data |
| Cryptographic failures | TLS everywhere; argon2/bcrypt/scrypt for passwords; secure randomness (`secrets`, `OsRng`) |
| Injection | Parameterized SQL; no shell with user input; template autoescape on; no `eval` of input |
| Insecure design | Threat model; rate limits on auth and expensive operations; business-logic abuse cases |
| Misconfiguration | Debug off in prod; CSP, HSTS, `X-Content-Type-Options`, `frame-ancestors`; minimal CORS; no default creds |
| Vulnerable components / supply chain | Audits clean; lockfiles committed; CI actions pinned by SHA; new deps checked for typosquats; SBOM; SLSA provenance for releases |
| Authentication failures | Session rotation on login; Secure/HttpOnly/SameSite cookies; brute-force protection; non-enumerable reset flows |
| Integrity failures | Signed artifacts; no unsafe deserialization; scoped CI secrets |
| Logging and monitoring | Auth events and authz failures logged; secrets/PII scrubbed; alerts exist |
| SSRF | Allow-list outbound hosts for user URLs; block internal ranges and metadata endpoints; re-check after redirects/DNS |
| Exceptional conditions | Fail closed; no stack traces to users; cleanup on error paths |

ASVS (OWASP Application Security Verification Standard): Level 1 baseline for every app; Level 2 for sensitive data. Areas: architecture, authentication, sessions, access control, validation/encoding, cryptography, errors/logging, data protection, communications, business logic, files, APIs, configuration.

## Python sinks

| Sink | Safe alternative |
|---|---|
| `pickle`, `marshal`, `shelve` on untrusted data | JSON / Pydantic models |
| `yaml.load` | `yaml.safe_load` |
| `subprocess(..., shell=True)`, `os.system` | List args, `shell=False` |
| f-strings in SQL | Bound parameters (SQLAlchemy `text()` + params) |
| `eval`, `exec` | Explicit parsing |
| Jinja2 `\|safe`, `Markup()`, `autoescape=False` | Keep autoescape; sanitize allow-listed HTML with `nh3` |
| `tempfile.mktemp` | `NamedTemporaryFile`, `mkstemp` |
| HTTP without timeout / `verify=False` | Timeouts; verification on |
| Path from user input | `Path.resolve()` then `is_relative_to(base)` |

## Rust risks

| Risk | Check |
|---|---|
| `unsafe` | `// SAFETY:` justification per block; minimal scope; `cargo miri` on tests |
| FFI | Null/length checks, ownership across the boundary, no unwinding across FFI |
| Panics as DoS | `unwrap`/`expect`/indexing on untrusted input; overflow in release |
| Deserialization | `serde` size/depth limits; `deny_unknown_fields` where strict |
| Supply chain | `cargo audit`, `cargo deny` (advisories, licenses, bans, sources), `cargo vet` |
| Secrets in memory | `zeroize`, `secrecy` |

## Web, server-rendered and htmx

- CSRF token on every state-changing request (htmx: `hx-headers` or meta-tag pattern); SameSite is defense in depth.
- `HX-Request`/`HX-Target` are client-controlled: never authorization inputs.
- Fragment endpoints need the same authz as full pages.
- CSP without `unsafe-inline`/`unsafe-eval`; `hx-on` and inline handlers need CSP review (`htmx.config.allowEval`).
- User HTML: escape by default; sanitize allow-listed tags only.
- Uploads: size limit, type by content, stored outside web root, random names.
- Redirects (`HX-Redirect`, `Location`): allow-listed targets.

## Secrets

Scan history (`gitleaks`, `trufflehog`); keep secrets in env or a secret manager; rotate on exposure; least-privilege, expiring tokens.
