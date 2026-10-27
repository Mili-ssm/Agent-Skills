# Security review checklist

## OWASP Top 10 themes (web) → what to check

| Theme | Check |
|---|---|
| Broken access control | Authz on every route and object (IDOR); deny by default; no authz decisions from client data |
| Cryptographic failures | TLS everywhere; passwords with argon2/bcrypt/scrypt; no secrets in code; strong random (`secrets`, `rand::rngs::OsRng`) |
| Injection | Parameterized SQL; no shell with user input; template autoescape on; no `eval`/dynamic imports from input |
| Insecure design | Threat model exists; rate limits on auth and expensive ops; business-logic abuse cases |
| Security misconfiguration | Debug off in prod; security headers (CSP, HSTS, X-Content-Type-Options, frame-ancestors); CORS minimal; default creds removed |
| Vulnerable / outdated components, supply chain | Audits clean; lockfiles committed; pinned CI actions; minimal deps; typosquat check on new deps |
| Identification and authentication failures | Session rotation on login; secure/HttpOnly/SameSite cookies; brute-force protection; reset flows not enumerable |
| Software and data integrity failures | Signed artifacts; no unsafe deserialization; CI secrets scoped |
| Logging and monitoring failures | Auth events and authz failures logged; no secrets/PII in logs; alerts exist |
| SSRF | Allow-list outbound hosts for user-supplied URLs; block internal ranges and metadata endpoints |
| Exceptional conditions | Errors fail closed; no stack traces to users; resource cleanup on error paths |

## ASVS areas (OWASP Application Security Verification Standard)

Architecture · Authentication · Session management · Access control · Validation, sanitization, encoding · Stored cryptography · Error handling and logging · Data protection · Communications · Malicious code · Business logic · Files and resources · API and web services · Configuration. Level 1 = baseline for all apps; Level 2 = apps with sensitive data.

## Python

| Sink | Safe alternative |
|---|---|
| `pickle`, `marshal`, `shelve` on untrusted data | JSON / Pydantic models |
| `yaml.load` | `yaml.safe_load` |
| `subprocess(..., shell=True)`, `os.system` | List args, `shell=False` |
| f-strings in SQL | Bound parameters (SQLAlchemy `text()` with params) |
| `eval`, `exec` | Explicit parsing |
| Jinja2 `\|safe`, `Markup()`, `autoescape=False` | Keep autoescape; sanitize with `nh3` if HTML input is required |
| `tempfile.mktemp` | `NamedTemporaryFile`, `mkstemp` |
| `requests` without timeout / `verify=False` | Timeouts; verification on |
| Path from user input | `Path.resolve()` + check `is_relative_to(base)` |

## Rust

| Risk | Check |
|---|---|
| `unsafe` | Each block has `// SAFETY:` justification; invariants hold; minimal scope; `cargo miri` on tests |
| FFI | Null/length checks, ownership across boundary, panics not unwinding across FFI |
| Panics as DoS | `unwrap`/`expect`/indexing on untrusted input; arithmetic overflow in release |
| Deserialization | `serde` size/depth limits; `deny_unknown_fields` where strictness matters |
| Supply chain | `cargo audit`, `cargo deny` (advisories, licenses, bans, sources), `cargo vet` |
| Secrets in memory | `zeroize`, `secrecy` crates |

## Web, server-rendered and htmx

- CSRF: token on every state-changing request (htmx: `hx-headers` or meta-tag pattern); SameSite cookies are defense in depth, not the only control.
- `HX-Request`, `HX-Target` and similar headers are client-controlled: never use them for authorization.
- Fragment endpoints need the same authz as full pages.
- CSP: avoid `unsafe-inline`/`unsafe-eval`; htmx `hx-on` and inline handlers need CSP consideration (`htmx.config.allowEval`).
- Returned HTML from user content: escape by default; sanitize allow-listed HTML only.
- File uploads: size limits, type by content (not extension), store outside web root, random names.
- Open redirects: allow-list redirect targets (`HX-Redirect`, `Location`).

## Secrets

Scan history (`gitleaks`, `trufflehog`); env/secret manager, never committed; rotate on exposure; least-privilege tokens with expiry.
