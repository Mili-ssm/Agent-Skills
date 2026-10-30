# Projects run mostly by LLM agents

How to shape a repository so coding agents work in it reliably and cheaply. Evidence is thin: most items are prescribed by tool makers, not measured; the label says which (as of 2026-10).

## Contents
- Navigation and reading
- Feedback loops
- Specs, plans and decisions
- Context files and docs
- Evidence summary

## Navigation and reading

| Practice | Evidence |
|---|---|
| Search just in time (grep, glob, outline) instead of a pre-built index or embeddings | Prescribed by Anthropic: grep and glob "bypass the issues of stale indexing"; Claude Code's makers report agentic search beat RAG internally (not published) |
| Outline first, then read only the range: the skill's `outline.py` (command in `SKILL.md`) prints headings and declarations with line ranges | Prescribed: SWE-agent shows ~100 lines per view; Aider ships a symbol map. No measurement isolates the outline |
| Never store line-number indexes in the repo | Line numbers shift with every edit above them; generate the outline when needed |
| Delegate long reading to a cheap worker that returns the answer, the outline or a verbatim extract (`summarizer`) | Measured here (ADR 0010): delegation reliable once the trigger table is in CLAUDE.md |
| Typed code and a code-intelligence (LSP) plugin let the agent jump to definitions | Prescribed by Claude Code docs; types: one 2022 study measured a small loss when TypeScript types were removed |
| Small, single-purpose files with descriptive names | Prescribed: "file sizes suggest complexity"; an agent reads a whole small file cheaply and finds it by name |
| Relevant material at the start or end of a long input, not the middle | Measured ("Lost in the middle", 2023): accuracy drops for mid-context documents; weaker on newer models |

## Feedback loops

- Give every task a check the agent can run itself (tests, typecheck, lint, a validator script): prescribed by Claude Code docs as the single most useful practice, because the agent closes its own loop.
- Checks print failures compactly; a cheap worker (`check-runner`) runs long ones in the background and returns failures, not logs.
- Encode conventions in validators, not prose, when they can be checked (this repo: `scripts/validate.py`).

## Specs, plans and decisions

| Artifact | Rule |
|---|---|
| Spec / requirements | Numbered, testable requirements (R1, N1…) that agents cite; EARS-style "When X, the system shall Y" where behavior matters (Kiro) |
| Plan | Tasks with paths, acceptance and checks, written for an executor with zero context (Superpowers `writing-plans`); decisions with their reasons |
| Decisions | ADRs with alternatives and "revisit if", so agents do not reopen settled choices |
| Progress | A progress file or checklist outside the context, so a fresh window resumes |

Spec Kit, Kiro, AGENTS.md and llms.txt prescribe these shapes; none publishes a measured effect.

## Context files and docs

- CLAUDE.md / AGENTS.md: minimal, only what the agent cannot discover (context-files.md); Claude Code advises under ~200 lines.
- Docs answer one reader need per section (Diátaxis) and state the why; facts live in one place and are linked.
- One term per concept across code, docs and prompts: agents treat synonyms as different things.

## Evidence summary

Strongest: a runnable check per task, short context files (one measured study), just-in-time search. Weak or absent: outlines and repo maps (no isolated measurement), spec formats (none measured). Measure in your own project before adding structure (evaluation.md).
