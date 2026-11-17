---
claim: Self-attention can replace recurrence for sequence transduction
topics: [llm, deep-learning, ml, computing]
confidence: medium
level: intermediate
origin: literature
updated: 2026-11-07
---

## Claim

Self-attention can replace recurrence for sequence transduction.

## Evidence

See [Attention Is All You Need](../../literature/computing/2017-vaswani-attention.md) for the original results.

## Applies when

The task maps an input sequence to an output sequence and training can be parallelized.

## Does not apply when

Memory is too limited for attention that grows quadratically with sequence length.
