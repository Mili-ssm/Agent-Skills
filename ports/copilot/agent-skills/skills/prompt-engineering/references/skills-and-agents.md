# Skills, subagents, commands and briefs

Sources (current as of 2026-10): Anthropic *Skill authoring best practices* (platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices); Claude Code subagent, skill and plugin docs (code.claude.com/docs/en/sub-agents, /skills, /plugins-reference); ADRs 0010, 0012 and 0013 of this repo for the measured results.

## Contents
- Skills
- Subagents
- Commands
- Worker briefs

## Skills

| Item | Rule |
|---|---|
| `name` | ≤ 64 chars, lowercase/digits/hyphens, no "anthropic"/"claude"; one naming pattern per collection |
| `description` | Third person; **what it does + "Use when …" triggers** with the user's likely key terms; ≤ 1024 chars; loaded every turn |
| Reason to load | End knowledge-skill descriptions with why loading beats answering from memory ("load it before answering so findings cite …"); measured on this plugin: positive trigger rate 58% → 87% with no false triggers |
| Body | Overview + workflow; < 500 lines (Anthropic), ≤ 150 here; smaller is better |
| References | One level deep from `SKILL.md`; descriptive filenames; `## Contents` when > 100 lines (partial reads see scope) |
| Workflows | Numbered steps; for long ones a checklist to copy and tick; feedback loop *validate → fix → repeat* |
| Scripts | Say whether to **run** or **read**; handle errors in the script; justify constants; path via `${CLAUDE_SKILL_DIR}` (substituted in the body) |
| Paths and tools | Forward slashes; MCP tools as `ServerName:tool_name`; never assume a package is installed |
| Time-sensitive facts | Date them, or isolate in an "old patterns" section |

## Subagents

| Item | Rule |
|---|---|
| `description` | Delegation trigger: specific, action-oriented "Use to/when …". "Use proactively" raises auto-delegation; here only the cheap workers carry it (ADR 0010). All descriptions together stay small (Claude Code docs warn above ~15,000 tokens) |
| Tools | Minimum set; enforce read-only with `disallowedTools: Edit, Write, NotebookEdit`, not prompt text; tell Bash users which commands keep files unchanged |
| Context | `omitClaudeMd: true` for workers: they see only their prompt and the brief, so restate any rule they need |
| Output | A condensed report with a format and a length bound; raw tool output stays inside |
| Delegation scope | Parallel, isolated or independent work; direct tools for simple lookups (models over-delegate) |
| Offload triggers | Measured here (ADR 0010, 0012): descriptions alone moved delegation little; a short trigger table in the main conversation's CLAUDE.md made it reliable; Opus delegated code only after its row was rewritten with a size threshold, a review step and "even when it looks easy" |
| Interaction | Subagents cannot ask the user mid-task: interactive work runs in skills; agents return the gap instead |
| Preload | `skills:` injects full skill content at start; keep preloads few |
| Paths | `${CLAUDE_PLUGIN_ROOT}` is substituted in a plugin agent's body; Glob runs in the project and did not reach plugin files (observed here) |

## Commands

- User-only commands (`disable-model-invocation: true`) force a workflow or an agent without relying on auto-triggering.
- Pass `$ARGUMENTS` into a self-contained brief; say which defaults were assumed when no argument is given.

## Worker briefs

A worker sees none of the conversation. Measured here (ADR 0013): with the six parts named in the main conversation's policy, the stop rule went from 0/3 to 3/3 briefs and delegation from 2/3 to 3/3.

1. **Goal** and acceptance criteria the worker can check itself.
2. **Scope**: the paths it owns, and what it must not touch.
3. **Decisions already taken, each with its reason**, so it neither reopens nor contradicts them.
4. **Checks**: the commands that prove the result.
5. **Stop rule**: when the brief does not fit what it finds, it stops and reports the gap.
6. **Report**: format and max length.

State the what, the limits and the check, not each step. A task whose design is still open is not delegated: settle it first (Cognition, *Don't build multi-agents*: actions carry implicit decisions, and workers that cannot see them make conflicting ones).
