# Memory capture in the background (stage B2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With the plugin option `auto_capture` on, each compaction and each session end starts one detached `mem-capture auto` run that reads the transcript from the line where the last run stopped and writes unconfirmed lessons into the project's memory; with the option off (the default) nothing changes.

**Architecture:** `bin/mem-capture` gains a command `auto` that reads the hook's JSON from standard input, takes one lock, and calls the existing `run --write` logic once per window, saving the last line read per session. `capture.extract` gains a forward mode that stops when the extract is full, so a long stretch is read as several windows instead of losing its beginning. The `PreCompact` and `SessionEnd` hooks start it with the `setsid nohup` line `session-end.sh` already uses for `mem-settle`.

**Tech Stack:** Python standard library (as `mem-auto`), bash hooks, pytest.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md), stage B2 and decisions C3 to C7, C22 to C27.

## Global Constraints

- Tests: `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`; before every commit also `python3 scripts/validate.py` and `claude plugin validate .`, chained with `&&` before `git commit`.
- No version change. One line under `## [Unreleased]` of `plugins/memory/CHANGELOG.md`, written for users.
- This repository is public: no home path, transcript text, memory text or project name in code, tests, docs or commit messages. Test transcripts are invented.
- Everything a run writes outside the project's memory goes under the data folder (`MEM_DATA`, else the state folder), in folders of mode 0700 and files of mode 0600.
- A hook never fails and never waits: `pre-compact.sh` and `session-end.sh` exit 0 within their timeout whatever `mem-capture` does, and `pre-compact.sh` still prints its HANDOFF text unchanged.
- With `CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE` unset or not exactly `true`, no process is started and no file is created.
- Stage staged files by name (`git add <path>`), never `git add -u` or `-A`. A report written under `.superpowers/` is never committed.

## Decisions of this stage (C22 to C27 in the design)

| # | Decision | Reason |
|---|---|---|
| C22 | A background run reads forward in windows: each window holds at most `EXTRACT_LIMIT` characters of extract, at most `MAX_WINDOWS = 3` windows per trigger, no new window once this trigger has written `MAX_NEW_PER_TRIGGER = 5` new records, and the next trigger continues where this one stopped | `extract` keeps the tail and drops the beginning when a stretch is long; a compaction covers a long stretch; the cap keeps one trigger from flooding the project (pre-mortem risk 6) |
| C23 | The saved offset moves past a window when the window was full, or when a model session ran and ended without error. It stays when the window was `too short` and reached the end of the file, and when the window failed; a window that failed twice at the same offset is skipped (the offset moves past it and the log line says so). A window whose candidates were all refused because `mem` could not run counts as failed | Short remainders accumulate until there is enough to read; a failed window is read again once, and never blocks the rest of the session |
| C24 | A background run writes only into a project that already has its memory folder; elsewhere (also when the session's folder is in no project) it skips with a reason in the log and never a failure | A background process must not create a folder in a repository the owner never set up for memory |
| C25 | One lock for all background captures of a data folder; a run waits up to 900 s for it, then gives up without a failure. A run started at `PreCompact` first waits 300 s | `PreCompact` and `SessionEnd` of one session can fire close together, and the second must not lose the tail. The next context records the summary's "not yet recorded" items right after a compaction; the wait lets those writes land in the "already recorded" list (pre-mortem risk 1; it does not help when the owner answers later) |
| C27 | The offset and the sightings use one identity: the transcript file's stem | `run --write` already names the sighting `session <stem>` |
| C26 | Option `auto_capture` (boolean, off) and `auto_capture_budget` (USD per window, default 0.25). A failed run leaves one line in the session start text until `mem-capture ack` | As `auto_curation` and `auto_settle` |

Observed 2026-11-22: in 43 transcripts of the last 12 days no user entry appears in two files, so one transcript file is one session and a per-file offset does not read the same text twice.

## Known limits, accepted for this stage (pre-mortem, 2026-11-22)

- A lesson the session recorded itself and the capture rewords is recorded twice: only an identical claim is refused. Counted in Task 5 and by the kill criteria; a match on meaning belongs to stage B3.
- The end of a session is not read when `SessionEnd` never fires, when the lock wait runs out, or when the trigger stops at `MAX_WINDOWS`; the log line's `more` field counts the last case. No catch-up pass yet.
- A forked session that copies its history into a new file would be read as a second session (not seen in 43 transcripts).
- Text typed by an automated multi-turn client counts as the owner's; the memory-folder check and the 3-OWNER-lines minimum are the only guards.
- A `light` record written in the background is established at once (C20). Whether background writes should need two sessions is the owner's decision.

## Review Focus

- A transcript path that does not exist, is a folder, or is missing from the hook input: the run ends quietly, exit 0, no failure line.
- The hook input is empty or not JSON: exit 0, nothing written.
- A second trigger while a run holds the lock: it waits, then reads from the offset the first run saved (no window read twice).
- A window of long autonomous work with fewer than 3 OWNER lines that is full: the offset still advances (no endless rereading of the same window).
- `mem-capture` started by a Python without the `yaml` module: a failed status with that reason, never a silent death.
- The same session captured at `PreCompact` and again at `SessionEnd`: no record gains a second sighting from it.
- A session whose transcript shrank below the saved offset (file replaced): the offset is reset to 0 only if the file is shorter than the offset.

---

### Task 1: Forward windows in the extract

**Files:**
- Modify: `plugins/memory/engine/capture.py` (`extract`)
- Modify: `plugins/memory/bin/mem-capture` (`run --forward`, result key `extract.more`)
- Test: `plugins/memory/engine/tests/test_capture.py`, `plugins/memory/engine/tests/test_mem_capture.py`

**Interfaces:**
- Produces: `capture.extract(transcript: Path, since_line: int = 0, forward: bool = False) -> tuple[str, int]`; module variable `capture.last_more: bool` (set by every call, as `last_skipped` is). With `forward=True` the function stops before the first transcript line whose events would take the kept text over the budget, returns as last line the line before it, sets `last_more = True`, and never adds the left-out marker. A line whose events alone exceed the budget is kept when nothing is kept yet (progress is guaranteed). With `forward=False` behavior is unchanged and `last_more` is False.
- Produces: `mem-capture run --forward`; result `extract.more` (bool, False without `--forward`).

- [x] **Step 1: Write the failing tests** in `test_capture.py`:
  - `test_forward_stops_when_full`: a transcript of 200 human-origin user lines of 1,000 characters each; `extract(p, 0, forward=True)` returns text of at most `EXTRACT_LIMIT` characters whose first line starts with `[1] OWNER:`, `last < 200`, `capture.last_more is True`, and the text does not contain `capture.LEFT_OUT_MARKER`.
  - `test_forward_windows_cover_every_line_once`: calling `extract(p, last, forward=True)` repeatedly until `last_more` is False yields `[n]` prefixes that together are exactly 1..200, each once.
  - `test_forward_short_transcript`: 5 lines → `last == 5`, `last_more is False`, same text as `forward=False`.
  - `test_forward_keeps_an_oversized_first_line`: `monkeypatch.setattr(capture, "EXTRACT_LIMIT", 300)` and a first line of 2,000 characters → text non-empty, `last == 1`.
  - `test_default_mode_unchanged`: `extract(p, 0)` on the 200-line transcript still starts with the left-out marker, returns `last == 200`, `last_more is False`.
  In `test_mem_capture.py`: `test_run_forward_reports_more`: a long invented transcript with `--forward` gives result `lines[1]` below the file's line count and `extract.more` true; without `--forward`, `extract.more` false.
- [x] **Step 2: Run them, expect FAIL** (`TypeError: extract() got an unexpected keyword argument 'forward'`).
- [x] **Step 3: Implement** the `forward` parameter and `last_more`; in `cmd_run` pass `args.forward`, set `out["extract"]["more"]`.
- [x] **Step 4: Run the whole suite, expect PASS.**
- [x] **Step 5: Commit** `feat(memory): mem-capture reads forward in windows (--forward)`.

### Task 2: State module and a callable window

**Files:**
- Create: `plugins/memory/engine/capture_state.py` (standard library only)
- Modify: `plugins/memory/bin/mem-capture` (subparsers; `run_window`)
- Test: `plugins/memory/engine/tests/test_capture_state.py`; `test_mem_capture.py` must pass untouched

**Interfaces:**
- Consumes: `auto_state.private_dir`, `read_json`, `write_json`, `failure`, `take_run_lock`.
- Produces, in `capture_state.py`:
  - `capture_dir(data: Path) -> Path` = `<data>/capture`
  - `session_path(data: Path, session: str) -> Path` = `<data>/capture/sessions/<sha1(session)[:16]>.json`, content `{"session": str, "offset": int, "attempts": int, "updated": float}`
  - `read_session(data, session) -> dict` (`{"offset": 0, "attempts": 0}` when absent or unreadable), `save_session(data, session, offset: int, attempts: int) -> None`
  - `failure_line(data: Path | None, now: float) -> str | None` → `Automatic capture failed on <date>: <reason>; log: <path> (mem-capture ack clears this).` (reads `<capture_dir>/status.json` through `auto_state.failure`)
  - `prune_runs(runs: Path, keep: int, max_age_days: int, now: float) -> None`: deletes run folders beyond the newest `keep` and any older than `max_age_days`
  - constants `MAX_WINDOWS = 3`, `MAX_NEW_PER_TRIGGER = 5`, `MAX_ATTEMPTS = 2`, `LOCK_WAIT_SECONDS = 900`, `PRE_COMPACT_DELAY_SECONDS = 300`, `KEEP_RUNS = 20`, `KEEP_RUN_DAYS = 14`, `OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE"`, `BUDGET_OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE_BUDGET"`
- Produces, in `bin/mem-capture`: `run_window(transcript: Path, out_path: Path, project: Path | None, since_line: int, model: str, budget: float, claude: str | None, forward: bool, write: bool, no_rules: bool = False, keep_work: bool = False, allow_out_in_repo: bool = False, quiet: bool = False) -> tuple[dict, int]` holding today's body of `cmd_run` (result dict and exit code; `quiet` suppresses the summary line on standard output); `cmd_run` becomes a thin caller. The parser becomes subparsers so that `--transcript` and `--out` are required only by `run`; `mem-capture run …` keeps every flag, message and exit code.

- [x] **Step 1: Write the failing tests** in `test_capture_state.py`: session round trip (`save_session` then `read_session`), unreadable file → zeros, files of mode 0600 in folders of mode 0700; `failure_line` None without a status, the line with a `failure` in `status.json`, the "did not finish" line for a `running` status older than `auto_state.STALE_RUNNING_SECONDS`; `prune_runs` keeps 20 of 22 and deletes one made 15 days old with `os.utime`. In `test_mem_capture.py` add only `test_run_window_is_importable_and_quiet` (load the script as a module the way `test_mem_capture.py` already loads it, or through a subprocess if it does not; `quiet=True` prints nothing).
- [x] **Step 2: Run them, expect FAIL** (`ModuleNotFoundError: capture_state`).
- [x] **Step 3: Implement.**
- [x] **Step 4: Run the whole suite, expect PASS** with `test_mem_capture.py` otherwise unchanged.
- [x] **Step 5: Commit** `refactor(memory): mem-capture window as a function; state of background captures`.

### Task 3: `mem-capture auto` and `ack`

**Files:**
- Modify: `plugins/memory/bin/mem-capture` (commands `auto`, `ack`)
- Test: `plugins/memory/engine/tests/test_capture_auto.py`

**Interfaces:**
- Consumes: `run_window`, `capture_state.*` (Task 2); `capture.extract(..., forward=True)` through `run_window(forward=True)` (Task 1); `records.project_root`, `records.project_dir`; the data folder as `mem-auto` resolves it.
- Produces: `mem-capture auto --trigger {pre-compact,session-end} [--claude PATH]`, reading the hook JSON (`transcript_path`, `cwd`) from standard input; always exit 0. `mem-capture ack` removes the `failure` key of `status.json`, exit 0.
- Test-only overrides, read from the environment: `MEM_CAPTURE_LOCK_WAIT` and `MEM_CAPTURE_DELAY` (seconds).

The script's module imports: `capture_state` and `auto_state` (standard library only) are imported first; `capture`, `records` and `synth_pipeline` inside a guard. When that guarded import fails and the command is `auto` with the option on, write `status.json` with `state: failed` and `failure.reason` `cannot load the engine: <exception text, 200 chars>`, exit 0; for `run` the error is printed and the exit code is 1.

Behavior of `auto`, in order:
1. Option not exactly `true` → return, nothing created.
2. Input not a JSON object, `transcript_path` missing or not a file → return, nothing created.
3. `cwd` from the input missing or not a folder → return. Project = `records.project_root(cwd, env)` (an inherited `MEM_PROJECT` wins, as everywhere in `mem`); None, or `records.project_dir(project)` not a folder → append the log line with `"skipped": "the project has no memory folder"`, return. No model is called before this check.
4. Session = the transcript file's stem (C27).
5. Trigger `pre-compact`: sleep `PRE_COMPACT_DELAY_SECONDS` (override `MEM_CAPTURE_DELAY`).
6. Take the lock of `capture_dir`, retrying every 5 s up to `LOCK_WAIT_SECONDS` (override `MEM_CAPTURE_LOCK_WAIT`); not obtained → log line with `"skipped": "another capture is running"`, return.
7. Write `status.json` `{"state": "running", "started": now, "log": <run folder>}`, keeping an existing `failure` key. Run folder: `<capture_dir>/runs/<YYYYmmdd-HHMMSS>-<pid>/`, holding `log.txt` and `window-N.json`.
8. `read_session`; if the transcript has fewer lines than the offset, offset = 0 and attempts = 0. Loop at most `MAX_WINDOWS` times, and not once `MAX_NEW_PER_TRIGGER` new records were written by this trigger: `run_window(since_line=offset, forward=True, write=True, allow_out_in_repo=True, quiet=True, model="haiku", budget = BUDGET_OPTION else 0.25)`, then apply C23:
   - the window failed (exit code not 0, or it has candidates and every `written` row's reason starts with `mem could not run` or `mem failed`): attempts += 1; below `MAX_ATTEMPTS` → `save_session(offset, attempts)`, record the failure in the status, stop; at `MAX_ATTEMPTS` → `save_session(lines[1], 0)`, count the window as `given_up`, record the failure, stop;
   - reason `too short` and `extract.more` false → stop, offset unchanged;
   - otherwise `save_session(lines[1], 0)`; continue only when `extract.more` is true.
9. Write `status.json` with `state` `ok` or `failed`, `finished`, the summed `cost`; an earlier unacknowledged `failure` is dropped only when this run read at least one window with a model and none failed.
10. Append one line to `<capture_dir>/log.jsonl`: `{"t": <UTC ISO>, "trigger", "session", "windows": int, "kept": int, "written": {"remembered": int, "sighting": int, "skipped": int}, "cost": float | null, "offset": int, "more": bool, "skipped": str | null, "failed": str | null, "given_up": int, "ms": int}`. No claim text and no path in this line.
11. `prune_runs(runs, KEEP_RUNS, KEEP_RUN_DAYS, now)`.
Any exception inside `auto` is caught at the top: status `failed` with the exception's class name as reason, exit 0.

- [ ] **Step 1: Write the failing tests** in `test_capture_auto.py`, reusing the fake `claude` and the `world` fixture style of `test_mem_capture.py` (`MEM_DATA` in tmp, a tmp git project whose memory folder is made by one `mem remember`, `CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE=true`, `MEM_CAPTURE_DELAY=0`), calling `bin/mem-capture auto --trigger session-end --claude FAKE` with the JSON on stdin:
  - `test_off_by_default`: option unset → exit 0, the data folder has no `capture` folder, the fake was not called.
  - `test_first_run_writes_and_saves_offset`: a 12-line invented transcript with 4 OWNER lines and a fake candidate whose evidence is in it → `mem memories` of the project lists the claim with `from transcript, unconfirmed`; offset 12; `status.json` state `ok`; one `log.jsonl` line with `windows == 1`, `written.remembered == 1`.
  - `test_second_run_reads_only_new_lines`: run, append 6 lines (3 OWNER), run again → the second run's `window-1.json` has `lines == [13, 18]`; the fake was called twice.
  - `test_same_session_twice_adds_no_sighting`: the fake returns the same claim in both runs of the previous test's shape → the record's sources hold one `session` entry.
  - `test_short_remainder_keeps_offset`: run, append 2 lines (1 OWNER), run → offset still 12, fake called once in total; append 4 more (3 OWNER), run → the window is `[13, 18]`.
  - `test_long_stretch_stops_at_max_windows`: a transcript long enough for 5 forward windows (built from `capture.EXTRACT_LIMIT`), the fake returning no candidates → fake called 3 times, offset equals the third window's last line, log line `more` true; a further run continues from it.
  - `test_stops_after_five_new_records`: the fake returns 5 valid candidates per window on a 3-window transcript → fake called once, log `written.remembered == 5`, `more` true.
  - `test_full_window_without_owner_lines_advances`: a full window made only of assistant text, then lines with 3 OWNER lines → the offset passes the first window and the fake is called for the second only.
  - `test_failure_leaves_a_line_and_keeps_offset`: `FAKE_MODE=exit1` → exit 0, offset 0, attempts 1, `capture_state.failure_line` starts with `Automatic capture failed on`; after `mem-capture ack` it is None.
  - `test_second_failure_skips_the_window`: `FAKE_MODE=badjson` twice → after the second run the offset equals the window's last line, attempts 0, log `given_up == 1`; a third run with a good fake and new lines reads only the new lines.
  - `test_mem_failure_is_a_failed_window`: `PATH` without `uv` for the run (so `bin/mem` exits 127) and one valid candidate → offset unchanged, a failure line.
  - `test_no_memory_folder_skips`: a git project without memory → fake not called, no memory folder created, log `skipped` reason, no failure line. `test_cwd_outside_a_project_skips`: a plain tmp folder → the same.
  - `test_bad_input_is_quiet`: stdin empty, stdin `[]`, a `transcript_path` that does not exist → exit 0 each, no `capture` folder.
  - `test_shrunk_transcript_resets_offset`: saved offset 50 for a 12-line file → the window starts at line 1.
  - `test_lock_wait_gives_up`: hold the lock from the test with `auto_state.take_run_lock(capture_dir)`, `MEM_CAPTURE_LOCK_WAIT=1` → exit 0, fake not called, `skipped == "another capture is running"`.
  - `test_waits_for_the_lock_then_continues`: hold the lock, start `auto` with `MEM_CAPTURE_LOCK_WAIT=20` in a subprocess, release after 2 s → it runs and saves the offset.
  - `test_pre_compact_waits_before_reading`: `--trigger pre-compact` with `MEM_CAPTURE_DELAY=2`, a memory written by the test during that wait with the candidate's exact claim → the candidate is dropped as already recorded.
  - `test_engine_import_failure_is_reported`: run the script with `python3 -S -I` style isolation or `PYTHONPATH` shadowing a `yaml.py` that raises ImportError (whichever makes `import yaml` fail on this machine) → exit 0 and `failure_line` contains `cannot load the engine`.
  - `test_data_folder_inside_a_repository_works`: `MEM_DATA` inside a git repository → the window is written and the run is `ok`.
  - `test_log_line_has_no_text`: the `log.jsonl` line contains neither the claim nor the transcript's folder path.
- [ ] **Step 2: Run them, expect FAIL** (`invalid choice: 'auto'`).
- [ ] **Step 3: Implement** `auto` and `ack`.
- [ ] **Step 4: Run the whole suite, expect PASS.**
- [ ] **Step 5: Commit** `feat(memory): mem-capture auto reads a session in windows from a saved offset`.

### Task 4: Option, hooks, session start line and docs

**Files:**
- Modify: `plugins/memory/.claude-plugin/plugin.json` (`userConfig`: `auto_capture` boolean, title `Automatic capture`; `auto_capture_budget` number, default 0.25)
- Modify: `plugins/memory/hooks/pre-compact.sh`, `plugins/memory/hooks/session-end.sh`
- Modify: `plugins/memory/engine/mem.py` (`cmd_session_index`: add `capture_state.failure_line(data_dir(os.environ), time.time())` to the notices)
- Modify: `plugins/memory/README.md` (section `### Automatic capture (off by default; not yet measured)` after the settling section; the capture trial section no longer says nothing runs by itself), `plugins/memory/CHANGELOG.md`, `plugins/memory/skills/memory/SKILL.md` only if it names what runs by itself
- Test: `plugins/memory/engine/tests/test_plugin_shell.py`, `plugins/memory/engine/tests/test_capture_auto.py`

**Interfaces:**
- Consumes: `mem-capture auto --trigger … [--claude PATH]` reading the hook JSON on stdin (Task 3); `capture_state.failure_line` (Task 2).
- Hook lines. In both hooks, only when `[ "${CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE:-}" = "true" ]`: read standard input once into a variable (`input=$(cat)`; with the option off standard input is not read), find `claude` as `session-end.sh` already does, and start `(setsid nohup "$here/../bin/mem-capture" auto --trigger <name> [--claude "$claude"] <<<"$input" >/dev/null 2>&1 &)`, with the same no-`setsid` fallback `session-end.sh` has. `pre-compact.sh` prints its HANDOFF text first and the text does not change. In `session-end.sh` the capture block comes before `mem history commit` (it writes the project, not the store, and the hook's time may run out during the commit).

- [ ] **Step 1: Write the failing tests.** In `test_plugin_shell.py`:
  - `test_plugin_declares_auto_capture`: `userConfig.auto_capture.type == "boolean"`, no `default` true; `auto_capture_budget.default == 0.25`.
  - `test_pre_compact_text_unchanged_with_capture_on`: stdout of `pre-compact.sh` with the option `true` and a JSON on stdin equals its stdout with the option unset.
  - `test_pre_compact_starts_capture_only_when_on`: with a stub `bin`-sibling approach used by the existing session-end tests (the pattern for observing a detached start is in `test_auto_curation.py`: a fake `claude` that appends to `FAKE_CALLS`, polled up to 10 s; use a tmp git project with a memory folder, a transcript with 4 OWNER lines and `MEM_CAPTURE_DELAY=0`) → called with the option on, not called with it unset.
  - `test_session_end_starts_capture_only_when_on`: the same for `session-end.sh`.
  - `test_session_end_starts_capture_when_the_commit_hangs`: with the hanging-git setup of the existing `test_session_end_hook_exits_0_when_git_hangs`, the fake `claude` is still called.
  - `test_hooks_return_fast_with_capture_on`: each hook returns in under 2 s while the fake `claude` sleeps 5 s.
  In `test_capture_auto.py`: `test_session_index_shows_the_failure_line`: after a failed `auto` run, `mem session-index` output contains `Automatic capture failed on`; after `mem-capture ack` it does not.
- [ ] **Step 2: Run them, expect FAIL.**
- [ ] **Step 3: Implement** the option, the two hook blocks, the notice, the README section (what it does, when it runs, the two options, where the status and log live, `mem-capture ack`, the limits: only projects with a memory folder, at most 3 windows and about 5 new records per trigger, a 5-minute wait after a compaction, the end of a session whose terminal was closed is not read, unmeasured) and the CHANGELOG line.
- [ ] **Step 4: Run the whole suite and both validators, expect PASS.**
- [ ] **Step 5: Commit** `feat(memory): option auto_capture starts mem-capture at compaction and session end`.

### Task 5: End-to-end check with the real model, and the records (controller)

- [ ] Run `hooks/pre-compact.sh` and `hooks/session-end.sh` by hand with the option on, `MEM_DATA` and `MEM_PROJECT` pointing at a private copy outside the repository, a real transcript on stdin: the hook returns at once, the detached run finishes, `status.json` is `ok`, the offset is saved, a second trigger reads only new lines. Record counts and cost (no text) below.
- [ ] Design: C22 to C27 added, stage B2 marked done. ADR 0023: `### Stage B2` under Review 2026-11-22 with kill criteria. Study: L3 status. Memory plan state table.
- [ ] Final narrow reviews, fixes, push, pull request to `dev`.

## Results

(filled in by Task 5)
