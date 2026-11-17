# Memory plugin: field research on comparable systems

Status: complete · Date: 2026-11-17 · For: [the design](2026-11-17-memory-plugin-design.md)

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

## 3. Retrieval: how stored knowledge gets back to the agent

| System | Always in context | Injected per turn | Fetched by the agent | Ranking |
|---|---|---|---|---|
| Claude Code auto memory | An index: the first 200 lines or 25 KB | No | Topic files | None |
| Anthropic memory tool | One protocol line telling the model to look at its memory folder first | No | File commands the application implements | None |
| claude-mem | A compact index of past observations, from the second session | Not documented | Three layers: `search` (ids, about 50 to 100 tokens each), `timeline`, then full observations (about 500 to 1,000 tokens each) | Keyword search with a vector store on top |
| Basic Memory | Nothing | Nothing | Search (ten per page), read with a token budget, a walk over relations | Hybrid when embeddings exist |
| Letta | Memory blocks "always visible", with a size limit in characters | No | Files in folders, on demand | n/a |
| Cursor, Windsurf | Rules marked always-on | Rules attached when a file matches a pattern, or when the agent judges a rule's description relevant | Manual mention | Pattern match or the agent's judgment |
| Mem0 | n/a | The integrator's choice | A search call, ten results by default | Semantic, lexical and entity scores fused; reranking off by default because it adds latency |
| Zep | n/a | Yes: one block every turn, replacing the previous turn's | Tools for harder cases | Recall over precision |
| Anthropic's contextual retrieval post (a vendor evaluation, not a memory system) | | | | Failure rate of the top 20: 5.7% with embeddings alone, 2.9% with a sentence of context added to each chunk plus lexical search, 1.9% with a reranker on top |

What this says for the plugin:
- **The shape is the common one**: a short always-present text and retrieval on the agent's initiative with bounded results. Vendors charge the always-on part per message and tell users to keep it short; the plugin's three lines are at the short end. Only one hosted service injects every turn.
- **Nobody measures their start text.** No system's docs report whether its always-on text makes the agent consult the memory. The plugin's recall trials (8 of 8 with a reason stated, against 7 of 8 without) are a measurement none of them publishes.
- **What the plugin lacks most**: a match on meaning. Its search is lexical, so a paraphrase or a question in another language misses (seen in this project: a Spanish question returned unrelated notes). Others add embeddings beside lexical search; the one measured result read (Anthropic's) credits lexical plus embeddings plus a reranker. The owner's note store tried dense fusion once: it passed on a fixed set and was not confirmed on new queries, so this needs its own measurement here.
- **Worth trying**: a token or line budget on what one call returns (`--max-tokens` on `show`, as Basic Memory has); the ladder that already exists (search prints handles and one line, `show` fetches) reported in tokens per step; patterns that attach a memory to files (a memory about `deploy.sh` offered when that file is touched), which is what rule systems do and is more precise than word overlap with a brief.

## 4. Storage, scopes and sync

| System | Storage | Scopes | Sync | Privacy | Reported problems |
|---|---|---|---|---|---|
| Claude Code | Markdown: context files by level, rule files with path patterns, auto memory as an index plus topic files with a type and a modified date | Managed, user, project, local | Context files through the repository; auto memory "machine-local" | Imports need approval | The memory folder is keyed by path, so one repository on two machines gets two memories; an old index loads with no sign of its age; bloat (issue reports read through a mirror) |
| Cursor, Windsurf | Rule files with frontmatter (description, patterns, always-on) | Project, user, team | Team rules pushed from a dashboard | Not found | Not searched |
| Cline Memory Bank | Six Markdown files in the repository (brief, context, patterns, tech, active context, progress) | The repository | Not stated | None | Not searched |
| OpenAI Codex | Context files by folder with a size cap; memories as generated files under its home folder | Per machine | None | Redacts secrets; "don't store secrets in memories" | Not searched |
| GitHub Copilot memory | Server-side: repository facts and user preferences | Repository facts shared with collaborators; preferences follow the user | Server | Secrets rejected at writing; expiry 90 days by default, reset by an upvote | Not searched |
| Basic Memory | Markdown with observations (`- [category] text`) and typed relations between notes | Named projects | "Track with git"; no mechanism | Local files | Not searched |
| Letta Code | A git repository of Markdown files; root files load every turn, folders on demand | Per agent, plus shared repositories | Commit and push; conflicts not described | Hosted repositories | Size caps |
| claude-mem | A database plus a vector store under the home folder | Local, optional team sharing | Opt-in cloud, on every write | A `<private>` tag is stripped before storage | Reports about redaction misses and an earlier upload of prompt history (single sources, unverified) |
| beads | Was a database plus a JSONL file in git; now a versioned database synced through git references, the JSONL kept as "an export… not the source of truth" | Per repository | Cell-level merges; same-field edits still conflict | Not found | A vendor's account says the earlier sync "proved too fragile" |
| Mem0 | Vector store plus a history database | By user, agent, application and run ids | n/a | Local or hosted | A query on one id excludes records that carry the others |

What this says for the plugin:
- **The same ground.** Markdown with frontmatter, a split between what people write and what the agent writes, and git as the sync channel are the recurring choices; plain files are also what survived at beads' expense of a second format.
- **Guards the plugin has and others report lacking**: a project memory is found from the repository, not from an absolute path of one machine (to verify once two machines exist); nothing loads an unbounded index (the start text has a cap and names counts, not content); memories carry a date, a validity and a status, where the most reported complaint elsewhere is an old entry loading with no sign of its age.
- **Worth taking**: reject secrets at writing, as Copilot and Codex do (the plugin has a forbidden-terms list for business names and the copied tool's basic secret pattern is not wired to memories); an expiry that an explicit confirmation resets, for kinds that go stale (today only findings and states expire); a `<private>` marker a person can put in a prompt so that nothing from it is stored (relevant to the capture experiment); typed relations between notes (Basic Memory), which is the owner's "builds on" idea in another system.
- **To watch in stage 7 (sync)**: one file per record limits merge conflicts to the same record edited on two machines; the curation log and the usage logs must stay out of the synced folder or be mergeable; an export must not be mistaken for the store.

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

## What to do with this

Status: complete on 2026-11-17 (five passes; every row a lead from one reader unless a number is quoted from the page). In short:

| | |
|---|---|
| The plugin does at least as well as what was read | Explicit writing with a measured routing; a start text with a measured effect; nothing deleted and step-by-step undo; contradictions shown, not auto-resolved; sections appended, not rewritten; a note that knows its part changed |
| The plugin is behind | A match on meaning (paraphrase, another language); secret rejection at writing for memories; attaching memories to files or paths; an evaluation that measures task outcome with repeated paired runs |
| Candidates, in the order proposed | 1. Secret patterns checked on every write. 2. A paired outcome evaluation (with memory, without, same facts in a plain context file), five runs per task. 3. Validity dates and both counters (confirmed, refuted) used in ranking. 4. Memories attached to path patterns. 5. A measured trial of embeddings beside lexical search, including Spanish queries. 6. For the capture experiment: gates before the small model runs, a "nothing durable" answer, a private marker |
| Not to copy | A model that deletes or rewrites records at every write; injection at every turn; a database as the source of truth |
