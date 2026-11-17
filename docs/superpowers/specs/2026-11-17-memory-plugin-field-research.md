# Memory plugin: field research on comparable systems

Status: in progress · Date: 2026-11-17 · For: [the design](2026-11-17-memory-plugin-design.md)

Asked for by the owner: how other memory systems for coding agents work, what to take from them, and what this plugin does better. Five research passes read the systems' own docs, repositories and papers on 2026-11-17. Every row is a lead from one reader unless marked otherwise; a claim is checked again at its source before a design decision rests on it.

## 1. Capture: what triggers a write and who writes

| System | Trigger and writer | What it keeps or skips | Reported cost or trouble |
|---|---|---|---|
| Claude Code auto memory | The main agent decides while working, or the user says "remember"; no second model | Docs: it "skips anything it can derive from the codebase" and anything the context files already say; it "doesn't save something every session" | None published |
| claude-mem | Hooks on nearly every event send each tool call to a second "observer" agent | A `<private>` tag is never stored; the observer may answer `<skip_summary reason="noise" />` or `reason="nothing durable"` | Vendor's own token claim, "not a measured recall"; a release note says observer sessions had cluttered session resume; an issue reports gigabytes of observer transcripts (snippets, not re-read) |
| OpenAI Codex memories | A background model, after a chat has been idle; separate settings for the per-chat extraction model and the consolidation model | Skips "active or short-lived sessions", chats that used external context (MCP, web search), and runs when the rate limit is low; redacts secrets | No figures; an open discussion asks for control against noise |
| Letta Code | The agent edits memory files when it "learns something durable"; background "dreaming" subagents review recent conversations "after a set number of completed agent steps or when the context window is compacted"; an optional second review before applying | Not stated | The second pass "uses more model tokens and does not ask you for approval" |
| GitHub Copilot memory | The agent, "as a byproduct of working", or on request | Each memory carries citations to the code, checked before the memory is used; votes can delete one | Expiry stated as 90 days in one page and 28 in another |
| Cline Memory Bank | An explicit "update memory bank" command that reviews every file | None | None |

What this says for the plugin:
- No system publishes a recall or noise measurement of its capture; the plugin's routing and recall trials are more than any of them shows.
- Explicit writing by the main agent, as here, is what Claude Code, Letta, Copilot and Cline do. Capture by a second model exists in claude-mem and Codex, and both report or guard against noise.
- Three ideas worth trying in the capture experiment (stage 9): gate before the small model runs (skip short sessions and ones with external tool output) and let it answer "nothing durable"; trigger at compaction rather than at every turn; keep with each provisional memory the file and symbol it is about, so it can be checked before it is trusted.
