---
type: llm
---
PASS if the final answer quotes these three lines of the "Retry policy" section verbatim (Markdown formatting aside): "Payments retry at most 4 times with exponential backoff: 2 s, 4 s, 8 s, 16 s.", "A retry never reuses an idempotency key older than 24 h." and "After the last retry the job moves to the dead-letter queue `payments-dlq`." FAIL if any line is missing, paraphrased or changed, or if text from a "Retry settings for service N" section is presented as the Retry policy.
