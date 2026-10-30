# Prompt rules (Claude)

Sources (current as of 2026-10): Anthropic *Prompting best practices* (platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices); *Effective context engineering for AI agents* (anthropic.com/engineering/effective-context-engineering-for-ai-agents). "Measured" marks a result someone reported with numbers; everything else is prescribed guidance.

## Contents
- Instructions
- Examples and format
- Context engineering
- Thinking, effort and API constraints
- Rewrite patterns

## Instructions

| Rule | Why |
|---|---|
| Add only what the model lacks; assume it knows common concepts | Every loaded token competes for attention (context rot) |
| Start minimal and add a line only for an observed failure; minimal is not the same as short | Lines added "just in case" dilute the ones that matter; a needed detail is not bloat |
| Right altitude: priorities and heuristics, neither brittle if/else trees nor vague advice | Heuristics generalize; hardcoded branches break on unseen cases |
| Give the reason for each non-obvious rule ("X, because Y") | The model generalizes from the reason to cases the rule never named |
| State what to do, not only what to avoid | Positive targets steer better than prohibitions |
| Calm wording; MUST/NEVER only for true invariants; no ALL CAPS, no "CRITICAL", no "if in doubt, use X" | Current models follow instructions closely and overtrigger on emphasis |
| One term per concept across all files | Synonyms read as different concepts |
| One default plus an escape hatch, not a menu | Menus cause dithering and inconsistent picks |
| Degrees of freedom by fragility: heuristics (open field) → template (preferred pattern) → exact command (narrow bridge) | Over-constraining wastes judgment; under-constraining breaks fragile steps |
| One-sentence role | Focuses tone and judgment cheaply |
| Action verbs decide action: "change X" edits, "suggest changes" only suggests | The model does what the verb says |
| Ground claims: read before asserting; cite evidence | Prevents confident answers about unopened code |
| Scope guard ("do what was asked; minimum complexity") where the target over-engineers | Opus 4.5+ is proactive; Anthropic gives this fix for overeagerness |
| Completion criteria stated up front (what "done" looks like) | Smaller models stop early without them (see models.md) |

## Examples and format

| Rule | Why |
|---|---|
| 3–5 diverse, canonical examples in `<example>` tags when the output shape matters; 1 when a single shape suffices | Examples steer format and level of detail more reliably than descriptions (Anthropic recommends 3–5) |
| Examples vary on what may vary and agree on what must not | Near-identical examples get copied literally |
| XML tags when instructions, context, examples and inputs mix | Unambiguous parsing; the model can be told "use the `<plan>`" |
| Describe the wanted format positively ("prose paragraphs", "a table with columns …") | "No Markdown" works worse than naming the target |
| Match prompt style to wanted output (Markdown in → Markdown out) | Style transfers |
| Bound the output (≤ N words or rows) and say why | The reader pays for every token; the reason stops padding |

## Context engineering

- Smallest set of high-signal tokens that makes the outcome likely.
- Just-in-time retrieval: keep paths and queries, load content when needed (grep, outline, read the range).
- Long inputs first, question last; measured by Anthropic: up to ~30% better on multi-document tasks.
- Quote first: for long documents, ask the model to extract the relevant quotes, then answer from them.
- Long tasks: structured notes outside the context (progress file, findings register, tests file); a fresh window resumes from those files, not from memory.
- Compaction keeps decisions and open items and drops stale tool output; clearing old tool results is the cheapest compaction.
- Subagents return condensed results; measured by Anthropic: summaries of about 1,000–2,000 tokens from much longer explorations.

## Thinking, effort and API constraints

As of 2026-10; check the models overview before relying on them.

| Fact | Consequence |
|---|---|
| Adaptive thinking with an `effort` level replaces `budget_tokens`, which returns 400 on 4.7+ models | Set `effort`; do not hand-tune thinking budgets |
| "Think thoroughly about …" usually beats a hand-written step list | Prescribe steps only where order is fragile |
| A prefilled final assistant turn returns 400 on 4.6+ models | Use structured outputs or format instructions instead of prefill |
| Structured outputs (`output_config.format`, `strict: true` tools) guarantee shape, not truth | Keep reasoning fields short ("short explanation"), use `strict` only for critical tools |

## Rewrite patterns

<example>
Before: "IMPORTANT: NEVER use ellipses!"
After: "Your reply is read aloud by a text-to-speech engine, so write without ellipses: it cannot pronounce them."
</example>

<example>
Before: "Be thorough and careful. Check everything."
After: "Done means: every claim cites `file:line`, the tests in `tests/api/` pass, and open questions are listed. Stop when all three hold."
</example>
