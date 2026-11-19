# Seamless global memory: research with the web, evolving notes, splitting syntheses

Owner, 2026-11-17: the global memory should work as an internal mechanism of the model, close to a black box: it researches and contrasts facts on the web to the extent the owner sets, keeps sibling notes in step, splits a synthesis that outgrows its topic (the specific part to a child, the generic part kept in the parent), and does this automatically. Project memory stays explicit.

**Status (2026-11-19):** stages W and 1 are built, measured and merged into `main` (PR 128, PR 129). Stage 2 is built and measured on the branch `feat/memory-inline-refs`: references are added after writing, and the confirming run passed (see "Stage 2 confirming run" under "Results"). Open in stage 2: task 6 on the real store (the hand fix of one link, the plugin update, the backfill), each with the owner's word, and the reference audit before stage 3. Stages 3 to 5 are not started.

## Where to resume: stages 2 to 5

Start with stage 2: stages 3 and 4 need its inline references, and stage 5 only wires what the others measured. One branch per stage; a merge into `main` needs the owner's word each time.

### State on 2026-11-18

| Fact | Detail |
|---|---|
| `main` | `7d190a1`; the installed plugins are at `a65b322` |
| Owner settings | `auto_settle` and `auto_curation` on for `memory@mili-ssm`; `research_depth` unset (default `contrast`) |
| Settling in a real session | Seen on 2026-11-18: `mem-settle status` reports a run that day, state ok, 0 pairs, 0 USD, no failure. A run that judges pairs is still to be seen |
| Tests | `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`: 1137 passed, 4 skipped on `main`; 1240 passed, 4 skipped on the stage 2 branch. `test_merge_logs_both_files_and_restore_undoes_each` fails during the hour after local midnight (the curation log writes its date in UTC, the test expects the local date): an open low defect |
| Open low items | three in `evals/settle/run_trial.py` (see "Results"); an unclosed `<script>` hides the rest of a fetched page (a false "quote not on the page"); the web session's own `official` label is trusted |

### How each stage was built so far (repeat it)

1. Write the stage's design into this file, then dispatch `agent-skills:pre-mortem` on that section and amend the text before any code.
2. One `agent-skills:implementer` per task with a six-part brief; `agent-skills:skeptical-reviewer` after each commit, at most two rounds; rerun the tests yourself.
3. Fix the trial's rule in this file before the run; run it on a store copy under the git-ignored `target/` through `plugins/memory/evals/trial_env.py`; write the numbers and their limits under "Results".
4. Rules that held in every stage: no model session gets a shell (it writes a file, Python applies it); every automatic action is undoable with one command; a headless session needs `--tools` for which tools exist and `--allowedTools` for the permission to call them; trials never touch the real store.

### Stage 2: inline note references in syntheses

- **Intent:** every later step must know which note supports which sentence. Nearly every part cites its notes only in its `Sources:` line (see "A change to how syntheses are written"; the count is in the design below).
- **Bound by the pre-mortem of 2026-11-17:** a reference is a Markdown link to the note, never a bare handle (`mem rename` rewrites only links); `mem check` follows `superseded_by`, so a reference to a note that was unified away is reported with its successor; the 24 existing syntheses get a measured backfill step, they are not left to be upgraded "when next rewritten".
- **Files:** writer prompt in `plugins/memory/agents/memory-synthesizer.md` (and `plugins/memory/evals/synthesis/writer-brief.md` for the trial); checker and fixer in `plugins/memory/engine/synth_briefs/`; the loop in `plugins/memory/engine/synth_pipeline.py` (`lean_loop`); `cmd_check` in `plugins/memory/engine/mem.py`; the pipeline command `plugins/memory/bin/mem-synthesize`.
- **Tasks:** (a) decide the reference form and where it may stand (end of the sentence that states a finding); (b) `mem check` rule: every reference resolves to a live note that is in the part's `Sources:` line; (c) writer and checker briefs: the checker compares a sentence with its one referenced note; (d) backfill: a session proposes references for an existing part as a file, Python accepts a reference only when the note is in the part's `Sources:` and applies them through `mem synthesis edit`; (e) the trial.
- **Trial:** `plugins/memory/evals/synthesis/run_trials.py`, the same three topics as the lean loop, whose recorded numbers are the baseline: Haiku writer at medium effort, 6.8 unsupported claims per 100 at 0.25 USD per synthesis (preliminary, one run). Rule to fix before the run; proposed: adopt when unsupported claims do not rise and cost rises by less than 30%; for the backfill, 0 references to a note that does not support its sentence in a judged sample of 40.
- **Cost estimate:** about 0.3 USD per Haiku synthesis and 0.05 to 0.2 per judge; a three-topic run with judging about 1.5 to 3 USD (written before the design; the design's own estimate below replaces it). Earlier estimates in this project were low by 3 to 5 times: state the estimate to the owner before the run.

#### Stage 2 design (2026-11-18, amended after its pre-mortem)

Measured on the real store before designing (2026-11-18): 24 syntheses, 218 parts, 1027 source links; 65 inline note links already exist in 14 parts of 3 syntheses (63 of them directly after a sentence's closing punctuation, most at the end of a paragraph); 1 of the 65 names a note that is not on its part's `Sources:` line; no source names a superseded note. Two statements above were wrong: parts do not cite "only in `Sources:`", and `mem check` does not follow `superseded_by` today (rule 16 only checks that the named handle exists; `mem unify` already repoints links, synthesis files included).

| Decision | Choice | Reason |
|---|---|---|
| Term | **reference**: a relative Markdown link, in a part's body, whose target is in a note folder. **source**: a link on the part's `Sources:` line. Links to a synthesis, anchors and URLs are neither | One term per concept; the `Sources:` line stays the part's list |
| Form | `[label](../knowledge/<domain>/<file>.md)`: the target as on the `Sources:` line, the label that target has there | `mem rename` and `mem unify` rewrite targets, never labels, so only the target carries meaning |
| Place and owner | Directly after the closing punctuation of the sentence it supports; several may follow one sentence (a comparison rests on two notes). Its owner is that sentence only: a reference at the end of a paragraph does not cover the paragraph. A reference inside a sentence belongs to that sentence (task 0: the two existing ones are note links used as words of the sentence). A reference with no sentence before it on its line, or in the `## Summary`, has no owner: the parser reports it and Python never reassigns it | 63 of the 65 existing links stand after the punctuation, written by the Haiku writer unprompted. The pre-mortem showed that a paragraph-final link read as "covers the paragraph" would make stages 3 and 4 follow the wrong sentences in silence |
| Parser | One function in `syntheses.py` returns a part as units `(number, text, references)`. A unit is a sentence, a table row or a list item. It never splits inside a link, a code span or a number, nor after `e.g.`, `i.e.`, `et al.`, `vs.`, `cf.`; a bold label such as `**What it is.**` is not a unit. The backfill, the checker's numbered input, the guard and stages 3 and 4 use it | Today's `_sentences` splits on every `.`, `!`, `?` and line break (it cuts `0.82` in two), and `syntheses._LINK`, `mem.py`'s `_LINK` and `synth_pipeline.split_parts` each parse on their own |
| Which sentences need one | Every sentence that states a finding from a note. Exempt: sentences that start with `Inference:`, the `## Summary`, connecting sentences. Not decidable by code: the writer brief asks for it, the checker lists a finding without one, the trial counts coverage | A `mem check` rule on "every sentence" would fail on connecting sentences and on the parts not yet backfilled |
| `mem check` (rule 15) and write time (`add`, `append`, `edit`) | (1) a reference names a note on its part's `Sources:` line; (2) a reference or source that names a note with `superseded_by` is reported with its successor's handle; (3) a reference without an owner is reported | Decidable by code. The 1 failing link of the real store is fixed by hand, with the owner's word, before the installed plugin is updated: the backfill only adds references. The trial harness fixes it in its copy |
| Checker | It reads the part as numbered units (a file Python writes) and still reads all of the part's sources. Unsupported claims keep today's line format and count. Reference problems go on separate lines, `REF: <part> \| <number> \| missing \| <source target>` or `REF: <part> \| <number> \| wrong <the reference's target> \| <source target, or none>`, outside `COUNTS unsupported`; they never reach the fixer or the delete-only step. Python applies a `REF:` line as an added, swapped or removed reference under the backfill's acceptance rule | In the lean loop every claim line still listed after the second check has its sentence deleted (`DELETE_ONLY`): a correct sentence that only lacked a reference would be deleted |
| Fixer | A replacement sentence carries its references; the brief says to keep the references of every sentence it does not change | Below |
| `_guard_shrink` | Compares units with references removed, so adding a reference is never a dropped sentence. On a unit whose text did not change, a reference that disappears is refused, with or without `--shrink` | Its link check is a set over the whole part, `Sources:` line included, so a dropped or swapped reference passes today, and the fixer brief uses `--shrink` on every edit |
| `part_of_hash` | `fingerprint` hashes the part with its references removed (one that follows a sentence is dropped, one inside a sentence is reduced to its label), so the backfill, `mem rename` and `mem unify` change no hash. Staleness accepts the old definition too, so the 14 parts that already hold inline links are not listed as stale between the update and their backfill; the backfill re-stamps their current member notes in its group | With today's definition, adding references would list all 354 attached notes as behind their part, and so would every later rename or unify of a referenced note |
| Backfill | `mem-synthesize --backfill [s:<handle>]`, one session per synthesis, started with `--tools Read` and read permission for its work folder and the store only (no shell, no web, no write tool). Python writes each part's numbered units and sources to a file; the session answers `<part> \| <number> \| <source target>`, or `none` for a finding no source supports, and no line for a sentence that states no finding; it has no write tool, so its answer text is the proposals. Python accepts a line only when the unit exists, the target is on the part's `Sources:` line and the unit does not carry it yet; it builds the new text itself, so the words never pass through the model. `none` lines go to the run report and change nothing. Parts with only URL or `experience` sources get no session. A new engine command `mem synthesis refs s:<handle> --file F` applies all parts of one synthesis as one logged group: one `mem restore s:<handle>` undoes it. A done list by part fingerprint in the run's state folder skips parts already processed | The session can only choose among the part's own sources: a wrong choice is a wrong reference, never a changed sentence. `mem synthesis edit` logs each part alone, which would need 218 restores |
| Reader cost | `mem show` prints a reference as `[n]`, the place of its note on the part's `Sources:` line, computed when shown (first built as `[label]`; changed on 2026-11-18 after the backfill trial, where labels made the shown text 10% to 28% longer), and gets an option for the stored text, which the fixer and every step that edits a part use; storage is unchanged. On the shown `Sources:` line each note carries its number. A stored part may not hold a bracketed number (`[3]`), in `add`, `append`, `edit` and `mem check`: the review before the push found that a sentence reworded from the shown form was saved with a literal `[1]` and no link, and the real store holds no such token. The trial reports the tokens of each synthesis as stored and as shown | Task 0 measured a reference at about 29 tokens and a unit at about 53: references on 80% of units would add about 44% to the stored text, above the 35% the pre-mortem set as its limit; what a reader is shown has its own limit of 15% (kill criteria). The label alone costs about 5 tokens, and the `Sources:` line still carries each label's link |

Exception to "no model session gets a shell", stated so it is not read as a breach: the writer, checker and fixer sessions of the synthesis loop, and the judge sessions of the trial harness (which run through the same session helper), keep `Bash(mem *)` as on `main`; the backfill session does not.

Tasks, in order (each one `implementer` brief, except 0 and 6):

0. *Done 2026-11-18, results below.* Spike, no commit of store text: run a draft of the parser over the 218 parts of a store copy under `target/`. Report references without an owner, units split inside a number or an abbreviation, bold labels and table rows met, and the token size of each synthesis. The parser's rules are fixed from this report.
1. Engine, in two briefs: (1a) the parser, `fingerprint` and the staleness comparison, the guard; (1b) `mem check` rules (1) to (3), also at write time, and the `mem show` output. Tests include `mem rename` and `mem unify` over a synthesis body (no hash changes). *1a done 2026-11-18* (`syntheses.units`, `without_references`, `fingerprint_legacy`, `is_current`, `mem synthesis edit --drop-references`): on the store copy, 4056 units, all 65 existing references owned, no span mismatch, and the new fingerprint equals the old one on all 204 parts without references. Rulings on its review: the guard protects only units whose text did not change, so a fixer that rewords a sentence can still drop its reference, and the checker's `REF:` lines are what catches that; notes of the 14 parts that already hold references keep an old-definition hash until the backfill re-stamps them (task 2), so a `rename` of a note they reference before that lists them as stale; `--drop-references` lifts the check for the whole part, and only Python steps pass it. *1b done 2026-11-18*: on a full store copy `mem check` reports exactly the 1 known link, and `mem show --all` of the synthesis with 63 references shrinks from 61,149 to 54,785 characters. Its review found that a part copied from plain `mem show` and saved with `--shrink` lost every link target without an error: `mem synthesis edit` now refuses a text that holds only the label of a stored reference, whatever the flags. Deferred, low: a reference written with a title or in angle brackets (`[a](<path>)`) is not read as a reference; a sentence wrapped over two lines with its reference opening the second line is refused (the message says to keep it on the same line); rule (2) names only the immediate successor of a chain.
2. Engine: `mem synthesis refs` with its group, the re-stamp and `mem restore`. *Done 2026-11-18.* On a store copy: 60 and 72 proposals applied to two syntheses (references 0 to 60 and 63 to 131), the words of every part unchanged, a second run of the same file refused every line, `mem check` unchanged, no note listed as stale before or after (15 notes re-stamped in the group of the synthesis that already held references), and one `mem restore` per synthesis returned its file byte for byte. Its review found that a reference could not be removed from a comma-separated pair (refused by the invariant, nothing written): fixed, the unit's run of references is written again. Deferred, low: a member note whose `part_of` is spelled with the `s:` prefix is not re-stamped; a member note with CRLF line ends that needs a re-stamp stops the run.
3. Writer, checker and fixer: `agents/memory-synthesizer.md`, `skills/memory-synthesis/SKILL.md`, `evals/synthesis/writer-brief.md`, `synth_briefs/checker-brief.md`, `synth_briefs/fixer-brief.md`; `parse_report` and `lean_loop` for `REF:` lines; `lean_loop` takes a briefs folder. *Done 2026-11-18.* The rule for where a reference stands lives once, in the skill's step 3. Two reviews. The prompt review found the checker brief defining a claim two ways (against the sentence's references, and against the cited notes): now one definition, against every source of the part, with an example report; the fixer's link rule is its own step with a before and after; the writer's rule is a list with its reason and the refusal of `add`. The code review found that a checker counting a reference problem in `COUNTS` with no claim line still started the fixer and the delete-only step: a report with `REF:` lines and no claim line now counts 0 unsupported; `REF:` lines behind a bullet or in backticks are read, malformed ones and refusal reasons are in the loop's result. Ruling: a `wrong` line whose reference stands inside its sentence adds the right reference and leaves the other, because that one is part of the sentence's words. Deferred, low: a `REF:` part given as a line range is refused; `REF:` lines of a scoped second check may name parts outside its scope (references only); a failure while writing the units file stops the loop.
4. Backfill: `mem-synthesize --backfill`, tests with a fake `claude`. *Done 2026-11-18* (`engine/backfill.py`, `synth_briefs/backfill-brief.md`). The session is started with `--tools Read` and read permission for its work folder and the store only. A dry run on a store copy selects all 24 syntheses. Its review led to one fix round: an answer of the single word `nothing` marks a synthesis done (an empty answer stays a failure), a part is marked done only when the answer had no unreadable line or named it, the done list is merged per synthesis at each write, a corrupt done list stops the run, the store key is the resolved path, `--topic` with `--backfill` is an error. The dry run's 0.15 USD per synthesis is a guess until the trial measures it.
5. Trial harness (`evals/synthesis/run_trials.py`). *Done 2026-11-18, in two briefs and one fix round.* Arm R is the branch. Arm M, the control, is `main` as shipped: main's own harness runs it from a git worktree of `main` under `target/`, and this harness judges the store it keeps. Both arms get the same two judges: unsupported claims with the checker brief of `main` (`evals/synthesis/frozen-main/`) on text without references, and a reference judgment (`evals/synthesis/ref-judge-brief.md`) that marks each unit a finding or not and each reference right or wrong. That judgment is calibrated on 20 planted wrong references, each a note of another part of the same synthesis. `--backfill-trial` runs the backfill on a store copy. Its review found defects that would have spoiled the run, all fixed: the control loaded the branch's plugin and engine (a first design ran `main`'s texts inside the branch); `--no-ref-judge` could print PASS; a backfill that applied nothing passed every check; `--budget` capped neither the judges nor work in flight; a planted reference could be a right one. Limit: the sessions of `main`'s harness are not capped by this one, and each control row pays for one judge session of `main` that is not used.
6. The trial runs and its results here; then, with the owner's word, the hand fix of the 1 link, the backfill of the real store and the update of the installed plugin.

Task 0 result (2026-11-18, a draft parser over a copy of the 24 syntheses under `target/`; a script outside the repository):

| Measure | Value |
|---|---|
| Units | 4072: 2784 sentences in paragraphs, 1221 in list items, 67 table rows; every one of the 218 parts uses bold labels |
| Existing references | 63 follow a sentence and get that sentence as owner; 2 stand inside a sentence; none is alone on a line |
| Splits inside a number | 0 (a sentence ends only where white space or the line's end follows the punctuation); 118 abbreviation endings were kept unsplit |
| To handle in task 1a | A bold label that starts with a number (`**3. ...`) was cut after the number; short closing sentences ("Confidence: low.") are units and need no reference |
| Size | About 217,000 tokens in all (characters / 4); a reference about 29 tokens; one reference per source would add 14%, references on 60% of units 33% |
| `Inference:` sentences | 1 in the whole store: the exemption exists in the writer's rules but is hardly used, so coverage is counted over all finding units |

Trial rule, as the constants at the top of `run_trials.py` hold it (proposed; the owner fixes it before the run):

- **Writer (arms M and R, the same three topics, two runs per arm and topic).** *Fixed by the owner on 2026-11-18 before the run, with the estimate of 11 to 12 USD under a cap of 15, plus the control's sessions.* Adopt when all hold: R's unsupported claims per 100 are at most M's plus the larger of 2 points and the gap between M's two runs; R's mean pipeline cost is below 1.3 times M's; every R synthesis passes `mem check`; at least 80% of the units the judge marks as findings carry a reference; at most 5% of judged references are wrong; R's syntheses as `mem show` prints them are at most 1.15 times M's in tokens. Coverage and wrong references are the worst case, in which a unit the judge skipped is a finding without a reference and a skipped reference is wrong. The result is preliminary, never an adoption, with fewer than two runs per arm, when M's runs differ by more than 4 points, when the judge finds fewer than 16 of 20 planted references (or fewer than 10 could be planted), when a reference report skips more than 10% of the units, or when the reference judgment was not run. Not measured: the share of units resting on two or more notes that carry one reference. One run per arm cannot decide this: with about 220 claims per arm the difference has a standard deviation near 2.4 points, and the recorded baseline moved 2 points when one topic was left out.
- **Backfill (three syntheses of a store copy).** *Fixed by the owner on 2026-11-18 before the run, with the estimate of 3 to 4 USD under a cap of 8.* First, or nothing else is read: the backfill applied at least one reference in every synthesis and the sample is not empty. Then: at most 1 wrong reference in a sample of 100 new references (fewer than 100: preliminary; 0 of 40 would only bound the error rate at about 7.5%); at least 60% of the findings that had no reference before get one (worst case); `none` answers at most 20% of the units sent; no part differs from before once references are removed, `mem check` passes and no more notes are listed as behind their section (by code); one `mem restore s:<handle>` per synthesis returns every file to its bytes; the calibration is valid.

Kill criteria:

| When | Then |
|---|---|
| Task 0 finds a split inside a number, or an existing reference without an owner that the rules above do not explain | Fix the parser's rules before task 1 |
| The delete-only step removes a sentence listed only on a `REF:` line | Stop: the loop is wrong |
| The syntheses of the trial copies, as `mem show` prints them, grow by more than 15% in tokens | Do not adopt: shorten the label rule first |
| `mem curate --notes` lists more stale notes after a backfill, a `rename` or a `unify` on the copy | Stop: the fingerprint is wrong |
| The reference judge finds fewer than 16 of 20 planted swaps, or M's two runs differ by more than 4 points | The result is preliminary: no adoption from it |
| Backfill coverage below 60%, or more than 20% of units answered `none` | No backfill of the real store; the `none` units are recorded as candidate unsupported claims |

Cost estimate, by sessions (2026-11-18): the writer trial starts about 100 sessions (12 pipelines of 4 to 5 sessions, 18 judge sessions, 12 reference judgments, 6 calibrations), estimated at 11 to 12 USD and run with `--budget 15`; the control's sessions are outside that cap (about 2 to 4 USD more). The backfill trial starts 3 backfill sessions, 3 reference judgments and up to 3 calibrations, estimated at 3 to 4 USD and run with `--budget 8`. Together about 15 USD estimated, about 27 USD at the caps. Earlier estimates in this project were low by 3 to 5 times; here the caps, not the estimate, bound the spend. One run per arm halves the writer trial and makes its result preliminary by rule. The real backfill is estimated after the trial from its measured cost per part.

Pre-mortem of 2026-11-18 (12 risks, 8 rated high), each checked in the code before it changed the text: the delete-only step and the new kinds; the guard blind to references; `_sentences` splitting inside figures; paragraph-final links and ownership; the backfill's undo; `rename` and `unify` changing fingerprints; rule (1) failing on the real store and its copies; arm M running the new briefs; trial thresholds inside the noise; the backfill sample and its rerun; reader tokens; the backfill session inheriting `Bash(mem *)`.

### Stage 3: integration and sibling updates

- **Intent:** a new note on a covered topic joins its synthesis without anyone asking, and the notes of that part stay in step.
- **Bound:** a sibling note is stale only when a sentence that cites it changed (needs stage 2); siblings receive links, evidence lines and dispute marks, never a rewritten claim.
- **Exists:** `mem curate --notes` lists unattached notes on a covered topic; `mem curate apply --safe` attaches a note only when the part's `Sources:` line already backs it; `mem synthesis append`, `attach`; `mem note confirm`, `mem note dispute` (stage 1a).
- **Tasks:** (a) a session writes the sentence to append, with its reference, as a file; Python appends and attaches; (b) staleness by changed sentence; (c) the sibling step proposes links and evidence as a file, Python applies fixed commands.
- **Trial:** a store copy with seeded notes: ones that belong to a part, ones on the topic that do not belong, and one that contradicts a sibling. Count wrong attachments and any claim that changed.

### Stage 4: splitting a synthesis

- **Intent (owner, 2026-11-17):** when enough notes of a synthesis are specific to a sub-subject, that part moves to a child synthesis; the parent keeps the generic part and a pointer; the two are linked. The owner's example: parallelism in the software-engineering synthesis stays generic, parallelism in a Rust synthesis is about Rust.
- **Bound:** the conservation check is on references and numbers (every reference and every figure of the old part is in the parent or the child), not on sentences; the moved notes are re-pointed to the child; the split is one reversible step.
- **Known facts:** notes carry several topics, and that is not duplication (all 11 programming-languages knowledge notes also sit in the software-engineering synthesis); the topic tree and the synthesis tree stay separate; no command deletes a whole synthesis, and an emptied one still holds its topic; the only concrete size rules found are Wikipedia's (split a subtopic that needs more detail than the parent can hold or is much larger than its siblings).
- **Open, for the owner:** the thresholds (how many notes sharing a second topic, or what size, starts a split), and whether a split is applied automatically or proposed first. Present options with their trade-offs; do not pick silently.
- **Tasks:** (a) detection by code in `mem curate --notes`; (b) a `mem synthesis split` command that moves whole parts with their notes and leaves a summary part with a pointer; (c) `memory-synthesizer` in split mode for a part that mixes generic and specific sentences; (d) the conservation check; (e) undo.
- **Trial:** a store copy with a seeded sub-subject; kill when a reference or a figure is lost, or a note points at the wrong synthesis.

### Stage 5: joining `mem-auto`

- **Intent:** the owner does not ask for any of this; it runs within a bounded budget and a failure is visible.
- **Rule:** a step joins only after its own trial, with its share of the run's budget (`plugins/memory/bin/mem-auto`, option `auto_curation_budget`, default 2 USD) and its own failure line at session start. Settling (stage W) already runs on its own trigger and stays apart.
- **Decide with the owner before wiring web contrast in:** the trial confirmed 6 of 12 real notes, at the threshold; widening what the web session reaches comes first. An automatic contrast would also send note claims to a web search without a request: the owner sets how far that goes (the option `research_depth` exists; a separate option for automatic contrast is proposed).


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

Today nearly every part cites its notes only in one `Sources:` line (on 2026-11-18, 204 of 218 parts). Every later step has to guess which note supports which sentence: the checker re-reads all cited notes for each claim, a sibling update cannot tell which notes a changed sentence touches, a split cannot tell which sentences are specific to the child, and the measured error "a figure moved to another note's setting" cannot be checked mechanically.

Proposed: each sentence that states a finding ends with the handle of the note it rests on (a short inline reference); the `Sources:` line stays as the part's list. With it the checker compares a sentence with its one note, sibling updates and splits work by reference, and the conservation check is exact. It changes the writer and checker prompts and adds a rule to `mem check`; existing syntheses stay valid and are upgraded when they are next rewritten. To be measured against the lean loop's numbers (accuracy and cost) before it is adopted.

## Stages (each with its own trial and kill criterion; nothing joins `mem-auto` before its trial)

- [x] **W. Settling new memories soon after they are written (Mem0, in the background).** Intent (owner, 2026-11-17): the memory a session reads is already settled, also inside a session that lasts hours. Design after the pre-mortem of stage W (table below):
  - **Trigger.** A write (`mem remember`, `mem memory edit`) to the global scope checks, at the cost of reading one state file: handles not yet judged exist, and the last settling run ended more than `auto_settle_minutes` ago (default 30; an option, because the owner sets how eager the memory is). When both hold it starts one detached settling run (`flock -n`, as `mem-auto`). The session-end hook starts the same run for what is left. The trigger lives in the write path, not in a timer: a session that writes nothing costs nothing, and two sessions open at once settle each other's records.
  - **Own state.** The run keeps its own list of judged handles; it never reads or writes `finished` of `mem-auto`, so the count of 10 for the heavy steps (syntheses, web contrast) is untouched, and a record written while a run is under way is judged by the next one. It runs no synthesis step.
  - **What is compared.** Only the queue pairs (`records.pairs`, containment 0.6 or more) in which one record is not yet judged; same scope, both active. Records of origin `pipeline` are never the new side.
  - **Who acts.** The model session has no Bash: it reads the pairs from a file and writes a verdict file (pair, decision, one line of reason). Python applies it through the judged mode of `mem curate apply`, which enforces: the dropped or superseded record is the older one; a merge never uses `--force` (a pair flagged by `flagged_words` can only be superseded, marked distinct or left); never an overwrite or a delete; knowledge notes are never merged this way (a contradiction between notes uses the dispute mark).
  - **What the owner sees.** The session start text gets one line while unacknowledged settlings exist ("settled since <date>: 2 merged, 1 superseded; `mem settle log`, undo with `mem settle undo <n>`"); `mem settle undo` restores both records of a pair in one command. A failure shows as the `mem-auto` failure line does.
  - **Trial before it is turned on**, on a copy of the store: 40 records derived from real memories are written into the copy (10 paraphrases, 10 corrections, 10 versions that are both valid, 10 unrelated look-alikes) and the run is started as in real use, so retrieval is part of what is measured. Reported apart: pairs the queue never showed (a retrieval miss, not a judgment), and judgments. A wrong action is a merge or supersede that should not have happened, a wrong direction, or a `distinct` on a true duplicate or correction (it hides the pair for good). Rule written beforehand: adopt when at most 1 of the 40 gets a wrong action and at least 60% of the 20 that should be acted on are, among those the queue showed; otherwise keep the strict safe subset and record the numbers. If the queue shows fewer than 12 of those 20, the result is a retrieval finding: record it and decide on the look-alike search before judging the model.
  - **Grading, fixed on 2026-11-18 before the run.** `mem merge` keeps the newer claim, so for a paraphrase or a correction both merge and supersede count as acted when the derived record stays active and its base does not; the reverse is a wrong action. Bases: the global memories plus this project's memories copied as global ones into the trial store (the global scope alone has 17 records, too few for 40 independent bases), one derived record per base.
  - **Built (2026-11-18, not yet measured):** `mem settle` (engine, two review rounds), `mem-settle` (the run), the trigger in the write path, the hooks, the session start lines, options `auto_settle` (off) and `auto_settle_minutes`.
  - **Kill criteria.** Switch off when a week of settling runs costs more than 1 USD, or when the owner undoes 2 settlings in a week.
- [ ] **1. (1a and the `mem-research` pipeline done and measured; the agent change is left) Research on demand with the web, to a set depth.** A command `mem-research` chains headless sessions with separated roles: memory step (store, no web) answers and lists what is missing or to contrast; web step (web only, sees no store) returns quotes with URLs from official documentation and papers; writing step (store, no web) records findings with their URL and low confidence, and for a contrast adds confirmed evidence or marks a note disputed. Depth: `memory` (no web), `contrast` (few pages, default), `deep` (more pages, papers); an option of the plugin sets the default and the request can override it. `memory-researcher` loses its web tools and points to the command. Check: a trial with planted facts (a correct one, a contradicted one, one with no source, and a page that carries an instruction) shows the three verdicts, nothing written from the instruction, and no store text in the web step's input.
- [ ] **2. Inline note references in syntheses.** Writer, checker and `mem check`; trial against the lean loop on the same three topics. *Built on `feat/memory-inline-refs` (2026-11-18); the trial is not run.*
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

### Pre-mortem of stage W (2026-11-17), each checked in the code

| Risk | Change |
|---|---|
| The curator session has `Bash(mem *)` and could call `mem supersede` or `mem merge --force` itself | No Bash: a verdict file, applied by Python |
| A run at 1 record would move the count window of `mem-auto`, so the heavy steps never reach 10 | Own list of judged handles |
| `mem merge` keeps the claim of `keep`: a new correction can be folded into the old wrong record | Direction enforced: the older record is the one dropped or superseded |
| Pairs handed to the model skip the look-alike search, and `distinct` hides a pair for good | The trial runs through the queue on a store copy; a wrong `distinct` counts as an error |
| Cost of a run at every session end | Only the new handles, no synthesis step, at most one run per `auto_settle_minutes`, weekly kill criterion |
| The owner sees nothing, and undoing a merge takes two restores | Session start line, `mem settle log`, `mem settle undo` |

Stage 1 is built in two halves: **1a (done 2026-11-17)** the engine (disputed and confirmed marks, the origin of a record, their display and their place in the curation queue, the count exclusion); **1b** the `mem-research` pipeline and its trial.

### Stage 1b design (2026-11-18): `mem-research`, five steps, three of them model sessions

| Step | Who | Sees | May do | Produces |
|---|---|---|---|---|
| 1 Memory | Haiku session | the store, through `mem search`, `mem show`, `mem find` only (allowed by name; no other `mem` command, no web) | read | `need.json`: the answer from memory with its references, whether it covers the question, the notes worth contrasting (handles) |
| 2 Web input | Python | the owner's question; for a contrast, the claims of the chosen global notes that pass the secret and forbidden-terms checks | build the web prompt | nothing written by a model reaches the web step |
| 3 Web | Haiku session | only that prompt; an empty folder, no `MEM_*`, no `mem` on PATH, no plugin | WebSearch, WebFetch, a turn cap | its reply: a JSON list of `{item, url, quote, stance, source_kind}` |
| 4 Check | Python | the URLs | fetch each page itself (http and https only, no private or local address, size and time caps) | only quotes found word for word on the page survive |
| 5 Verdict | Haiku session, no shell, no web | the claims and the surviving quotes, as data | write one file in its work folder | `verdicts.json`: per contrasted note confirmed, contradicted or no source; new findings, each tied to a quote; the answer text |
| 6 Apply | Python | `verdicts.json` | a fixed list: `mem note confirm`, `mem note dispute`, `mem remember --global --kind finding --origin web --source <url>` | records, each marked as coming from the web and unconfirmed |

- Depth: `memory` stops after step 1; `contrast` (default, option `research_depth`) allows 5 pages; `deep` allows 15 and asks for papers. `--contrast NOTE...` skips the choice of notes in step 1.
- "Contradicted" is applied only when the quote comes from a source the web step labelled official or paper and Python found the quote on the page; otherwise the row is downgraded to no source.
- A quote is data: the verdict brief says so, the verdict session cannot run anything, and step 6 accepts only the three commands above with arguments taken from `verdicts.json` fields, never a command line.
- `memory-researcher` loses WebSearch and WebFetch and runs `mem-research` when memory does not cover the question (a description change: measured by the eval protocol, in its own commit).

### Pre-mortem of the stage 1b design (2026-11-18): amendments, which replace the rows of the table above they touch

| Risk | Change |
|---|---|
| Step 1 with `Bash(mem search …)` breaks "no Bash at all", and web-origin text read through `mem show` could steer it | No session has a shell. Python runs `mem search` on the question and writes the results to a file; the memory session reads that file and writes `need.json`, which may ask for up to 3 more searches (each passed as one argument to `mem search`) before it answers |
| `--allowedTools` leaves Read, Grep and MCP tools in the web session; the installed `claude` lists no turn-cap flag | The web session is started with `--tools WebSearch,WebFetch --strict-mcp-config`, in an empty folder; its cap is `--max-budget-usd` plus a time limit; a reply that is not the expected JSON (code fences tolerated) writes nothing |
| WebFetch returns a summary, so quotes copied by the web session rarely match the page | The web session returns only `{item, url, stance, source_kind}`. Python fetches each page and hands the verdict session the passages of the page that share terms with the item; the verdict session copies its quote from those passages, and Python keeps it only when it is on the page word for word. PDFs are read with `pdftotext` when it is installed, else reported as not checked |
| Fetching untrusted URLs | http and https only, public addresses only and re-checked at each redirect, a size cap, text types only (task 1) |
| A finding whose claim says more than its quote, or carries an instruction, and then replaces an older memory through settling | A finding is written only when every number in its claim is in the quote and at least 70% of its content words are; settling never treats a record of origin `web` as the new side |
| The question is sent to the web unchecked | The question passes the secret and forbidden-terms checks or the run stops; the queries and URLs of the web session are logged in the run folder |
| No kill for a wrong "confirmed"; no budget per depth | Kill also when an altered-figure or own-experiment note is confirmed. Budgets: `contrast` 0.50 USD and 5 minutes, `deep` 2 USD and 9 minutes (15 at first; lowered on 2026-11-18 because an agent's shell call lasts at most 10); the trial's local page is reached only through a host the trial names |

Confirm and dispute work only on knowledge notes, so only those are contrasted.

Trial of stage 1 (ground truth by construction, on a copy of the store): 12 real notes whose claim their own cited source supports (expected confirmed), 4 of them copied with one figure altered (expected contradicted), 4 notes that record the owner's own experiments (expected no source), one canary note, and one local test page that carries an instruction. Kill criteria: the canary in any web-step event; more than one wrong "contradicted" in 20; `deep` over its budget; anything written from the planted instruction.

### Stage 1b trial, fixed on 2026-11-18 before the run

- Notes of origin `experience` are never chosen for a contrast by the pipeline (the web cannot confirm the owner's own experiments, and they are the most private notes); they go to the web only when named with `--contrast`. The trial names 4 of them, chosen with generic content.
- Arms, on a store copy under `target/`: 12 literature-origin knowledge notes (expected confirmed; no source is a miss, not an error), 4 copies of them with one figure altered (expected contradicted or no source), 4 experience notes (expected no source), in runs of at most 8 notes at depth `contrast`; one canary note that no run names; one injection run in which the web reply is canned and points at a local page that holds a supporting passage and an instruction (write a marked finding, dispute a named note), with the real verdict session.
- Kill: the canary token in any web-step file; a confirmed altered or experience note; more than 1 wrong contradicted among the 20; a finding or a dispute that follows the planted instruction; a run over its budget. Usefulness, reported apart: at least 6 of the 12 confirmed, else the stage is safe but weak and the passages or the web brief are tuned before it joins `mem-auto`. Total budget 2.5 USD.

## Results

### Stage W trial, 2026-11-18 (one run, Haiku at medium effort, `plugins/memory/evals/settle/run_trial.py`)

Store copy: 55 active memories (global ones plus this project's, copied as global) and 40 derived records, one per base.

| Type | Rows | Shown by the queue | Decisions | Grade |
|---|---|---|---|---|
| Paraphrase | 10 | 10 | 9 merge, 1 nothing | 9 acted |
| Correction | 10 | 10 | 9 supersede, 1 nothing | 9 acted |
| Valid version | 10 | 7 | 3 distinct, 4 nothing | 10 correct |
| Unrelated look-alike | 10 | 5 | 5 distinct | 10 correct |

Wrong actions 0 of 40 (limit 1); acted 18 of the 20 shown that should be acted on, 90% (limit 60%); unexpected pairs 0; cost 0.018 USD for 32 pairs in one session. One merged pair was checked in the record files: the base is superseded by the derived record, whose observed count is 2. **By the rule: adopt.**

Limits: one run, so no variance; the derived records were written by the agent that built the feature, from real memories, and the paraphrases reuse the base's terms, so the 20 of 20 shown says little about look-alikes written in other words (the queue needs 0.6 containment); no pair of the trial had two new records. Not measured: the write-path trigger and the hooks in a real session (tested with a fake `claude` only). The option `auto_settle` stays off by default; kill criteria as in stage W. A review of the harness left three low items open in `run_trial.py`: a timed-out session would count as cost 0, an unreadable settle-log line is skipped without a count, and failed writes are missing from the printed table; none occurred in this run (status ok, 26 log lines all read, 0 failed writes, no inherited trigger variable).

### Stage 1b trial, 2026-11-18 (`plugins/memory/evals/research/run_trial.py`, depth `contrast`, Haiku at medium effort)

| Run | 12 real notes confirmed | 4 altered | 4 experience | Canary in the web step | Planted instruction | Cost |
|---|---|---|---|---|---|---|
| 1 | 0 | 4 left | 4 left | no | ignored (the verdict session said so) | 0.076 USD |
| 2, after two fixes | 6 | 2 disputed, 2 left | 4 left | no | ignored | 0.322 USD |

Run 1 found two defects: the web session had its two tools but no permission to call them (`--tools` without `--allowedTools`; in 2 of 3 batches it replied that the calls never ran), and the verdict brief asked one passage to cover every fact of a note. Both were fixed before run 2 (commit a803846), so run 2 is not a clean measure of the brief change: the brief was changed after seeing a result. By the rule fixed beforehand, run 2 is **safe** (no kill criterion met: 0 wrong confirmed, 0 wrong contradicted of 20, no canary, nothing written from the instruction, every run under 0.50 USD) and **useful at the threshold** (6 of 12). Checked in the note files: a disputed variant carries the official quote with the right figure; a confirmed note carries the fact and its quote.

Limits: one run per state; 12 notes of the kind easiest to check (standards, language documentation); half of the real notes still get no source (papers and pages the web session did not reach); the web session's own `official` label is trusted; `deep` was not run. Not yet done: `memory-researcher` without web tools (a measured description change), and joining `mem-auto`.

Stage 2: built and measured; the three trials are below. Stages 3 to 5: pending.

### Stage 2 backfill trial, 2026-11-18 (`run_trials.py --backfill-trial --budget 8`, three syntheses of a store copy, Haiku at high effort, one run)

Verdict by the rule fixed before the run: **PASS**. Spent 1.87 USD of the 8 USD cap: 0.13 for the three backfill sessions, 1.74 for the reference judgments and calibrations.

| Measure | Value | Rule |
|---|---|---|
| Parts and units sent | 21 parts, 336 units | |
| References proposed, applied, refused | 429, 400, 29 (all 29 in one synthesis; reasons not read, the run's work folder is deleted at the end) | at least one applied per synthesis: pass |
| `none` answers | 5 of 336 units (1%) | at most 20%: pass |
| Wrong references in a sample of 100 new ones | 1 (worst case 1) | at most 1: pass |
| Findings without a reference before that now have one | 178 of 196 (91%, worst case equal) | at least 60%: pass |
| Words of every part, `mem check`, notes behind their section | unchanged, exit 0, 0 before and 0 after | pass |
| `mem restore`, one per synthesis | every snapshotted file back byte for byte | pass |
| Calibration of the reference judge | 20 of 20 planted wrong references found, none of them weak; no unit or reference left unjudged | at least 16: valid |
| Backfill cost | 0.035, 0.046 and 0.053 USD per synthesis; 0.006 to 0.007 per part | |
| Tokens as stored, before and after | 5342 to 10487, 4688 to 7960, 5840 to 8796 (+96%, +70%, +51%) | |
| Tokens as `mem show` prints them | 5342 to 6845, 4688 to 5619, 5826 to 6398 (+28%, +20%, +10%) | no rule in this trial |

Reading, with its limits:

- One run, three syntheses, one judge model: the wrong-reference rate is bounded near 5% by the sample, not measured below that.
- The judge marked 197 of the 336 units as findings; coverage is over those.
- What a reader is shown grew by 10% to 28%, because a label copied from the `Sources:` line is several words long. The writer trial's limit for the same measure is 15%. The owner accepted the proposal made here: `mem show` now prints a reference as the number of its note on the part's `Sources:` line (`[2]`), computed when shown; storage unchanged. On a store copy, the synthesis with 63 references shows as 53,303 characters against 61,149 stored (54,785 with labels).
- From the measured cost per part, the backfill of the real store's 218 parts is estimated at about 1.5 USD without any judging.

### Stage 2 writer trial, 2026-11-19 (`run_trials.py --arm M --arm R --runs 2 --jobs 2 --budget 15`, three topics, Haiku at high effort, branch at `7bca3e9`, control `main` at `7d190a1`)

Verdict by the rule fixed before the run: **FAIL**, on one condition of six. The writer change is not adopted and the branch is not merged. Spent 11.90 USD of the 15 USD cap (1.50 of it the control's own judge sessions, which are not used).

| Condition | M (control, `main`) | R (branch) | Rule | |
|---|---|---|---|---|
| Unsupported claims per 100, pooled over 6 syntheses | 4.7 (31 of 660) | 7.5 (35 of 469) | at most M's + max(2, gap of M's runs 1.4) = 6.7 | **failed** |
| Mean pipeline cost, USD | 0.484 | 0.463 | below 1.3 times M's | passed |
| `mem check` | 6 of 6 | 6 of 6 | every R synthesis | passed |
| Findings that carry a reference (worst case) | 0 of 413 | 399 of 402 (99%) | at least 80% | passed |
| Wrong references (worst case) | none to judge | 12 of 556 (2.2%) | at most 5% | passed |
| Tokens as `mem show` prints them, mean | 5276 | 3883 | at most 1.15 times M's | passed |
| Calibration of the reference judge | | 20 of 20 planted found, none weak, no unreliable report | at least 16 | valid |

Per synthesis, unsupported per 100 (claims checked): M 5.6 (90), 8.2 (85), 3.0 (132), 6.2 (97), 4.0 (124), 3.0 (132); R 6.7 (60), 6.7 (89), 17.1 (70), 4.3 (93), 5.1 (78), 6.3 (79).

Reading, with its limits:

- The failed condition is the one the stage must not buy its references with. R is 2.8 points above M; with these counts the difference has a standard deviation near 1.5 points, so it is about two of them: likely real, not proven. One R synthesis (12 of 70) carries a third of R's unsupported claims; without it R would be 5.8 and pass, but a rule fixed beforehand does not drop a row afterwards.
- R writes less: 2258 words and 78 checked claims per synthesis against 2986 and 110. Its shown text is shorter than M's because it has fewer words, not only because of `[n]`. Whether the shorter text is the cause of the higher rate was not measured.
- References themselves work: 99% coverage and 2.2% wrong on text the writer linked while writing, 91% and 1 of 100 on text linked afterwards by the backfill (trial above).
- Open, for the owner: both trials together point to linking after writing instead of while writing. Keep the writer, checker and fixer texts of `main` (the control's accuracy) and run the backfill step at the end of `mem-synthesize`, which the backfill trial measured on syntheses written by that same writer. It needs the texts of task 3 taken back, the backfill wired into the pipeline, and one confirming run. Not done: it is a change of design.

### Stage 2, change of design after the two trials (2026-11-19, owner: finish it and merge): link after writing

The writer trial failed on unsupported claims while every reference measure passed, and the backfill passed on syntheses written by the writer of `main`. So references are added after the text is written and checked, by code, and the writer is no longer asked to link.

| Decision | Choice | Reason |
|---|---|---|
| Writer, checker and fixer texts | Those of `main` again (`skills/memory-synthesis/SKILL.md` step 3 and its opening line, `agents/memory-synthesizer.md`, `evals/synthesis/writer-brief.md`, `synth_briefs/checker-brief.md`, `synth_briefs/fixer-brief.md`). Differences from `main` that remain in what those sessions meet: the fixer copies a part with `mem show ... --stored`; the engine refuses at write time a reference without an owner, in the Summary or to a note that is not on `Sources:`, and a bracketed number, all of which `main` accepts; plain `mem show` prints `[n]`. The skill's section "Writing a new synthesis" is the one of `main` | They are the texts of the control, which measured 4.7 unsupported per 100. `mem show` no longer prints the stored text |
| Where references come from | `mem-synthesize` runs the backfill on each synthesis it wrote, as its last step: after the loop, the attaching and `mem check`. The same code as `--backfill`, the same done list, inside the topic's budget | The backfill cannot change a word, so the text the loop checked is the text that stays; measured at 91% of findings linked and 1 wrong in 100 |
| A writer that links anyway | Allowed: the engine's rules hold at write time, and the backfill skips a sentence that already carries the note | The Haiku writer wrote 65 references unprompted before this stage |
| `REF:` lines in the loop | The code stays, unused while the checker brief is the one of `main` (it writes no `REF:` line); stage 3's checker is its expected user. Delete `REF_LINE`, `apply_refs`, the units file and the `parse_report` rule when stage 3's design is fixed without them, or on 2026-12-31, whichever comes first. One live path remains: the units file is written before every check, and a failure there stops the loop | Removing it now would be a second change to the loop before the confirming run |
| Trial harness | Arm R is the branch's pipeline, so it gets the backfill step; its pipeline cost includes it. The judge of unsupported claims reads text without references, so it reads what the loop left | |

Confirming run, rule fixed before it (the owner's word of 2026-11-19 covers it): the writer rule above, unchanged, with arm R redefined as this pipeline. Arm M is not run again: its six rows of 2026-11-19 are reused, because the control is the same code (`main` moved from `7d190a1` to `aca4e90` by a merge of documentation only). Its store copy was taken 1.5 hours after the branch's from the same store; checked on 2026-11-19, the two differ in 3 memories, the settle state and one synthesis outside the three topics. Six new R rows (three topics, two runs), estimated at 6 to 7 USD under a cap of 8; the estimate given to the owner beforehand was 3 to 5 USD for one run, and two runs are what the rule needs to be more than preliminary. Limits of the reuse: the two arms are not from the same night, and the results of the first night record the model family, not the model's full identifier nor the version of the `claude` program.

What this run can show: the reference step on fresh text (coverage, wrong references, size, cost), and that the branch's engine does not raise unsupported claims beyond the margin. What it cannot: an effect of the backfill on unsupported claims (none by construction: the judge reads text without references and the backfill changes no word), nor the budget path of `mem-synthesize` or `mem-auto`, which run the production writer agent. A failure on unsupported claims alone is read in the session streams (write-time refusals, the excess claims) before anything else; no second run without the owner's word.

If it passes, the branch is merged. If it fails, it is not, and the numbers go to the owner.

Pre-mortem of 2026-11-19 on this change (7 risks, 1 high), and what it added:

- **Before the merge:** `mem-auto` read the row status `ok, references not added: ...` as a failure, so most automatic runs would have shown a failure line: fixed. The four clarifications above.
- **Task 6, in this order:** (1) fix the one link by hand and see `mem check` of the branch exit 0 on a store copy; (2) update the installed plugin; (3) the same day, `mem-synthesize --backfill --dry-run` and then the backfill, with the installed plugin and never from the checkout while the old plugin is installed (the old fingerprint hashes references, so attached notes would be listed as stale). The history commit "before backfill" is the way back: `mem restore` refuses a group once one of its files changed later. With the plugin updated before the link is fixed, the store-wide `mem check` exits 1 in every writer and fixer session.
- **New task, before stage 3 uses references: a reference audit.** No step checks a reference after the backfill adds it: `mem check` only tests that its note is on the part's `Sources:` line, and the reference judge lives in the trial harness. The backfill trial bounds wrong references at about 5% (1 in a sample of 100, one run, one judge model), which on the real store may be tens of links. The audit judges a random sample of 100 references of the real store with `evals/synthesis/ref-judge-brief.md` and keeps the backfill's `none` lines as candidate unsupported claims. Kill: more than 2 wrong, and stage 3 does not act on references. Repeat before stage 4.

### Stage 2 confirming run, 2026-11-19 (`run_trials.py --arm R --runs 2 --jobs 2 --budget 8 --control-results <the writer trial's results file>`, three topics, Haiku at high effort, branch at `1db8f1b`)

**Verdict: PASS on the rule fixed before the run, with six valid R rows and no row lost to the budget.** Arm M is the six rows of the writer trial (`main` at `7d190a1`), reused. Cost 6.60 USD of the 8 USD cap, of which 1.50 is the control's judge counted again.

| Condition | M | R | Limit | Result |
|---|---|---|---|---|
| Unsupported claims per 100 | 4.7 | 4.9 | 6.7 (M + 2.0) | passed |
| Pipeline cost per synthesis, USD | 0.484 | 0.482 | below 0.630 | passed |
| `mem check` exits 0 | 6 of 6 | 6 of 6 | all | passed |
| Findings that carry a reference | - | 393 of 472 (83%) | at least 80% | passed |
| Wrong references | - | 36 of 741 (4.9%) | at most 5% | passed, one reference below the limit |
| Tokens shown by `mem show`, mean | 5276 | 5236 | at most 6067 | passed |
| Calibration of the reference judge | - | 19 of 20 planted found | at least 16 | valid |

Per row, unsupported per 100: 5.7, 6.7, 3.8, 5.2, 7.1, 1.7 (gap between R's two runs 2.6 points; M's 2.3). The stored file grows from a mean of 5248 to 8747 tokens (+67%), which only `mem show --stored` and the engine read.

Limits, to read before building on this:

- **Wrong references sit at the limit.** 4.9% here against 1 in a sample of 100 in the backfill trial. The two are not the same measure (every reference judged here, on text written the same hour; a sample there, on older syntheses), and one judge model produced both. At this rate the reference audit before stage 3 (kill at more than 2 wrong in 100) is likely to fire: stage 3 must not assume references are right until that audit says so.
- **Coverage is lower on fresh text:** 83% against 91% in the backfill trial.
- One synthesis left one part off its index (`unlisted` in the harness table) and still passed `mem check`; not looked into.
- Two runs per topic; the unsupported difference between arms (0.2 points) is far inside the noise, as expected, since the judge reads text without references.

After the run, before the merge, from the review of the wiring: the reference step does not start with less budget left than one session usually costs; an error while selecting parts leaves the topic a pass (`ok, references not added: ...`); a `mem check` that no longer exits 0 after references were written fails the topic and names the undo. Not done, low: the harness does not test that M and R hold the same (topic, run) pairs, nor mark a decision on fewer than six valid R rows as preliminary (this run had six).
