# Rules block grouped by topic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The lessons that load at session start can be printed under their topic; the choice of lessons and their texts do not change, and the flat block stays the default until a measure says the grouped one is followed as well.

**Architecture:** `rules.choose` is untouched; `rules.block` gains a layout argument and a function lays the chosen lessons out by topic. The layout reaches the session start hook as a plugin option turned into an environment variable, as the loaded-rules switch does; `mem rules --layout` shows either.

**Tech Stack:** Python 3 standard library, pytest, the plugin's shell hooks.

**Spec:** [the design](../specs/2026-11-23-memory-reword-and-grouping-design.md), Part 2, rows C81 to C85. Read it before any task.

## Global Constraints

- Branch `feat/memory-reword-and-grouping`; one local commit per task; no push, no pull request, no merge.
- With the option unset or `flat`, the session start text and `mem rules` are byte-identical to 0.7.0.
- `rules.choose`, `RULES_MAX`, `RULES_LIMIT`, the ranking and the short forms are not changed. Both layouts print the same lessons.
- No home path, private repository name, client name or note title in code, tests or docs.
- The whole suite, once at the end of each task: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q` (about five minutes; foreground, timeout 600 s).

## Review Focus

| Input or condition | Expected | Pinned in |
|---|---|---|
| An unknown value of the option or of `--layout` | The flat block (the option) or a usage error (the flag) | Task 1 |
| No lesson loads | No heading at all; the text of today | Task 1 |
| Every lesson has the same topic, or none has one | One heading, `<topic>:` or `other:` | Task 1 |
| The loaded rules are switched off | Nothing of the block is printed, in either layout | Task 1 |

---

### Task 1: The grouped layout (C81, C82, C83)

**Files:**
- Modify: `plugins/memory/engine/rules.py` (`block`, one new function)
- Modify: `plugins/memory/engine/mem.py` (`session_index`, `cmd_rules` and its parser)
- Modify: `plugins/memory/hooks/session-index.sh`, `plugins/memory/hooks/session-env.sh` (it exports the variables a `mem` command typed in a session sees: export `MEM_RULES_LAYOUT` there too, so `mem rules` and the session start agree), `plugins/memory/.claude-plugin/plugin.json` (the `userConfig` key `rules_layout`, a string, default `flat`, described in one sentence in the style of `research_depth`; the version is not changed)
- Test: `plugins/memory/engine/tests/test_rules.py`, `plugins/memory/engine/tests/test_rules_session.py`

**Interfaces:**
- Produces:
  - `rules.LAYOUTS = ("flat", "grouped")`.
  - `rules.grouped(choice: Choice) -> list[str]`: for the lessons of `choice.loaded`, in their order: the topics in the order of first appearance, lessons without a topic collected under `other` and placed last; per topic the line `<topic>:` followed by its lessons' lines, each exactly `rules.line(m)`.
  - `rules.block(choice, layout: str = "flat") -> list[str]`: `[HEADER, *lines]` as today for `flat`; `[HEADER, *grouped(choice)]` for `grouped`; `[]` when nothing loads; any other value behaves as `flat`.
  - `mem rules --layout {flat,grouped}`: prints that layout; without the flag, the layout named by the environment variable `MEM_RULES_LAYOUT`, else `flat`.
  - `session_index` uses `MEM_RULES_LAYOUT` in the same way. `hooks/session-index.sh` sets `MEM_RULES_LAYOUT` from `CLAUDE_PLUGIN_OPTION_RULES_LAYOUT` when that is `grouped`, beside the line that sets `MEM_LOADED_RULES`.
  - The count of characters kept in the session start statistics (`rules_chars`) is that of the lines printed, headings included.

- [x] **Step 1: Write the failing tests**

| Test | Asserts |
|---|---|
| `test_grouped_puts_lessons_under_their_topic_in_rank_order` | lessons ranked a (testing), b (shell), c (testing), d (no topic), e (shell): `testing:`, a, c, `shell:`, b, e, `other:`, d |
| `test_grouped_and_flat_print_the_same_lessons` | the set of lines that start with `- ` is equal in both |
| `test_flat_is_unchanged` | `block(choice)` and `block(choice, "flat")` equal the list of today; an unknown layout too |
| `test_no_heading_when_nothing_loads` | `block(Choice(), "grouped") == []` |
| `test_rules_command_takes_the_layout` | `mem rules --layout grouped` prints the headings; `--layout wrong` exits 2; `MEM_RULES_LAYOUT=grouped mem rules` prints the grouped block and `--layout flat` overrides it |
| `test_session_start_uses_the_layout_variable` | with `MEM_RULES_LAYOUT=grouped` the session start text holds the headings; without it the text equals that of 0.7.0 for the same store |
| `test_rules_off_prints_no_block_in_either_layout` | as the existing test of the switch, with the variable set |
| `test_plugin_json_has_the_layout_option` | the key exists with default `flat` |
| `test_the_hook_passes_the_layout` | `hooks/session-index.sh` run as the existing hook test for the loaded-rules switch runs it (`test_rules_session.py`), with `CLAUDE_PLUGIN_OPTION_RULES_LAYOUT` set to `grouped`, `flat`, unset and `nonsense`: headings only for `grouped` |
| `test_a_lesson_whose_topic_is_other_shares_the_last_heading` | if `records.valid_topic` accepts the topic `other`, such a lesson and one without a topic sit under one `other:` heading; if it refuses it, the test asserts that refusal instead |

- [x] **Step 2: Run them and see them fail**

- [x] **Step 3: Implement**

- [x] **Step 4: Run the two test files, then the whole suite, then `python3 scripts/validate.py` and `claude plugin validate .`**

- [x] **Step 5: Commit**

```bash
git add plugins/memory
git commit -m "feat(memory): the loaded lessons can be printed under their topic (option rules_layout)"
```

---

### Task 2: The measure, and the documents (C84)

**Files:**
- Create: `plugins/memory/evals/rules_layout/run_trial.py` (the runner) and `plugins/memory/evals/rules_layout/README.md` (how to run it, what it costs)
- Modify: `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md` (under `## [Unreleased]`), `docs/superpowers/plans/2026-11-17-memory-plugin.md` ("Current state and where to resume")
- Modify: this file (`## Results

**No figure is reported: both attempts stopped on void runs (2026-11-23).** Runner: `plugins/memory/evals/rules_layout/run_trial.py`. The layout is **not measured**; the default stays `flat`, and changing it is the owner's decision.

| Item | First attempt | Second attempt |
| --- | --- | --- |
| Tool list | `Read`, `Edit`, `Write`, `Bash(./check.sh)`, `Bash(git *)`, `Bash(python3 greet.py)` | Widened after the first attempt, because that list came from the pre-mortem and the flags of the 2026-11-22 measure were never recorded: the bounded list of the protocol above |
| Dry run, canary | Passed (token returned, no knowledge of `validate.py`, built-in plugins only) | Same |
| Runs | F1: 1 denial, void; stopped (the rule then stopped at the first void) | F1: void; F1 rerun: void; G1: void; stopped at the third void (more than two) |
| What was denied | One Bash call chaining a redirect, `>>`, `./check.sh` and `git commit` | Each time a compound command: `sed -i ... && echo ... >> NOTES.md && ./check.sh && git commit`, or `echo ... > greet.py && echo ... >> NOTES.md && ./check.sh`; the model chains the whole task into one call and a chain is denied when any part, or the redirect, is outside the list |
| Cost | about 0.12 USD | about 0.26 USD (canary and three runs) |
| Real folders | Global memories, `.memory/` and plugin state: checksums equal | Equal again |
| Left behind | 3 Claude projects folders, removed | 4 folders (canary and three runs), removed |

Per-rule scores of the void runs are not reported: a void run is not scored. In the three void runs of the second attempt the model did fix, quote `check.sh`, prefix and write the line, but only after a denial.

What it would take: either a list that lets a chain pass (a stricter match is not available, so `Bash(*)` inside the throwaway project, which the coordinator ruled out), or a prompt that asks for one command per call, which changes the task. Both are the owner's call.
