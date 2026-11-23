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
- Modify: `plugins/memory/hooks/session-index.sh`, `plugins/memory/.claude-plugin/plugin.json` (the `userConfig` key `rules_layout`, a string, default `flat`, described in one sentence in the style of `research_depth`; the version is not changed)
- Test: `plugins/memory/engine/tests/test_rules.py`, `plugins/memory/engine/tests/test_rules_session.py`

**Interfaces:**
- Produces:
  - `rules.LAYOUTS = ("flat", "grouped")`.
  - `rules.grouped(choice: Choice) -> list[str]`: for the lessons of `choice.loaded`, in their order: the topics in the order of first appearance, lessons without a topic collected under `other` and placed last; per topic the line `<topic>:` followed by its lessons' lines, each exactly `rules.line(m)`.
  - `rules.block(choice, layout: str = "flat") -> list[str]`: `[HEADER, *lines]` as today for `flat`; `[HEADER, *grouped(choice)]` for `grouped`; `[]` when nothing loads; any other value behaves as `flat`.
  - `mem rules --layout {flat,grouped}`: prints that layout; without the flag, the layout named by the environment variable `MEM_RULES_LAYOUT`, else `flat`.
  - `session_index` uses `MEM_RULES_LAYOUT` in the same way. `hooks/session-index.sh` sets `MEM_RULES_LAYOUT` from `CLAUDE_PLUGIN_OPTION_RULES_LAYOUT` when that is `grouped`, beside the line that sets `MEM_LOADED_RULES`.
  - The count of characters kept in the session start statistics (`rules_chars`) is that of the lines printed, headings included.

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the two test files, then the whole suite, then `python3 scripts/validate.py` and `claude plugin validate .`**

- [ ] **Step 5: Commit**

```bash
git add plugins/memory
git commit -m "feat(memory): the loaded lessons can be printed under their topic (option rules_layout)"
```

---

### Task 2: The measure, and the documents (C84)

**Files:**
- Create: `plugins/memory/evals/rules_layout/run_trial.py` (the runner) and `plugins/memory/evals/rules_layout/README.md` (how to run it, what it costs)
- Modify: `plugins/memory/README.md`, `plugins/memory/CHANGELOG.md` (under `## [Unreleased]`), `docs/superpowers/plans/2026-11-17-memory-plugin.md` ("Current state and where to resume")
- Modify: this file (`## Results`)

**The protocol** (from "Measurement: loaded rules are followed (2026-11-22)" in [the handoff](2026-11-22-memory-loaded-rules-and-reminders.md); read that section first):

- A fresh git project in a temporary directory with `greet.py` printing a misspelled greeting, a `check.sh` the README does not mention, and a session start hook that prints a rules file. Nothing of the plugin is loaded and no user instruction file is read (read `plugins/memory/evals/trial_env.py` and the other runners under `plugins/memory/evals/` for how a headless trial is isolated here; reuse it).
- The prompt, the same in every run: "greet.py prints a misspelled greeting. Fix it and commit the change."
- The rules file is produced by the engine itself: 16 lessons written into a temporary store, three of which leave a trace (run `./check.sh` before reporting and quote its last line; start the commit message with a type prefix; add a line to `NOTES.md`), each of the three under a different topic and none ranked first; the 13 others are unrelated lessons spread over four more topics. Condition F prints `mem rules --layout flat`, condition G `mem rules --layout grouped`, from the same store.
- Model: Sonnet, headless. Three runs a condition. A cap on the cost of the whole trial of 1.00 USD: stop when it is reached.
- Scored from the trace of each run, by code: `check.sh` was run and its last line appears in the reply; the last commit message starts with a type prefix (`fix:`, `feat:`, `docs:`, `chore:` or with a scope); `NOTES.md` has a new line.

- [ ] **Step 1: Write the runner**

`run_trial.py --runs 3 --max-cost-usd 1.00 --out <folder>` builds the project and the store, runs both conditions, and writes one JSON line per run (condition, the three scores, cost, the path of the saved trace) and a summary table. `--dry-run` builds everything and prints the two rules blocks without calling a model.

- [ ] **Step 2: Check it without a model**

Run: `python3 plugins/memory/evals/rules_layout/run_trial.py --dry-run --out <tmp>`
Expected: two blocks with the same 16 lessons, the second with seven headings; the three rules that leave a trace are in both and not first.

- [ ] **Step 3: Run the trial**

Run it once with a real `claude`. The traces stay in the temporary folder; headless trials leave folders under the user's Claude projects directory that belong to the temporary project: remove those afterwards and say how many were removed.

- [ ] **Step 4: Record the figures**

In `## Results`: the table of the six runs, the mean cost per condition, and the outcome of C84's rule (grouped is adopted only if it follows the three rules in as many runs as flat). The default stays `flat` either way: the change of default is the owner's.

- [ ] **Step 5: Write the documents**

README: the option and the two layouts, with the result of the measure and its limits (one task, one model, three runs). Changelog: one line for users. The resume section: where both plans of 2026-11-23 stand.

- [ ] **Step 6: Run `python3 scripts/validate.py`, `claude plugin validate .`, `python3 scripts/port.py --check`**

- [ ] **Step 7: Commit**

```bash
git add plugins/memory docs
git commit -m "docs(memory): the grouped block measured against the flat one, and where it stands"
```

---

## Results

Filled by Task 2.
