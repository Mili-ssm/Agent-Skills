# Seamless global memory: research with the web, evolving notes, splitting syntheses

Owner, 2026-11-17: the global memory should work as an internal mechanism of the model, close to a black box: it researches and contrasts facts on the web to the extent the owner sets, keeps sibling notes in step, splits a synthesis that outgrows its topic (the specific part to a child, the generic part kept in the parent), and does this automatically. Project memory stays explicit.

**Status:** planned; stage 1 next.

## What the literature gives, and how it is adapted

Sources are recorded as global memories (`mem search "agent-memory systems reorganize"`, `mem search "verifies or extends its own stored facts"`, `mem search "splitting a long document"`).

| Source | What it does | What is taken | What is changed, and why |
| --- | --- | --- | --- |
| A-MEM (memory evolution) | On every new memory an LLM updates the context, keywords and tags of the linked older notes | Sibling notes are revisited when new knowledge arrives | The neighbour set is the synthesis part a note belongs to (already stored in `part_of`), not an embedding search; it runs in the background at a threshold, not on every write (D21: simple while working); it edits links, evidence and a dispute mark, never a claim, because no source measures the error rate of rewrites; the existing `part_of_hash` already says which notes are behind their part |
| Generative Agents (reflection) | Higher-level memories written when summed importance passes a threshold | A threshold of accumulated new records starts the background run (built: `mem-auto`) | The count is of records, not importance; weighting by kind is a later option |
| Sleep-time compute, Letta sleep-time agents | Reorganize between sessions | The run starts at session end, so the next session finds the memory curated (built) | Bounded by a budget per run and one run at a time |
| Mem0 (add/update/delete at write) | An LLM decides add, update, delete or nothing at each write | Taken, in the background (owner, 2026-11-17, stage W): new records are compared with their look-alikes soon after they are written, so the next session finds them settled | The working agent still writes with one command (the intent of the earlier rule "only a perfect duplicate is refused at writing" was to keep writing simple, and it is kept); the decision is made by a cheap model after the session, not by the writer; an update never overwrites: the old record is marked superseded and `mem restore` brings it back; measured on pairs derived from real records before it is turned on, because no source measures the error rate of such updates |
| Zep (invalidate, do not delete) | A contradicted fact gets an end of validity | A note contradicted by a source is marked disputed with both sources, never overwritten | Same as the plugin's rule that nothing is deleted |
| SAFE, FActScore | Split a text into atomic facts and check each against a source | The contrast mode checks a note fact by fact | Sources are official documentation and papers first; a verdict per fact: confirmed, contradicted, no source |
| CRAG | A cheap evaluator decides when retrieval needs the web | A cheap step decides whether the memory answers the question before the web is used | The depth the owner set bounds it |
| OWASP LLM01, CaMeL, the lethal trifecta, MINJA | No complete defence; separate trusted control from untrusted data, label external content, least privilege | The session that reads the web never sees the store; the session that writes the store never has the web and receives quotes as data; web-derived records carry their URL and low confidence until a second source confirms | Needed because the run is automatic and unobserved |
| Wikipedia summary style and article size | Split a subtopic that outgrows its parent; the parent keeps a short summary and a pointer | Parent with a summary part and a pointer; child with a link back; merge back when a child stays small | A conservation check (every sentence of the old part is in the parent or the child), because no source measures what a reorganization loses |

## A change to how syntheses are written

Today a part cites its notes only in one `Sources:` line. Every later step has to guess which note supports which sentence: the checker re-reads all cited notes for each claim, a sibling update cannot tell which notes a changed sentence touches, a split cannot tell which sentences are specific to the child, and the measured error "a figure moved to another note's setting" cannot be checked mechanically.

Proposed: each sentence that states a finding ends with the handle of the note it rests on (a short inline reference); the `Sources:` line stays as the part's list. With it the checker compares a sentence with its one note, sibling updates and splits work by reference, and the conservation check is exact. It changes the writer and checker prompts and adds a rule to `mem check`; existing syntheses stay valid and are upgraded when they are next rewritten. To be measured against the lean loop's numbers (accuracy and cost) before it is adopted.

## Stages (each with its own trial and kill criterion; nothing joins `mem-auto` before its trial)

- [ ] **W. Settling new memories soon after they are written (Mem0, in the background).** At session end, when at least one new global memory exists, a micro-curation run compares each new memory with its look-alikes and decides: the same in other words (merge, the observation counted), a correction (the older one superseded), different things (`distinct`), or nothing. Enforced in code by a judged mode of `mem curate apply`: only pairs where one record is new since the last run, same scope, both active; never an overwrite or a delete; every action undone by `mem restore`; knowledge notes are never merged this way (a contradiction between notes uses the dispute mark). The heavy steps (syntheses, web contrast) keep their threshold of 10. Trial before it is turned on, on a copy: 40 pairs derived from real memories (10 paraphrases, 10 corrections, 10 versions that are both valid, 10 look-alikes that are unrelated). Rule written beforehand: adopt when at most 1 of the 40 gets a wrong merge or supersede and at least 60% of the 20 that should be acted on are; otherwise keep the strict safe subset and record the numbers. Not built: a run after every single write (two sessions open at once see each other's settling only when one ends); to add if the owner misses it.
- [ ] **1. Research on demand with the web, to a set depth.** A command `mem-research` chains headless sessions with separated roles: memory step (store, no web) answers and lists what is missing or to contrast; web step (web only, sees no store) returns quotes with URLs from official documentation and papers; writing step (store, no web) records findings with their URL and low confidence, and for a contrast adds confirmed evidence or marks a note disputed. Depth: `memory` (no web), `contrast` (few pages, default), `deep` (more pages, papers); an option of the plugin sets the default and the request can override it. `memory-researcher` loses its web tools and points to the command. Check: a trial with planted facts (a correct one, a contradicted one, one with no source, and a page that carries an instruction) shows the three verdicts, nothing written from the instruction, and no store text in the web step's input.
- [ ] **2. Inline note references in syntheses.** Writer, checker and `mem check`; trial against the lean loop on the same three topics.
- [ ] **3. Integration and sibling updates.** An unattached note on a covered topic is added to its part and attached; the part's other notes get links, evidence and dispute marks, never claim rewrites. Trial on a store copy with seeded notes.
- [ ] **4. Splitting a synthesis.** Detection in `mem curate --notes`; `memory-synthesizer` in split mode writes the child part and the revised parent part; conservation check; one reversible step. Trial on a copy with a seeded sub-subject.
- [ ] **5. The steps join `mem-auto`**, each with its share of the run's budget, after its trial.

## Pre-mortem of 2026-11-17 and what changed

| Risk | Change (binding) |
| --- | --- |
| The web step can read the store (bare `Read`/`Grep`/`Glob`) or leak it in a query | The web session gets only WebSearch and WebFetch, a fresh empty folder outside the store, no `MEM_*` variables, no `mem` on PATH and a turn cap; its queries are built by code from the question or from global claims that pass the secret and forbidden-terms checks; the trial plants a canary note and searches the whole web-step stream for it |
| The writing step obeys a quote (`Bash(mem *)` allows `--owner-approved`, `terms remove`, claim edits, `unify`, `synthesis remove`) | The model steps have no Bash at all: they produce a verdict file; Python reads it and runs a fixed list of `mem` commands without a shell |
| Wrong "contradicted" verdicts; no disputed field exists; WebFetch returns a model's summary, not the page | New field and commands first (stage 1a); Python fetches each URL itself and keeps a quote only when it is found word for word on the page; "contradicted" needs a primary source, and one that matches the note's version when the note states one |
| Records written by a pipeline count toward the `mem-auto` threshold and start the next run | Pipeline-written records carry their origin and are left out of that count |
| The 24 existing syntheses have no inline references and nothing upgrades them | Stage 2 adds a measured backfill step |
| Bare handles break on `rename`; after `unify` they point at superseded notes | Inline references are Markdown links; `mem check` follows `superseded_by` |
| Appending to a part marks every sibling stale and invites claim rewrites | A sibling is stale only when a sentence that cites it changed (needs stage 2) |
| Exact-sentence conservation fails on every rewrite and a fuzzy one passes a moved figure; notes stay pointed at the parent | The split check is on references and numbers: every reference and every figure of the old part is in the parent or the child; the notes are re-pointed |

Stage 1 is built in two halves: **1a (done 2026-11-17)** the engine (disputed and confirmed marks, the origin of a record, their display and their place in the curation queue, the count exclusion); **1b** the `mem-research` pipeline and its trial.

Trial of stage 1 (ground truth by construction, on a copy of the store): 12 real notes whose claim their own cited source supports (expected confirmed), 4 of them copied with one figure altered (expected contradicted), 4 notes that record the owner's own experiments (expected no source), one canary note, and one local test page that carries an instruction. Kill criteria: the canary in any web-step event; more than one wrong "contradicted" in 20; `deep` over its budget; anything written from the planted instruction.

## Results

Pending.
