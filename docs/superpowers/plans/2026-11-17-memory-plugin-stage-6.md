# Memory plugin, stage 6 (signal) Implementation Plan

Status: done · merged in #117, 2026-11-17 · boxes left unticked during execution are not open work (checked 2026-11-19).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a subagent learns from its own brief that records related to its task exist, by name and without their content, so it can open them; nothing is added when nothing relates.

**Architecture:** a `PreToolUse` hook on the Agent tool runs `mem signal --hook`, which reads the brief from the hook's input, finds the records whose claim is largely contained in the brief, and returns the brief with one short block appended (`updatedInput`, with no permission decision). Matching is a containment score over words, computed in `records.py`; its thresholds are chosen on a labelled set kept in the repository, by a rule written before any run.

**Tech Stack:** Python 3.12, `uv`, Bash, `pytest`.

**Spec:** [../specs/2026-11-17-memory-plugin-design.md](../specs/2026-11-17-memory-plugin-design.md), section "The signal" (owner decision D12); stage 6 of [2026-11-17-memory-plugin.md](2026-11-17-memory-plugin.md). This stage runs before stage 5 at the owner's request.

## What changed since the design was written, and why

- The signal goes into subagent briefs only, not into the owner's prompt. Measured on 2026-11-17: with the three-line session index the main agent recalls unasked (8 of 8 trials), and the owner's prompts are in Spanish while the records are in English, so word matching on a prompt misses. Briefs are written by the agent in English.
- Tried on Claude Code 2.1.325: a `PreToolUse` hook on the Agent tool that returns `updatedInput` and no permission decision changes the brief the subagent receives, and leaves the permission flow alone.
- The match is measured from the record's side. A brief has hundreds of words and a claim about ten, so "half of the query's words" (the rule of `mem search` for memories) can never be met by a brief.

## Global Constraints

- Nothing outside `plugins/memory/` and `docs/` changes. Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (482 passed, 2 skipped before this stage).
- The hook never fails a tool call: on any error, on no match, with no store and no project, it prints nothing and exits 0, and the brief is left as it was. It never returns a permission decision.
- The appended block is at most 400 characters and holds handles and counts only, never the text of a record.
- Notes are matched on their file names only (a knowledge note's file name is its claim); no note is opened: the hook runs at every subagent dispatch.
- Only live memories are matched. A record already named in the brief (its handle appears there) is not signalled.
- The thresholds are constants in `records.py`, set from the labelled set by the rule in Task 2, and recorded with their figures in this file.
- Public repository: no home-directory path or private name. Commit after each task on `feat/memory-plugin`; do not push.

## Review Focus

1. A brief that is empty, not a string, or several thousand words long.
2. A memory whose claim has fewer than two words left after removing stop words: never signalled.
3. A brief that quotes a memory's handle: that memory is not signalled again.
4. Twenty matching memories: the block names three and counts the rest, within 400 characters.
5. The hook's input lacks `tool_input`, or `tool_name` is not `Agent`: nothing is printed.

---

### Task 1: Containment matching and the signal text

**Files:**
- Modify: `plugins/memory/engine/records.py`, `plugins/memory/engine/mem.py`
- Create: `plugins/memory/engine/tests/test_signal.py`

**Interfaces:**
- In `records.py`:
  - `STRONG = 0.75`, `POSSIBLE = 0.5` (provisional; Task 2 sets them), `MIN_TERMS = 2`.
  - `containment(claim_tokens: Iterable[str], text_tokens: Collection[str]) -> float`: the distinct claim tokens not in `STOPWORDS` are the terms; with fewer than `MIN_TERMS` terms the result is 0.0; otherwise the share of the terms that occur in `text_tokens`.
  - `Related = NamedTuple("Related", [("handle", str), ("kind", str), ("score", float)])` where `kind` is `"m"` or `"n"`.
  - `related_records(memories: Sequence[Memory], note_stems: Sequence[str], text: str, today: datetime.date, *, tokenize: Callable[[str], list[str]]) -> tuple[list[Related], list[Related]]`: the strong list (score at least `STRONG`) and the possible list (at least `POSSIBLE`, below `STRONG`), each ordered by score descending, then memories before notes, then handle. A live memory is scored on its claim; a note on its file stem with hyphens as spaces. A record whose handle occurs in `text` is left out.
- In `mem.py`:
  - `signal_text(strong: Sequence[Related], possible: Sequence[Related]) -> str`: `""` when `strong` is empty. Otherwise exactly:

    ```
    [memory] Records related to this task exist (not read yet): m:<h> m:<h> n:<h>
    S strong, P possibly related. Open one with: mem show <handle>. Project memories are files in .memory/.
    A memory (m:) is experience, not fact.
    ```

    with at most three handles on the first line, strong ones first, each prefixed `m:` or `n:`; S and P are the two list lengths. The third line appears only when a memory is among the handles shown.
  - Command `mem signal [--hook]`: without `--hook` it reads the text from standard input and prints the signal text (nothing when empty). With `--hook` it reads the hook's JSON, requires `tool_name` to be `Agent` and `tool_input.prompt` to be a non-empty string, finds the project from the input's `cwd`, and when the signal text is not empty prints one JSON object `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": <tool_input with the prompt followed by a blank line and the signal text>}}`. It appends `{"t", "hook": "signal", "ms", "strong", "possible"}` to the hook log. It never exits non-zero and writes nothing else.
  - Note stems come from file names only, with the same patterns the session index counts.

- [ ] **Step 1: Write the failing tests**: `containment` (all terms present 1.0; half; fewer than two terms 0.0; stop words ignored); `related_records` (bands, order, a refuted memory left out, a handle quoted in the text left out, a note matched by its stem); `signal_text` (empty without a strong match; three handles and the counts with twenty matches, under 400 characters; the third line only with a memory shown); the command with `--hook` (valid input gives JSON whose `updatedInput.prompt` starts with the original brief and ends with the signal text, other `tool_input` keys unchanged, no `permissionDecision` key anywhere; no match, a non-Agent tool, empty input and invalid JSON print nothing and return 0).
- [ ] **Step 2:** Run them. Expected: fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5:** Commit: `feat(memory): add the signal for subagent briefs`.

### Task 2: A labelled set and the thresholds

Written by the main conversation: it needs judgment about what "related" means.

**Rule, written before any run:** on the half of the set kept for testing, the strong band must name no unrelated record in at least 9 of 10 briefs that get a signal (precision at least 0.9 by brief), and must signal at least half of the briefs that have a related record. If no pair of thresholds meets both on the tuning half, the hook ships with the strictest pair that meets the first, and the second figure is recorded as a limit. If the first cannot be met, the hook does not ship.

- [ ] **Step 1:** `plugins/memory/evals/signal/set.json`: about 30 briefs written as a main agent writes them (goal, scope, decisions, checks), each with the handles that truly relate, over about 15 memories and 15 note stems, all synthetic. A third of the briefs relate to nothing.
- [ ] **Step 2:** `plugins/memory/evals/signal/score.py`: splits the set by alternating briefs, scores a grid of thresholds on the tuning half, prints both figures for each pair, then the chosen pair's figures on the test half.
- [ ] **Step 3:** Set `STRONG` and `POSSIBLE`; record the table here; add a test that the constants equal the recorded pair.
- [ ] **Step 4:** Commit: `test(memory): choose the signal thresholds on a labelled set`.

### Task 3: The hook

**Files:**
- Create: `plugins/memory/hooks/signal.sh`
- Modify: `plugins/memory/hooks/hooks.json`, `plugins/memory/engine/tests/test_plugin_shell.py`

- `signal.sh`: sets `MEM_STORE` and `MEM_MEMORIES` from the plugin options as `session-index.sh` does, runs `mem signal --hook` with standard input passed through and stderr discarded, exits 0 always.
- `hooks.json`: a `PreToolUse` group with the matcher `Agent`, timeout 10.

- [ ] **Step 1:** Failing tests: the script with a matching brief prints JSON with `updatedInput`; with no match, with `uv` missing, with empty input prints nothing; exit 0 each time; it is executable; `hooks.json` names it under `PreToolUse` with the matcher.
- [ ] **Step 2 to 4:** Run, implement, run the whole suite, `python3 scripts/validate.py`, `claude plugin validate plugins/memory`.
- [ ] **Step 5:** Commit: `feat(memory): signal related records in subagent briefs`.

### Task 4: Measurements

Run by the main conversation.

- [ ] **Step 1:** Time `signal.sh` ten times against a store of about 1,100 notes and a project with 10 memories. Expected: under 0.5 s.
- [ ] **Step 2:** Delegated recall, with and without the hook (a copy of the plugin without it): the recall trials' three positive cases, with the request telling the agent to hand the work to a subagent. A run passes when the answer carries the memory's fact. Two runs per case and arm.
- [ ] **Step 3:** One delegated task that relates to nothing. Expected: the brief is unchanged (the hook log shows zero strong matches).
- [ ] **Step 4:** Record the figures here; tick stage 6 in the stage plan.

## Results

### Thresholds (Task 2, 2026-11-17)

`plugins/memory/evals/signal/set.json`: 30 synthetic briefs (20 with a related record, 10 with none, several of those sharing generic words with the claims), 15 memories, 15 note stems; a fixed paragraph of brief boilerplate is added to each. `score.py` splits by alternating briefs.

| Strong threshold | Tuning half: signalled briefs naming only related records · briefs with a related record that got a signal | Test half |
|---|---|---|
| 0.4 | 10 of 11 · 10 of 10 | 10 of 10 · 10 of 10 |
| **0.5** | **10 of 10 · 10 of 10** | **9 of 9 · 9 of 10** |
| 0.6 | 5 of 5 · 5 of 10 | 5 of 5 · 5 of 10 |
| 0.75 (the provisional value) | 1 of 1 · 1 of 10 | 5 of 5 · 5 of 10 |

That choice (0.5) did not survive real data and is withdrawn. The pre-mortem simulated the matcher on the owner's own transcripts, and a second measurement confirmed it (2,254 distinct subagent briefs, median about 320 words; the briefs stay on the owner's machine, only figures are recorded here).

| What is matched | Rule | Briefs that would get a signal |
|---|---|---|
| Note names (about 1,100) | share of name words in the brief, 0.5 | 82% |
| Note names | the same, 0.75 | 35% |
| Knowledge note names only, words weighted by rarity, 0.85, two rare words | | 9% |
| The 15 synthetic memory claims (no real brief relates to them, so every signal is false) | share of claim words, 0.5 | 4.7% |
| The same | 0.6, numbers ignored | 0.3% (7 briefs) |
| The same | 0.75 | 0.0% |

On the labelled set, memories only, 0.6 with numbers ignored: every signalled brief names only related memories (8 of 8) and 8 of 15 briefs with a related memory get a signal.

## Amendments after the pre-mortem and the real-data measurement (2026-11-17)

These override the tasks above.

- **Memories only.** Notes are not signalled in this version: a note's name shares too many common words with a real brief. Signalling notes needs a meaning-based match and is left for a later stage. `related_records` keeps its `note_stems` parameter; `mem signal` passes an empty list.
- `STRONG = 0.6`, `POSSIBLE = 0.5`; a term that is only digits is not a term. The rule of Task 2 is met as: false signals on real briefs at most 1 in 100 (measured 0.3%), and at least half of the labelled briefs with a related memory signalled (8 of 15).
- The signal text becomes exactly:

  ```
  [memory] For information: memories related to this task exist (not read yet): m:<h> m:<h>
  S strong, P possibly related. Read one with: mem show m:<handle> (they are files in .memory/).
  They are experience, not fact: where one conflicts with this brief, the brief wins and you report the conflict.
  ```

  with at most three handles; all three lines always.
- `plugins/memory/hooks/subagent-start.sh`: the words `and your brief has no memory section` are removed, so a signal in the brief does not stop a subagent from searching.
- The hook log line of `signal` gains `subagent_type` and `words` (the brief's word count); it still holds no text and no handle.
- A record counts as already named when its handle occurs in the brief as a whole token, with or without the `m:` prefix. The skill tells the main agent to quote `m:<handle>` when a brief uses a memory.
- Kill criteria, read from the hook log after a week of use: the signal fires on more than 5% of briefs, or a subagent follows a memory against its brief: switch the hook off and re-plan.
- Not built: combining with another plugin's hook that also rewrites the brief (none is installed); a different block for subagents that cannot run shell commands (they can read `.memory/` files).

### Delegated trials (Task 4, 2026-11-17): the signal showed no gain and is not registered

`evals/recall/run_trials.py --delegate` tells the agent to hand the work to a subagent without consulting anything first; a run passes when the answer carries the memory's fact. Sonnet, two runs per case (three in the last row).

| Arm | Project pitfall | Project constraint | Global lesson | Unrelated (must not consult) | Total |
|---|---|---|---|---|---|
| With the signal hook | 2 of 2 | 2 of 2 | 0 of 2 | 2 of 2 | 6 of 8 |
| Without it | 2 of 2 | 2 of 2 | 1 of 2 | 2 of 2 | 7 of 8 |
| Without it, and the subagent's start text reworded to give its reason ("…are in a searchable memory, not in the files. Before you change or decide anything…") | 3 of 3 | not run | 3 of 3 | 3 of 3 | 9 of 9 |

Reading: where the brief already holds a memory's words, the subagent finds it without a signal; where it does not (the global lesson: the brief says "upgrade the library", the memory says which version corrupts exports), a word match cannot fire. The case was solved by the subagent searching, which the reworded start text brought about.

Decided from these figures: the reworded subagent text is adopted (441 characters). `mem signal` and `hooks/signal.sh` stay in the code with their tests, but the `PreToolUse` group is not registered in `hooks.json`. The hook's own figures: about 100 ms per call; 0.3% false signals on real briefs at the chosen threshold.

Open: a signal for notes or for paraphrased memories needs a match on meaning, not on words; the owner's idea of bands (strong, possible, tangential) waits for that. The "project constraint" case's key word also appears in the project's file, so that column does not separate the arms.
