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

## 2. Curation and consolidation

| System | What is consolidated, when, by whom | Contradictions; is the original kept? | Reported effect or failure |
|---|---|---|---|
| Mem0 | Each incoming fact is compared with its ten most similar memories; one model call picks add, update, delete or nothing, at every write | The contradicted memory is deleted (its graph variant marks an edge invalid instead); not kept | Its own benchmark gains; no failure analysis. A secondary source reports silent wrong deletes (unverified) |
| Zep / Graphiti | New facts compared by a model with related existing ones, at every ingest | The old fact gets an end date equal to the new one's start: "old facts are invalidated — not deleted" | Its own benchmark figures |
| A-MEM | Each new note triggers a model pass over its nearest neighbours, which may rewrite their context and tags | Neighbours are replaced in place; no history | An ablation: temporal questions 31.2 without the pass, 45.9 with it |
| ACE | A reflector proposes small "delta" bullets; a curator merges them with plain code and embedding de-duplication; never a whole rewrite | Bullets carry helpful and harmful counters; no restore described | Its own gains; the paper names "context collapse" as what whole rewrites cause |
| Generative Agents | A "reflection" when the summed importance of recent events passes a threshold: higher-level insights that cite the records they came from | Nothing is overwritten | Reported as critical to its results; no re-sync when sources change |
| Letta Code | Background subagents consolidate lessons into git-backed files after N steps or at compaction; a backup before "splitting large files, merging duplicates" | Git commits exist; no documented restore | A size cap; the review pass costs tokens |
| GitHub Copilot memory | No consolidation: citations checked against the code at use; expiry (the clock resets on an upvote, not on retrieval) | Downvoted memories are hidden, then deleted | Docs: validation "does not guarantee that it will recognize every outdated fact" |
| RAPTOR | Clusters of chunks summarized into parent nodes | Leaves kept | A small gain on one reading benchmark; no re-sync |
| beads, Basic Memory | "Memory decay" summaries of closed tasks (beads); nothing found (Basic Memory) | Not stated | None |

What this says for the plugin:
- **Where the plugin is already on the safer side.** Nothing is deleted and every action has an undo; Mem0 and A-MEM overwrite. Contradictions are shown to an agent as "same or opposite" instead of being resolved by one unreviewed model call per write. Sections of a synthesis are appended to, not rewritten, which is the lesson ACE draws.
- **Worth taking.** Graphiti's validity dates: a refuted or superseded memory could carry the date it stopped holding and a pointer to what replaced it, so "what did we believe in March" stays answerable (the fields mostly exist: `refuted`, `superseded_by`, `valid_until`). ACE's helpful and harmful counters: `confirm` and `refute` are the plugin's version; counting both, not only observations, would make them usable in ranking. Generative Agents' threshold on accumulated importance is a third trigger for a pass, beside count and time.
- **Nobody solves it.** No system read keeps a summary in step with its sources automatically. The plugin's section fingerprint (a note knows when its part changed) is a step none of them has; the reverse (a part knows when a note it cites changed) is not built.
- **To avoid.** A model deleting or rewriting records on every write with no review.

## 5. Evaluation: what is known about memory helping coding agents

| Source | What was varied | Result | Who ran it |
|---|---|---|---|
| Study of repository context files (arXiv 2602.11988) | No file, a model-written one, a developer-written one, on four coding agents | Resolve rate did not reliably rise (one agent 59.9 to 58.7 with a model-written file); cost rose over 20% | Independent |
| SWE-Bench-CL (arXiv 2507.00014) | Memory on or off across a sequence of repository tasks | Inconclusive by its authors' own words; memory "on par or slightly worse" | Academic pilot |
| ReasoningBank (arXiv 2509.25140) | No memory against a library of strategies, on SWE-bench Verified | 34.2 to 38.8 with one model, 54.0 to 57.4 with another | The method's authors; run count not stated |
| Mem0 paper against Zep's re-run of it | Memory systems on a chat benchmark | Mem0 reports itself above Zep; Zep's re-run puts Zep above; in Mem0's own table, giving the model the full history beats every memory system | Vendors, disagreeing about set-up |
| Letta's post | A plain file with search tools against a graph memory | The plain file scored higher (74.0% against 68.5%) | A competing vendor |

What this says for the plugin:
- There is no independent positive result for memory on multi-session coding work, and the one controlled study of context files is null on success and negative on cost. The plugin's worth is therefore unproven by anyone's standard, including ours: routing and recall trials measure where things are written and whether they are read, not whether the task came out better.
- A plain file with search held its own against specialized systems, which supports plain Markdown and a search command over a database.
- A better evaluation, within reach: paired tasks run with the memory, without it, and with the same facts in a plain context file; each task repeated five times or more; and the failure cases the literature names: a fact that changed, a contradiction, irrelevant memories as distraction, a memory of a failed attempt. Four cases at two runs cannot detect a difference of ten or twenty points; the trials so far are smoke tests and are labelled so.
