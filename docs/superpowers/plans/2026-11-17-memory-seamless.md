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
| Mem0 (add/update/delete at write) | Decides at each write | Not taken | The owner's rule: only a perfect duplicate is refused at writing; the rest is curation |
| Zep (invalidate, do not delete) | A contradicted fact gets an end of validity | A note contradicted by a source is marked disputed with both sources, never overwritten | Same as the plugin's rule that nothing is deleted |
| SAFE, FActScore | Split a text into atomic facts and check each against a source | The contrast mode checks a note fact by fact | Sources are official documentation and papers first; a verdict per fact: confirmed, contradicted, no source |
| CRAG | A cheap evaluator decides when retrieval needs the web | A cheap step decides whether the memory answers the question before the web is used | The depth the owner set bounds it |
| OWASP LLM01, CaMeL, the lethal trifecta, MINJA | No complete defence; separate trusted control from untrusted data, label external content, least privilege | The session that reads the web never sees the store; the session that writes the store never has the web and receives quotes as data; web-derived records carry their URL and low confidence until a second source confirms | Needed because the run is automatic and unobserved |
| Wikipedia summary style and article size | Split a subtopic that outgrows its parent; the parent keeps a short summary and a pointer | Parent with a summary part and a pointer; child with a link back; merge back when a child stays small | A conservation check (every sentence of the old part is in the parent or the child), because no source measures what a reorganization loses |

## A change to how syntheses are written

Today a part cites its notes only in one `Sources:` line. Every later step has to guess which note supports which sentence: the checker re-reads all cited notes for each claim, a sibling update cannot tell which notes a changed sentence touches, a split cannot tell which sentences are specific to the child, and the measured error "a figure moved to another note's setting" cannot be checked mechanically.

Proposed: each sentence that states a finding ends with the handle of the note it rests on (a short inline reference); the `Sources:` line stays as the part's list. With it the checker compares a sentence with its one note, sibling updates and splits work by reference, and the conservation check is exact. It changes the writer and checker prompts and adds a rule to `mem check`; existing syntheses stay valid and are upgraded when they are next rewritten. To be measured against the lean loop's numbers (accuracy and cost) before it is adopted.

## Stages (each with its own trial and kill criterion; nothing joins `mem-auto` before its trial)

- [ ] **1. Research on demand with the web, to a set depth.** A command `mem-research` chains headless sessions with separated roles: memory step (store, no web) answers and lists what is missing or to contrast; web step (web only, sees no store) returns quotes with URLs from official documentation and papers; writing step (store, no web) records findings with their URL and low confidence, and for a contrast adds confirmed evidence or marks a note disputed. Depth: `memory` (no web), `contrast` (few pages, default), `deep` (more pages, papers); an option of the plugin sets the default and the request can override it. `memory-researcher` loses its web tools and points to the command. Check: a trial with planted facts (a correct one, a contradicted one, one with no source, and a page that carries an instruction) shows the three verdicts, nothing written from the instruction, and no store text in the web step's input.
- [ ] **2. Inline note references in syntheses.** Writer, checker and `mem check`; trial against the lean loop on the same three topics.
- [ ] **3. Integration and sibling updates.** An unattached note on a covered topic is added to its part and attached; the part's other notes get links, evidence and dispute marks, never claim rewrites. Trial on a store copy with seeded notes.
- [ ] **4. Splitting a synthesis.** Detection in `mem curate --notes`; `memory-synthesizer` in split mode writes the child part and the revised parent part; conservation check; one reversible step. Trial on a copy with a seeded sub-subject.
- [ ] **5. The steps join `mem-auto`**, each with its share of the run's budget, after its trial.

## Results

Pending.
