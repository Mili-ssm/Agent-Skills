# Prompt, skill and subagent authoring (Claude)

Sources (current as of 2026-10): Anthropic *Skill authoring best practices*; *Prompting best practices*; *Effective context engineering for AI agents*; Claude Code subagent and plugin-eval docs.

## Contents
- Core rules
- Skills
- Subagents
- Context engineering
- Evaluation

## Core rules

| Rule | Why |
|---|---|
| Add only what the model lacks; assume it already knows common concepts | Every loaded token competes for attention (context rot) |
| Right altitude: priorities and heuristics, not brittle if/else trees nor vague advice | Heuristics generalize; hardcoded branches break on unseen cases |
| Give the reason for non-obvious rules ("X, because Y") | The model generalizes from reasons to cases the rule never named |
| State what to do, not only what to avoid | Positive targets steer better than prohibitions |
| Calm wording; reserve MUST/NEVER for true invariants; no ALL CAPS | Current models are proactive and overtrigger on emphasis |
| One term per concept across all files | Synonyms read as different concepts |
| One default plus an escape hatch, not a menu of options | Menus cause dithering and inconsistent picks |
| Degrees of freedom by fragility: heuristics (open field) → template (preferred pattern) → exact command (narrow bridge) | Over-constraining wastes judgment; under-constraining breaks fragile steps |
| 1–3 canonical, diverse examples in `<example>` tags | Examples steer format and level of detail more reliably than descriptions |
| XML tags when instructions, context, examples and inputs mix | Unambiguous parsing |
| Match prompt style to wanted output (Markdown in → Markdown out) | Style transfers |
| One-sentence role | Focuses tone and judgment cheaply |
| Action verbs decide action: "change X" edits, "suggest changes" only suggests | The model follows instructions literally |
| Ground claims: read before asserting; cite evidence | Prevents speculation about unopened code |
| Scope guard: do what was asked, minimum complexity | Models tend to over-engineer |

## Skills

| Item | Rule |
|---|---|
| `name` | ≤ 64 chars, lowercase/digits/hyphens, no "anthropic"/"claude"; gerund or noun phrase, one pattern per collection |
| `description` | Third person; **what it does + "Use when …" triggers** with the user's likely key terms; ≤ 1024 chars; loaded every turn |
| Reason to load | End knowledge-skill descriptions with why loading beats answering from memory ("load it before answering so findings cite …"); measured on this plugin: positive trigger rate 58% → 87% with no false triggers |
| Body | Overview + workflow; < 500 lines (Anthropic); smaller is better |
| References | One level deep from `SKILL.md`; descriptive filenames; `## Contents` when > 100 lines (partial reads see scope) |
| Workflows | Numbered steps; for long ones a checklist to copy and tick; feedback loop *validate → fix → repeat* |
| Scripts | Say whether to **run** or **read**; handle errors in the script; justify constants |
| Time-sensitive facts | Avoid, or isolate in an "old patterns" section |

## Subagents

| Item | Rule |
|---|---|
| `description` | Delegation trigger: specific, action-oriented "Use to/when …". "Use proactively" raises auto-delegation; add it only where unprompted use is wanted |
| Tools | Minimum set; enforce read-only reviewers with `disallowedTools: Edit, Write` instead of prompt text |
| Output | A condensed, distilled report; raw tool output stays inside |
| Delegation scope | Parallel, isolated or independent work; direct tools for simple lookups (models over-delegate) |
| Offload workers | Cheap workers may say "Use proactively … instead of doing it yourself, because …"; measured: descriptions alone moved little, a short offload table in CLAUDE.md made delegation reliable |
| Self-contained briefs | Workers with `omitClaudeMd: true` see only the brief: include goal, paths, commands, acceptance, max length |
| Interaction | Subagents cannot ask the user mid-task → interactive work runs in skills |
| Preload | `skills:` injects full skill content at start; keep preloads few |

## Context engineering

- Smallest high-signal token set that makes the outcome likely.
- Just-in-time retrieval: keep paths/queries, load content when needed (grep, read sections).
- Long tasks: structured notes outside the context (progress file, findings register); compaction keeps decisions, drops stale tool output.
- Long inputs first, question last (up to ~30% better on multi-document tasks).

## Evaluation

1. Run representative tasks without the skill; note failures.
2. Write eval cases (`claude plugin eval`, cases in `evals/`), measure a baseline.
3. Write the minimum instructions that pass; re-run; compare.
4. Observe navigation: unread files are unnecessary or badly signposted; files read every time belong in `SKILL.md`.
5. Test with every model the skill targets (Haiku needs more guidance; Opus needs less explanation).
