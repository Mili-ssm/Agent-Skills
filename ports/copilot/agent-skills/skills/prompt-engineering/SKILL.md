---
name: prompt-engineering
description: Rules, labeled measured or prescribed, and workflows for writing text that LLMs read or act on - prompts and system prompts, skills, subagent and command definitions, worker briefs, tool and MCP descriptions, CLAUDE.md/AGENTS.md - and for shaping projects run mostly by coding agents, including cheap navigation of long files by outline and line range. Use when writing, improving or reviewing such text, when asking how to phrase an instruction so Claude follows it, why an agent ignores a rule, overtriggers, over-engineers or stops early, which model or effort a worker needs, or how to make a repository easier for agents; load it before answering so advice cites current Anthropic guidance and measured results instead of memory.
---

# Prompt engineering

**Core rule:** a model acts only on what is in its context. Write the smallest set of high-signal tokens that makes the wanted behavior likely, give the reason for each non-obvious rule, and prove the change with an eval, not by rereading it.

## References

| Open when | Reference |
|---|---|
| Wording any prompt: instructions, emphasis, examples, format, long context, thinking and effort | [prompt-rules.md](references/prompt-rules.md) |
| Writing a skill, subagent, command or worker brief | [skills-and-agents.md](references/skills-and-agents.md) |
| Designing tools, MCP tool descriptions or structured outputs | [tools.md](references/tools.md) |
| Choosing or writing for a model (Haiku, Sonnet, Opus), or a model change | [models.md](references/models.md) |
| Writing or auditing CLAUDE.md or AGENTS.md | [context-files.md](references/context-files.md) |
| Structuring a repo, specs, plans and docs for agent-run projects; navigating long files | [llm-native-projects.md](references/llm-native-projects.md) |
| Measuring a prompt change (`claude plugin eval`) | [evaluation.md](references/evaluation.md) |

Density cuts follow the `docs-principles` checklist; on LLM-facing text, keep every line that changes behavior (context-files.md audit questions). The authoring *process* for skills (TDD for skills) belongs to Superpowers `writing-skills`.

## Writing or improving

Copy and tick:

```
- [ ] 1 Frame: the reader (model, effort, tools, what it already sees), the wanted behavior, how it will be checked
- [ ] 2 Baseline: run the task without the new text, or read the failing trace; name each failure
- [ ] 3 Draft the minimum that fixes the named failures, with the reference for this artifact
- [ ] 4 Test with every target model; read traces, not only scores
- [ ] 5 Revise: add only for an observed failure; cut lines that changed nothing
- [ ] 6 Record what was measured (ADR, eval, commit), so the next edit does not undo it
```

When no eval is feasible, say the change is unmeasured and name the cheapest check that would measure it.

## Diagnosing a misbehaving prompt

| Symptom | Usual cause | Fix |
|---|---|---|
| Ignores a rule | Rule buried, without a reason, or contradicted elsewhere | One place, near the top, with its reason; remove the conflict |
| Overtriggers or overuses a tool | Emphasis (CAPS, "CRITICAL", "if in doubt, use X") | Calm wording and a specific trigger |
| Skill does not fire | Description lacks the user's terms or a reason to load | "Use when …" with likely terms, plus why loading beats memory |
| Over-engineers or edits when asked to suggest | No scope guard; the verb says "change" | Scope guard; the verb that names the wanted action |
| Stops early, skips steps | Low effort on a small model; no completion criteria | "Done means …"; raise effort for multi-step work |
| Wrong or drifting format | Format only described | 3–5 diverse examples in `<example>` tags |
| Worker improvises or contradicts a decision | Brief lacks decisions, scope or a stop rule | The six-part brief |
| Context fills up | Raw files, logs or command output in the main conversation | Outline and range reads; offload to cheap workers |

## Answering an advice request

1. Diagnose from the text or trace, quoting the lines that cause the behavior.
2. Name the rule and its source, labeled **measured** or **prescribed**.
3. Give a before/after rewrite of only the lines that change.
4. Say how to verify it (an eval case, a trace to read, a model to test).

## Review output (default; a format in the caller's task or agent definition replaces it)

```markdown
| File:line | Rule (reference · measured/prescribed) | Issue | Rewrite | Check |
Unmeasured changes: <list> → cheapest check
```

## Reading long files cheaply

```bash
python3 ${COPILOT_HOME:-$HOME/.copilot}/installed-plugins/mili-ssm/agent-skills/skills/prompt-engineering/scripts/outline.py PATH [PATH...] [--depth N] [--max-entries N]
```

It prints each file's headings and declarations with line ranges, computed by a script, not a model; then read only the range you need (Read with offset and limit). Generate it when needed and never store it, because line numbers go stale with every edit. For logs and other material without structure, dispatch `summarizer` instead.
