# Question bank

Pick only questions the evidence leaves open. Rephrase with concrete options from the hypothesis.

| Area | Questions |
|---|---|
| Purpose | What problem does this solve, for whom? What happens if it doesn't exist? What is success, measurably? |
| Users | Who uses it (roles, skill, devices, accessibility needs)? How many? Internal or public? |
| Jobs-to-be-done | When [situation], users want to [motivation], so they can [outcome]. Which jobs are core vs. nice-to-have? |
| Scope | What is explicitly out of scope (non-goals)? What is the MVP boundary? |
| Priority | MoSCoW per feature: must / should / could / won't (this time) |
| Quality attributes | Rank: performance, reliability, security, usability, maintainability, cost. Concrete targets (p95 latency, uptime, RPO/RTO)? |
| Constraints — technical | Required languages, frameworks, platforms, hosting, browsers, minimal JS, offline? |
| Constraints — organizational | Team size and skills, deadlines, budget, approval processes, ownership after delivery |
| Constraints — legal | Personal data (GDPR), retention, licensing, auditability, regulated domain |
| Environment / framework | Dev workflow, CI/CD, environments, deployment cadence, monitoring |
| Data | Sources of truth, volumes, growth, consistency needs, migrations, backups |
| Integrations | External systems, contracts, who owns them, failure behavior |
| Failure | What must never happen? Acceptable degradation? Rollback expectations? |
| Security | Threat actors, auth model, sensitive assets, trust boundaries |
| Lifecycle | Expected lifetime, prototype vs. long-lived, who maintains it |
| History | Why was X done this way? Is the reason still valid? Was alternative Y tried? |
| Change mode | Why now? What breaks if we don't? Who is affected? Backward compatibility required? |

## Techniques

| Technique | Use |
|---|---|
| 5 whys | Reach the real goal behind a requested solution |
| Example mapping (rules, examples, questions) | Turn a feature into testable rules |
| Assumption mapping (importance × evidence) | Find risky assumptions to validate first |
| Negative questions | "What would make this a failure even if it works?" |
| Laddering | Move between concrete behavior and abstract goal |

## Phrasing rules

- Closed with options when the space is known; open only for genuine discovery.
- One concept per question; no compound questions.
- Include the default you would pick and why.
