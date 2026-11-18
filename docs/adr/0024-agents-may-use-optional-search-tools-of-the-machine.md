# 0024 Agents may use optional search tools of the machine: fff and ast-grep

Status: accepted · Date: 2026-11-18

## Context

The owner installed two search tools on their machine and asked (2026-11-18) that the agents use them: the `fff` MCP server (`fff-mcp` 0.11.0; no command-line binary exists) and the `ast-grep` command (0.51.0). Every agent declares a `tools` allowlist, so none could call an MCP tool, and no prompt named `ast-grep`. The plugin is public: a machine that installs it may have neither tool.

Evidence gathered that day:

| Question | Result | Kind |
|---|---|---|
| Does `mcp__fff__*` in `tools` work in a plugin agent, without `ToolSearch`? | Yes: a throwaway plugin agent (Haiku) called `find_files` | observed, one run, current Claude Code |
| Does an agent launch when a listed MCP server is absent? | Yes: `tools: Read, Grep, mcp__nosuchserver__*` launched with Read and Grep | observed, one run |
| Do the three tool names work beside an absent one? | Yes: the three `fff` names plus `mcp__nosuchserver__grep` launched and called `find_files` | observed, one run |
| Older Claude Code versions | Issues report the wildcard unrecognized (anthropics/claude-code #17928, #53865) and a valid MCP entry lost beside an unresolvable one (#75267); all closed, fix unverified | reported |
| Does `fff` tolerate typos? | Its README says a query with no match retries as fuzzy | author claim |
| User experience with agents | One independent report (dmtrKovalenko/fff #325): good for identifiers, native Grep still needed for exclusions and context lines; closed bugs in exclusions and `multi_grep` constraints | reported, one user |

## Decision

1. `skeptical-reviewer`, `summarizer`, `check-runner` and `fact-checker` add the three `fff` tools by name to `tools` (not `mcp__fff__*`, so a tool the server adds later is not granted to a read-only agent) and one rule: use the `fff` tools when they are in the tool list, keep Grep for exclusions, context lines and regex, and confirm with Grep before reporting that something does not exist.
2. `architect`, `security-reviewer`, `implementer` and `fixer` get one rule: `ast-grep run` for a search by code structure when `command -v ast-grep` finds it, never the alias `sg` (on Fedora that is a `shadow-utils` command), and an empty result is confirmed with Grep.
3. Both rules are conditional on the tool being present, so the prompts stay true on a machine without it.
4. `scripts/port.py` maps the three tools to nothing: Copilot gets no alias and the Codex tools rule leaves it out, because those ports cannot reach a Claude user's MCP server. The rule text is ported unchanged; its condition makes it inert there.

Unmeasured (N6 allows it for prompt changes outside a `description` and the offload policy): no eval suite covers these agent bodies for search behavior.

## Alternatives

| Option | Why not |
|---|---|
| Guidance only in the owner's `~/.claude/CLAUDE.md` | 16 of 21 agents set `omitClaudeMd: true`; applied there for the main conversation only |
| `fff` for every Haiku agent | `researcher` has no Grep or Glob and searches the web; the three Haiku memory agents work through `mem` |
| The `ast-grep` MCP server in agents | The command through Bash does the same without a second optional server in `tools` |
| Drop `tools` so agents inherit every MCP tool | Removes the allowlist that keeps read-only agents read-only (ADR 0010) |

## Consequences

- Four agents carry three more tool schemas when `fff` is connected; eight prompts grow by one line.
- On a machine without the tools nothing changes, as observed for a missing server on the current Claude Code; older versions may behave as the issues above report.
- `port.py` accepts a tool that ports to nothing, so a later optional MCP tool needs one entry in each map.

## Revisit if

- A trace shows one of these agents reporting "not found" from an empty `fff` or `ast-grep` result without the Grep confirmation, or spending more tool rounds than before on searches: revert that agent's line (kill criterion).
- A user reports an agent that fails to launch or loses tools because of the `fff` entries: remove them from `tools`.
- `fff` ships a command-line binary: prefer it through Bash and drop the MCP entry.
