# Repository tooling, shared text and model catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: planned, pre-mortem amendments applied · Date: 2026-11-25 · Branch: `feat/repo-tooling`, created from `docs/backlog` after this plan and `docs/backlog.md` are committed there (so both exist on the branch; no merge into `dev` is needed first)

**Goal:** Test and enforce the commit gate (review Q1, Q2, Q3), apply its rules to every plugin from one rule table (A9, A10), give repeated prompt text one source (B9–B12), and derive the Codex model mapping from a vendor model catalog.

**Architecture:** A stdlib-only package `scripts/promptkit/` holds two reusable tools: `fragments` renders marked blocks in Markdown files from `shared/fragments/<id>.md` (one source per shared text; `--check` fails on drift), and `models` loads `shared/models.toml` (per vendor: level on a common scale, cost relative within the vendor) and derives cross-vendor (model, effort) pairs. `validate.py` owns one agent-rule table that `port.py` imports. Claude files stay complete and editable in place, because installed plugins read the committed files.

**Tech Stack:** Python 3.11+ standard library (`tomllib`); tests with `uv run --with pytest pytest scripts/tests -q`.

**Spec:** [project review 2026-11-24](../../studies/2026-11-24-project-review.md) (IDs Q1, Q2, Q3, A9, A10, B9–B12) and the owner rulings of 2026-11-25 below.

## Owner rulings (2026-11-25)

| Ruling | Consequence |
|---|---|
| One source of truth wherever possible; marketplace clean, correct, extensible; general tools reusable | Shared text and model data live in `shared/`; the tools in `scripts/promptkit/` take paths as arguments, nothing plugin-specific inside |
| Design delegated to the main session | Marked blocks, not template sources (every agent would exist twice and outputs invite hand edits); model wildcards resolved through the catalog's levels, Claude aliases stay the keys |
| Effort: never `max`; `xhigh` at most, preferably avoided: the next model at `low` beats the previous model at `xhigh` | Derivation policy: target effort `max` is never chosen; `xhigh` only on a vendor's top model |
| Costs compared only within a vendor (memory, 2026-11-19) | `cost` is relative inside each vendor (cheapest = 1); no cross-vendor cost column |
| Q3: opt-in local `pre-push` hook, no CI (review decision 2, 2026-11-24) | `git config core.hooksPath scripts/hooks` is the opt-in |
| Main session, 2026-11-25, after the pre-mortem: the description person rule ignores text inside double quotes | Quoted user phrases ("what do we know about X") are trigger terms, not the description speaking; owner informed, not asked (routine) |

## Pre-mortem findings that shaped this plan (2026-11-25, verified)

- The six-part brief is written out in `user-config/offload-policy.md`, which `*-with-policy` evals embed verbatim and `cloud-setup.sh` and the README prompt block copy raw: no markers go into `user-config/*.md`.
- `port.py --check` rebuilds expected text in `expected_text`, independent of `transform`: every transform change is made in both.
- With Codex levels 1–4, 12 of 20 cells change and most agent cells gain one effort step; best-fit levels luna 1.25, terra 2.25, sol 3.25, astra 4.0 keep every cell an agent uses.
- Two memory descriptions quote user phrases with "we", which the person rule flags.

## Global Constraints

- `scripts/*.py` and `scripts/promptkit/` use the standard library only; only tests may use pytest.
- Files under `ports/**`, the marketplaces of other tools and `user-config/*.{copilot,codex}.md` are generated: change them only by running `python3 scripts/port.py`.
- No skill or agent `description` changes in this plan (eval protocol, CLAUDE.md). Bodies change only as Task 6 says.
- Every change under `plugins/<name>/`, `ports/`, `user-config/`, except a pure refactor, adds a line under `## [Unreleased]` in that plugin's `CHANGELOG.md`.
- Never store line numbers in repository text (ADR 0014).
- English in code, comments, docs and commits; pull request to `dev`.
- Done for every task: `python3 scripts/validate.py` prints `OK`, and `uv run --with pytest pytest scripts/tests -q` passes.

## Review Focus

1. A hand edit inside a rendered block: `fragments --check` names the file and the fragment id (Task 5 test `test_check_reports_hand_edit`).
2. Marker syntax shown inside a fenced code example (prompt-engineering references may show it): not treated as a block (Task 5 test `test_markers_in_code_fence_ignored`).
3. Rules scoped to `agent-skills` (workers, offload rows, README catalog, a command per agent) must not fire on the `memory` plugin (Task 4 test `test_memory_agent_without_command_passes`).
4. A source pair above every target pair (`fable`, `max`) resolves to the top allowed pair, never to nothing (Task 7 test `test_above_all_maps_to_top_allowed`).
5. The hook on a machine without `uv` or `claude`: it prints which check it skipped and still runs the rest (Task 9 test `test_hook_skips_missing_tools`).
6. A shared line edited outside any block, or a block whose markers were deleted: reported (Task 5 test `test_shared_text_outside_block_reported`).
7. A later `models.toml` edit that silently remaps cells: `load_catalog` enforces rising levels and next-low > previous-xhigh; the generated `docs/ports.md` table shows the change in the diff (Task 7, Task 9 CLAUDE.md row).

## Kill criteria

- After Task 7, `port.py --models-diff` changes any cell an agent uses → Task 8 stops for an owner ruling.
- `fragments.py` changes a line outside markers, or `check_offload_policy` fails → stop and re-plan the fragment scope.
- A Task 4 fix needs a description edit → stop; owner ruling.
- More than 3 fail-open defects in Task 1b → fix each in its own commit, then re-estimate Tasks 2–9.
- A reworded worker drops 2 or more of 6 on its `offload-*` case, or a trace shows the reworded rule ignored → revert only the rewording commit.

---

### Task 1a: Test harness (Q1)

**Files:**
- Create: `scripts/tests/conftest.py`, `scripts/tests/test_validate.py`
- Modify: `scripts/validate.py` (only what testing needs: every `check_*` that reads `ROOT`/`PLUGIN` takes them from module globals the fixture can patch)

**Interfaces:**
- Produces: fixture `mini_repo(tmp_path, monkeypatch) -> Path` that builds a minimal valid repository and patches every path global of `validate` (`ROOT`, `PLUGIN`, `POLICY`, `OFFLOAD_COMMAND`, and any other module-level path). The mini repo holds what every check except `check_ports` reads: `plugins/agent-skills/` with one skill, one worker agent, `commands/offload.md` with its row, one command per non-worker agent, `.claude-plugin/plugin.json` and `CHANGELOG.md`; `.claude-plugin/marketplace.json`; the two other tools' catalogs and every path in `PUBLIC_PATHS` (`user-config/*.md`, `user-agents/Explore.md`, README anchors); `README.md` with the `## Catalog` tables; `LICENSE`. Helper `run_checks(root) -> list[str]` returns the errors of every check except `check_ports` and the `--release` git checks. `conftest.py` puts `scripts/` on `sys.path`.

- [x] **Step 1:** `test_mini_repo_is_valid` (no errors); run the suite.
- [x] **Step 2:** Commit `test(scripts): harness with a minimal valid repository for validate.py`.

### Task 1b: `validate.py` rule tests (Q1)

**Files:**
- Modify: `scripts/tests/test_validate.py`; `scripts/validate.py` only to fix a fail-open rule

**Interfaces:**
- Consumes: `mini_repo`, `run_checks` (Task 1a).

- [x] **Step 1:** One negative test per rule, each mutating the mini repo once and asserting one error that names the file: skill name ≠ folder, description without trigger, first-person description, SKILL.md over 150 lines, reference two levels deep, reference over 100 lines without `## Contents`, broken relative link, agent without `tools`, invalid `model`, missing `effort`, worker without `maxTurns`, non-worker saying "Use proactively", Read-only agent granting `Edit`, Read-only agent without `omitClaudeMd: true`, unknown preloaded skill, command without `$ARGUMENTS`, non-worker agent with no command, README catalog missing an agent, eval grader naming an unknown agent, public path missing, `plugin.json` version without a CHANGELOG entry.
- [x] **Step 2:** Unit tests: `parse_frontmatter` (list keys, quoted values, block scalars, `argument-hint: [x]` stays text, malformed → `FrontmatterError`), `version_key` (`1.10.0` > `1.9.0`, pre-release sorts before release), `block_scalar`.
- [x] **Step 3:** The person rule ignores text inside double quotes (owner ruling above): tests `test_quoted_we_passes` (`... such as "what do we know about X"`) and `test_unquoted_we_fails`; implement in `check_description`.
- [x] **Step 4:** Run `uv run --with pytest pytest scripts/tests -q`. A rule whose negative test passes without an error is a fail-open defect: fix each in its own commit and list it in the report (kill criterion: more than 3).
- [x] **Step 5:** Commit `test(scripts): cover every validate.py rule with a negative case`.

### Task 2: `port.py` transform tests (Q2)

**Files:**
- Create: `scripts/tests/test_port.py`

**Interfaces:**
- Consumes: `port.transform`, `port.rename_agents`, `port.toml_multiline`, `port.copilot_tools`, `port.codex_capabilities`, `port.stale_token`, `port.q`.

- [x] **Step 1:** Table-driven tests: `rename_agents` (`agent-skills:x` and bare `x` in prose, no change inside a longer word), `toml_multiline` (text with `"""`, backslashes, trailing newline), `q` (quotes and backslashes), `copilot_tools` (Edit and Write collapse to `edit`, `Skill` dropped), `codex_capabilities` (read-only vs write), `transform` per target (model tag "(Haiku)" rewritten for Codex, `CLAUDE_ONLY_LINE` removed, `/agent-skills:x` → `/x` for Copilot), `stale_token` (a Claude-only token left in output is reported).
- [x] **Step 2:** Run the suite; a transform that fails a case is a defect: fix it and report it.
- [x] **Step 3:** Commit `test(scripts): table tests for port.py transforms`.

### Task 3: One agent-rule table (A10)

**Files:**
- Modify: `scripts/validate.py`, `scripts/port.py`, `scripts/tests/test_validate.py`

**Interfaces:**
- Produces in `validate.py`: `AGENT_MODELS: frozenset[str]` (today `haiku`, `sonnet`, `opus`, `fable`, `inherit`), `AGENT_EFFORTS: frozenset[str]` (`low`, `medium`, `high`), and `check_agent_rules(rel: Path, fm: Frontmatter, skill_names: set[str], errors: list[str]) -> None` covering model, effort membership, positive integer `maxTurns` when set, `omitClaudeMd` boolean, preloads.
- `port.py` imports `AGENT_EFFORTS` and `check_agent_rules`; its `check_agent` keeps only mapping coverage (model in `MODEL_MAP`, pair in `CODEX_PAIRS`, tools in `TOOL_MAP`/`TOOL_CAPABILITY`, Copilot alias conflicts). `EFFORTS` in `port.py` is removed, and the `docs/ports.md` sentence that cites `EFFORTS` names `AGENT_EFFORTS` in `validate.py`. Full `claude-` ids stay accepted (`FULL_MODEL_ID`).

- [x] **Step 1:** Tests: effort `xhigh` on an agent fails in `validate.py` with the allowed set in the message; `maxTurns: 0` fails; the same agent errors are not reported twice when `validate.py` runs `port.py --check`.
- [x] **Step 2:** Implement; `python3 scripts/port.py --check` and the suite pass; ports unchanged (`git status ports/` clean).
- [x] **Step 3:** Commit `refactor(scripts): one agent-rule table shared by validate.py and port.py`.

### Task 4: Rules over every plugin (A9)

**Files:**
- Modify: `scripts/validate.py`, `scripts/tests/test_validate.py`; agent or skill bodies under `plugins/memory/` only if they break a general rule (fix the body; never weaken the rule; a fix that needs a description edit stops the task for an owner ruling). Expected on 2026-11-25: no error left after Task 1b's quoted-text rule.

**Interfaces:**
- `check_skills(errors, plugin: Path) -> set[str]` and `check_agents(errors, skill_names, plugin: Path) -> set[str]` take the plugin folder; `main` runs them for every `plugins/*/` that has `skills/` or `agents/`. General rules: name, description shape and person, line budgets, references, links, model, effort, Read-only config, preloads. Rules that stay on `agent-skills` only: `WORKERS` and `maxTurns` for workers (the "Use proactively" rule is repo-wide: only those workers may say it), offload rows, commands per agent, README catalog, eval graders.
- The summary line counts all plugins: `OK: <n> skills, <m> agents, 0 errors`.

- [x] **Step 1:** Tests: a memory-plugin agent with an invalid `model` fails; `test_memory_agent_without_command_passes`; a memory agent saying "Use proactively" fails (repo-wide rule, CLAUDE.md, ADR 0007/0010; corrected after the Task 4 review).
- [x] **Step 2:** Implement; run `python3 scripts/validate.py`. List every new error on the real repository in the report, with the fix applied to each `plugins/memory/` file.
- [x] **Step 3:** If a memory file changed: a line under `## [Unreleased]` in `plugins/memory/CHANGELOG.md`.
- [x] **Step 4:** Commit `feat(scripts): validate agents and skills of every plugin`.

### Task 5: `promptkit.fragments`: marked blocks from one source

**Files:**
- Create: `scripts/promptkit/__init__.py`, `scripts/promptkit/fragments.py`, `scripts/tests/test_fragments.py`, `shared/fragments/README.md` (what a fragment is, marker syntax, the two commands)

**Interfaces:**
- Run every promptkit CLI as `python3 -m promptkit.<module>` from `scripts/` (or with `PYTHONPATH=scripts`); promptkit never imports `port` or `validate`.
- Fences follow CommonMark: a fence closes only with the same character and at least the opening length, so ```` with an inner ``` stays one fence; `~~~` counts; an unclosed fence runs to the end of the file.
- Marker syntax (line-anchored, outside fenced code):

  ```
  <!-- shared:<id> key="value" ... -->
  rendered text
  <!-- /shared:<id> -->
  ```

  A fragment is `shared/fragments/<id>.md`; `{{key}}` placeholders are filled from the opening marker's attributes.
- Produces: `class FragmentError(ValueError)`; `load_fragments(folder: Path) -> dict[str, str]` (id → text without trailing newline); `render(text: str, fragments: dict[str, str]) -> str` (raises `FragmentError` on unknown id, unclosed or mismatched marker, missing or unused parameter); `strip_markers(text: str) -> str` (removes marker lines, keeps content); `find_unmarked(text: str, fragments: dict[str, str]) -> list[str]` (ids of parameterless fragments whose full text appears outside any block); `main(argv) -> int` with `python3 -m promptkit.fragments [--check] [--root PATH]`, scanning `plugins/*/{agents,commands}/*.md` and `plugins/*/skills/**/*.md` (never `user-config/`: see the pre-mortem findings); `--check` prints `<file>: block '<id>' differs from shared/fragments/<id>.md` per drift and `<file>: text of '<id>' outside a block` per unmarked copy, and exits 1. A fragment may declare `verbatim-in: user-config/offload-policy.md` on its first line (stripped from the text); `--check` then also requires the fragment text to appear verbatim in that file.

- [x] **Step 1:** Tests: `test_render_fills_block`, `test_render_is_idempotent`, `test_params_fill_placeholders`, `test_missing_param_fails`, `test_unused_param_fails`, `test_unknown_id_fails`, `test_unclosed_marker_fails`, `test_markers_in_code_fence_ignored`, `test_nested_fence_four_backticks`, `test_tilde_fence`, `test_unclosed_fence`, `test_check_reports_hand_edit` (names file and id), `test_shared_text_outside_block_reported`, `test_verbatim_in_mismatch_fails`, `test_strip_markers_keeps_content`.
- [x] **Step 2:** Implement; run the suite.
- [x] **Step 3:** `validate.py` gains `check_fragments(errors)` calling the `--check` logic (no subprocess needed).
- [x] **Step 4:** Commit `feat(scripts): promptkit fragments render shared text into marked blocks`.

### Task 6a: Markers around identical shared lines (mechanical)

**Files:**
- Create: one `shared/fragments/<id>.md` per text below
- Modify: the agent, skill and command files that carry an identical copy; `scripts/port.py`: `strip_markers` in both `transform` and `expected_text`, and references are stripped in both the generator and `Verifier.skill`, so ports carry no markers; `scripts/tests/test_port.py` gains `test_check_passes_with_block` (a skill reference and an agent with a block pass `--check`)

**Interfaces:**
- Consumes: Task 5.

- [x] **Step 1:** Fragments for each line repeated identically 3 or more times across `plugins/*/agents/*.md` (find them with `cat plugins/*/agents/*.md | sort | uniq -c | sort -rn`); on 2026-11-25: the English-report line (17), the Bash-leaves-files-unchanged line (6 identical of 11), the delegation line (5), the `fff` tools line (4). The six-part brief becomes a fragment taken verbatim from `user-config/offload-policy.md`, declared `verbatim-in: user-config/offload-policy.md`, with a block only in `prompt-engineering/references/skills-and-agents.md` if its copy there is identical; offload-policy.md itself gets no markers. Only identical copies get markers in this task.
- [x] **Step 2:** Run `python3 -m promptkit.fragments` from `scripts/`. Check: `git diff -U0 plugins/` shows only added marker lines; `python3 scripts/port.py` leaves `ports/` unchanged; `python3 scripts/validate.py` OK.
- [x] **Step 3:** CHANGELOG line (agent-skills, refactor, no behavior change). Commit `refactor(agent-skills): shared prompt lines rendered from one source`.

### Task 6b: Reworded copies, ADR citations, vocabulary (main session or Opus; judgment)

**Files:**
- Modify: agent and skill bodies holding a drifted copy of a Task 6a fragment; files cited below; `plugins/agent-skills/CHANGELOG.md`; ADR 0029 (Task 9) carries this task's kill criteria

- [x] **Step 1:** Drifted copies (same rule, other wording; e.g. the 5 non-identical Bash lines, a `skills-and-agents.md` six-part copy that differs) take the fragment's wording inside a block. List each changed file with the old and new line.
- [x] **Step 2:** B9: in files shipped to users (`plugins/*/skills/**`, `plugins/*/agents/**`), replace each bare "ADR NNNN" citation with its reason in a few words (installed users cannot open the ADRs); CHANGELOG and evals keep theirs. B10: `pre-mortem.md` says "risk" where it says "finding" (ADR 0007 vocabulary); `feature-briefing/SKILL.md` gives `ux-reviewer` no `design` mode it lacks (word it by the modes `ux-reviewer.md` has).
- [x] **Step 3:** Measure: for each worker whose body changed (likely `fixer`, `implementer`), run its `offload-*` cases per CLAUDE.md § Eval protocol, or read one trace each when the run is not affordable, and record the numbers in ADR 0029. Non-worker bodies ship unmeasured with ADR 0029's kill criteria.
- [x] **Step 4:** `python3 scripts/port.py`; `python3 scripts/validate.py`. CHANGELOG line (agent-skills): wording unified in the listed agents; ADR numbers replaced by reasons in shipped text.
- [x] **Step 5:** Commits, each revertible alone: `fix(agent-skills): unify drifted copies of shared lines`, then `fix(agent-skills): vocabulary and ADR citations in shipped text`.

### Task 7: `promptkit.models`: catalog and derivation (no switch yet)

**Files:**
- Create: `shared/models.toml`, `scripts/promptkit/models.py`, `scripts/tests/test_models.py`

**Interfaces:**
- `shared/models.toml`:

  ```toml
  # level: capability on a scale shared across vendors (owner judgment; 1 = cheapest tier of the oldest pairing).
  # cost: price per token relative to the vendor's cheapest model; never compared across vendors.
  [policy]
  efforts = ["low", "medium", "high", "xhigh", "max"]
  effort_step = 0.25          # grade = level + effort_step * index(effort)
  never = ["max"]             # never chosen as a target effort
  xhigh_only_on_top = true    # the next model at low beats the previous at xhigh (owner, 2026-11-25)

  [[vendors.claude.models]]   # alias = the agent frontmatter value; copilot = the Copilot CLI id
  alias = "haiku";  level = 1; cost = 1;  copilot = "claude-haiku-5.5"
  # sonnet level 2 cost 20, opus 3 cost 40, fable 4 cost 80, copilot ids from port.COPILOT_MODELS

  [[vendors.codex.models]]
  id = "gpt-6-luna"; level = 1.25; cost = 1
  # gpt-6.1-terra level 2.25 cost 10, gpt-6.2-sol 3.25 cost 20, gpt-6.2-astra 4.0 cost 80 (credits, docs/ports.md);
  # best-fit levels from the pre-mortem: every cell an agent uses keeps today's pair

  [[overrides]]
  from = ["haiku", "medium"]; to = ["gpt-6-luna", "low"]; reason = "owner 2026-11-03, ADR 0017"
  # plus one override each for sonnet/low, sonnet/xhigh, opus/xhigh to today's pair, each with its reason
  # (owner 2026-11-19 cell rulings, docs/ports.md), unless the owner rules otherwise at Task 8
  ```

  (TOML needs one key per line; the implementer writes it in valid TOML.)
- Produces: `@dataclass(frozen=True) Model(vendor: str, key: str, level: float, cost: float, copilot: str | None)`; `Catalog` with `models(vendor) -> list[Model]`, `policy`, `overrides`; `load_catalog(path: Path) -> Catalog`; `grade(model: Model, effort: str, catalog: Catalog) -> float`; `allowed_targets(vendor: str, catalog: Catalog) -> list[tuple[Model, str]]`; `derive_pairs(catalog: Catalog, source: str, target: str) -> dict[tuple[str, str], tuple[str, str]]`: for each source (model, effort) including `max`, the allowed target pair with the smallest grade ≥ the source grade, ties to the lower `cost`; none ≥ → the highest-grade allowed pair; overrides applied last. `load_catalog` raises `ValueError` unless levels rise strictly within each vendor and, for consecutive models, `grade(next, "low") > grade(previous, "xhigh")`. `port.py --models-diff` (in `port.py`, so promptkit stays generic) prints each cell where `derive_pairs(..., "claude", "codex")` differs from `CODEX_PAIRS` as `haiku/high: gpt-6-luna medium -> ...`, and marks the cells agents use.

- [x] **Step 1:** Tests on a small fixture catalog: `test_next_model_low_beats_previous_xhigh`, `test_max_never_chosen`, `test_xhigh_only_on_top`, `test_above_all_maps_to_top_allowed`, `test_tie_goes_to_cheaper`, `test_override_wins`, `test_every_source_pair_mapped` (20 cells for 4 models × 5 efforts), `test_catalog_rejects_falling_levels`, `test_catalog_rejects_spacing_that_breaks_next_low`; on the real catalog, `test_agent_cells_keep_todays_pairs` (every (model, effort) an agent declares maps to its current `CODEX_PAIRS` value).
- [x] **Step 2:** Implement; run the suite; run `python3 scripts/port.py --models-diff` and paste its full output into the report.
- [x] **Step 3:** Commit `feat(scripts): vendor model catalog and derived cross-vendor pairs`.

### Task 8: Owner gate, then switch the Codex mapping

**Files:**
- Modify: `shared/models.toml` (levels or overrides as ruled), `scripts/port.py` (`CODEX_PAIRS = derive_pairs(load_catalog(...), "claude", "codex")`, `COPILOT_MODELS` from the catalog's `copilot` ids, `validate.AGENT_MODELS` from the catalog's Claude aliases plus `inherit`), `docs/ports.md` § Models (a generated block, `<!-- BEGIN generated: models -->`, rendered by `port.py` from the catalog: per vendor model, level, relative cost; then the derived pair table), `plugins/agent-skills/CHANGELOG.md`

- [x] **Step 1 (main session, not a worker):** Owner ruling 2026-11-25: accept the derived table (only the four unused `max` cells change: haiku luna xhigh → terra low, sonnet terra xhigh → sol low, opus sol xhigh → astra low, fable astra max → astra xhigh). Original step: Show the owner the `--models-diff` output of Task 7 as a before/after table per agent (none expected) and per unused cell, noting that a higher effort uses more tokens; record the ruling (accept, change levels, add overrides) in this plan.
- [x] **Step 2:** Implement the switch; `python3 scripts/port.py`; `--models-diff` removed with the hand table it compared against (the generated `docs/ports.md` block and the literal `AGENT_PAIRS` pins in `test_models.py` guard remaps instead); the generated block in `docs/ports.md` is listed in CLAUDE.md § Generated files.
- [x] **Step 3:** CHANGELOG line (agent-skills): Codex port models derived from the catalog; list the agents whose Codex model or effort changed.
- [x] **Step 4:** Commit `feat(ports): derive the Codex model mapping from the model catalog`.

### Task 9: Opt-in `pre-push` hook (Q3) and documentation

**Files:**
- Create: `scripts/hooks/pre-push` (POSIX sh, executable), `scripts/tests/test_hook.py`, `docs/adr/0029-shared-text-and-model-catalog.md` (0028 is reserved for the memory split)
- Modify: `CLAUDE.md` (Commands table: the opt-in line and the test command; Where a change goes: rows for `shared/fragments/` and `shared/models.toml`, the latter saying any edit needs the generated `docs/ports.md` table in the diff and a CHANGELOG line; Generated files: rendered blocks and the `docs/ports.md` models block), `README.md` § Develop, `docs/requirements.md` (N5 note: opt-in hook), `docs/ports.md` (link the catalog as the home of model facts), `docs/backlog.md` (remove done items, move dates), the review study (mark Q1, Q2, Q3, A9, A10, B9–B12 done)

**Interfaces:**
- Hook runs, in order: `python3 scripts/validate.py`; `uv run --with pytest pytest scripts/tests -q` if `uv` is on `PATH`; `claude plugin validate .` if `claude` is on `PATH`. A missing tool prints `pre-push: skipped <check> (<tool> not found)`; any failing check exits non-zero. Opt-in: `git config core.hooksPath scripts/hooks`.

- [ ] **Step 1:** Tests (`subprocess` with a fake `PATH`): `test_hook_fails_on_validate_error`, `test_hook_skips_missing_tools`.
- [ ] **Step 2:** Implement the hook and the docs; ADR 0029 records: marked blocks over templates (why, including the owner's install-time rendering alternative: no tool runs a plugin step at install, a `SessionStart` render applies only from the next session and writes into a cache that updates replace; revisit if a tool adds an install hook or variable substitution in agent and skill bodies), the catalog's level and cost semantics, the effort policy, the quoted-text person rule, Task 6b's measurements and kill criteria, ADR 0015 amended; update ADR 0015's Status line with `Amended by 0029`.
- [ ] **Step 3:** Run the hook once by hand: `sh scripts/hooks/pre-push`; paste its last lines.
- [ ] **Step 4:** Commit `feat(scripts): opt-in pre-push hook; docs for promptkit and the model catalog`.
