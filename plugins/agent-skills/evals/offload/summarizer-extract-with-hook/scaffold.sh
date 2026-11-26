#!/bin/bash
# ~2400-line runbook; the section asked for sits in the middle among look-alike sections.
set -e
python3 - <<'PY'
out = ["# Runbook", ""]
for n in range(60):
    out += [f"## Service {n}", "", f"### Retry settings for service {n}", ""]
    out += [f"Service {n} retries {n % 5 + 1} times with a fixed delay of {n % 3 + 1} s." for _ in range(1)]
    out += [f"Line {k} of the operational notes for service {n}." for k in range(30)]
    out.append("")
    if n == 31:
        out += ["### Retry policy", "",
                "Payments retry at most 4 times with exponential backoff: 2 s, 4 s, 8 s, 16 s.",
                "A retry never reuses an idempotency key older than 24 h.",
                "After the last retry the job moves to the dead-letter queue `payments-dlq`.", ""]
open("runbook.md", "w").write("\n".join(out) + "\n")
PY
