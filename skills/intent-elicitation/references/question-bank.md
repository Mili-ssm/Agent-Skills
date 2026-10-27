# Question bank

Ask only what evidence leaves open. Phrase each question with concrete options from the hypothesis.

| Area | Questions |
|---|---|
| Purpose | What problem does this solve, for whom? What happens without it? What is measurable success? |
| Users | Roles, skill, devices, accessibility needs? How many? Internal or public? |
| Jobs-to-be-done | When `<situation>`, users want to `<motivation>`, so they can `<outcome>`. Core vs. nice-to-have jobs? |
| Scope | Explicit non-goals? MVP boundary? |
| Priority | MoSCoW per feature; Kano class (basic / performance / delighter) |
| Quality attributes | Rank performance, reliability, security, usability, maintainability, cost. Targets (p95, uptime, RPO/RTO)? |
| Technical constraints | Languages, frameworks, hosting, browsers, minimal JS, offline? |
| Organizational constraints | Team size and skills, deadlines, budget, approvals, ownership after delivery |
| Legal constraints | Personal data (GDPR), retention, licensing, auditability, regulated domain |
| Environment | Dev workflow, CI/CD, environments, release cadence, monitoring |
| Data | Sources of truth, volume, growth, consistency, migrations, backups |
| Integrations | External systems, contracts, owners, failure behavior |
| Failure | What must never happen? Acceptable degradation? Rollback expectations? |
| Security | Threat actors, auth model, sensitive assets, trust boundaries |
| Lifecycle | Prototype or long-lived? Who maintains it? |
| History | Why was X done this way? Is the reason still valid? Was Y tried? |
| Change | Why now? Cost of not doing it? Who is affected? Backward compatibility required? |

## Techniques

| Technique | Use |
|---|---|
| 5 whys / laddering | Reach the goal behind a requested solution |
| Impact mapping (Adzic): goal → actors → impacts → deliverables | Tie features to a measurable goal; cut deliverables with no impact |
| User story mapping (Patton) | Order the journey; slice releases across it |
| Example mapping / specification by example | Rules + concrete examples + open questions; examples become tests |
| Three amigos (business, dev, test) | Surface misunderstandings before building |
| Event Storming | Discover domain events, commands, aggregates and bounded contexts |
| Assumption mapping (importance × evidence) | Validate risky assumptions first |
| Cynefin (clear, complicated, complex, chaotic) | Clear/complicated → analyze and specify; complex → probe with small experiments |
| Negative questions | "What would make this a failure even if it works?" |

## Phrasing

- Closed with options when the space is known; open only for real discovery.
- One concept per question.
- Include your recommended default and its reason.
