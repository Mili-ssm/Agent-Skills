# 0014 Prompt engineering skill and cheap navigation

Status: accepted · Date: 2026-10-30

## Context

The owner runs projects developed almost entirely by LLM agents and wants expert help to write, and advise on, text that LLMs act on. That guidance lived in two references inside `docs-principles` (`prompt-authoring.md`, `agent-context-files.md`), filed under documentation, with no tool, per-model or eval-practice rules, and no reviewer agent.

The owner also asked for a Haiku worker that indexes files (titles and line numbers, so agents read only what they need) and runs long commands without filling the main context.

Research (2026-10-30):

| Source | Finding |
|---|---|
| Anthropic prompting best practices, per-model pages | 3–5 examples; adaptive thinking and `effort` replace `budget_tokens` (400 on 4.7+); prefill 400 on 4.6+; Haiku 5.5 `low` effort stops early (low → medium roughly halved early stops, more than doubled output tokens) |
| Anthropic, *Writing effective tools for agents* | Tool design and descriptions; concise responses 72 vs 206 tokens |
| Anthropic, *Effective context engineering* | Just-in-time grep/glob "bypass the issues of stale indexing" |
| SWE-agent, Aider, Agentless | Windowed views and symbol maps are prescribed; no study isolates the effect of an outline |
| Spec Kit, Kiro, AGENTS.md, llms.txt | Prescribed shapes; none publishes a measured effect |
| Claude Code docs | `${CLAUDE_PLUGIN_ROOT}` is substituted in agent bodies, `${CLAUDE_SKILL_DIR}` in skill bodies; background Bash writes output to a file; LSP symbols need a code-intelligence plugin |

## Decision

- New knowledge skill `prompt-engineering`: writing workflow, a symptom → cause → fix table, advice and review formats; references for prompt rules, skills/agents/briefs, tools, models, context files, agent-run projects and evaluation. The two `docs-principles` references move into it (single source); `docs-principles` keeps repository docs.
- New read-only reviewer `prompt-engineer` (Sonnet, preloads the skill) and the user-only command `/agent-skills:prompt-review`. Writing with the owner runs inline through the skill, because subagents cannot ask (ADR 0003).
- Navigation: `scripts/outline.py` in the skill prints headings and declarations with line ranges for zero model tokens, generated on demand and never stored, because stored line numbers go stale with every edit.
- No new Haiku agent. `summarizer` gains `outline` and `extract` (verbatim) modes; `check-runner` runs any long read-only command and returns failures, the result or the last lines verbatim; the offload policy says long runs go to the background.

## Alternatives

| Option | Rejected because |
|---|---|
| A new Haiku `navigator` worker | Overlaps `summarizer` and `check-runner`; one more description loaded every turn |
| A stored index file (titles, line numbers) | Goes stale with each edit; Anthropic recommends just-in-time search for the same reason |
| An LLM step to build the outline | A script computes it exactly for zero model tokens |
| Extending `docs-principles` only | Hides prompt work under documentation; no reviewer agent |
| tree-sitter or ctags for exact ranges | Not installed everywhere; regex ranges are close enough for a map, and Python uses `ast` |

## Consequences

- One more skill description and one more agent description in every session.
- Regex ranges (Rust, TS/JS, Go) are approximate; the script says so.
- Owners copy the updated offload table into their `CLAUDE.md`.

## Revisit if

The `prompt-engineering` trigger case stays below 2/3, a near-miss starts firing it, `summarizer` returns paraphrase in `extract` mode, or a measured study shows stored indexes beat on-demand outlines.

## Measurement 2026-10-30

Pending.
