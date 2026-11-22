# Memory Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reminder written in one session asks for a piece of work in a later one: it becomes due by date or by a count of sessions, loads at session start as one short line, and ends as done, closed, put off or lapsed.

**Architecture:** Two new engine modules, `session_count.py` (a count of sessions per project and a total, in the data folder) and `reminders.py` (the record, its conditions and the summary line), both pure apart from file reads and writes. `mem.py` gains the commands and calls both from the session start text. A reminder is a Markdown file with YAML front matter in a `reminders` folder beside the memories, so no memory code ever loads one.

**Tech Stack:** Python 3 standard library and PyYAML, as the rest of `plugins/memory/engine`; pytest.

**Spec:** [the capture design](../specs/2026-11-21-memory-capture-design.md), decisions C40 to C45 and C50. Stage overview and research: [the B4 handoff](2026-11-22-memory-loaded-rules-and-reminders.md).

## Global Constraints

- Session start never fails and never waits: every new call in `cmd_session_index` is inside its own `try`, a failure adds no line, and the hook's 4 second limit holds (the count uses a lock wait of at most 0.5 s).
- The hook log holds no text and no path: numbers only.
- A reminder never appears in `mem search`, `mem memories`, `mem curate`, the "This project: N memories" count or the capture and corroboration passes. Its folder is `<memory folder>/reminders/`, which `records.load_memories` (non-recursive `*.md`) does not read.
- A write to the global scope passes the same refusals as `mem remember --global`: `_refuse_secret` and `_check_terms` on topic and body. A project write passes `_refuse_secret`.
- Every change to an existing reminder calls `records.log_before` first, so `mem reminder restore` can undo it.
- Exact values: topic at most 40 characters; summary line at most 300 characters; at most 4 topics in the line; at most 10 live reminders per scope; the owner question appears at 5 showings; efforts and risks are `low`, `medium`, `high`, default `medium`; repetition is `<N>d` or `<N>s` with N from 1 to 999.
- `mem` computes every date and count; no command takes a count of sessions as an absolute number.
- Handles print with the prefix `r:`.
- Text written into the project is English. Tests run with `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`.
- A change under `plugins/memory/` adds a line under `## [Unreleased]` of `plugins/memory/CHANGELOG.md`; the version does not change in this plan.

## Review Focus

- The data folder cannot be read or written (missing, read-only, lock held): the session start text still prints, no count is raised, a reminder that waits for sessions is not due, a reminder that waits for a date still works.
- The count file is reset or lower than a reminder's `armed_count`: "sessions since" is 0, never negative, and the reminder becomes due after its sessions from the reset.
- Two sessions start at the same moment: neither crashes; at most one increment is lost.
- A broken reminder file (bad YAML, unknown status): it is skipped at session start and listed with its error by `mem reminders --all`; the others still load.
- A topic or body with a secret or a forbidden term for the global scope: refused, nothing written.

---

### Task 1: Session count

**Files:**
- Create: `plugins/memory/engine/session_count.py`
- Modify: `plugins/memory/engine/mem.py` (`cmd_session_index`)
- Test: `plugins/memory/engine/tests/test_session_count.py`

**Interfaces:**
- Produces:
  - `COUNT_NAME = "sessions.json"`, `COUNTED_SOURCES = ("startup", "clear", "compact")`
  - `read(data: Path | None) -> dict` returns `{"total": int, "projects": {key: int}, "shown": {str: int}}`, zeros and empty maps when the file is missing or unreadable.
  - `count_for(state: dict, key: str | None) -> int`: the project's count for a key, the total for `None`.
  - `bump(data: Path | None, key: str | None, shown: Sequence[str] = ()) -> dict | None`: under an exclusive `fcntl.flock` on `<data>/sessions.lock` (non-blocking, retried for at most 0.5 s), adds 1 to `total`, to `projects[key]` when key is given, and to `shown[name]` for each name; writes through a temporary file and `os.replace`; returns the new state, or `None` when nothing was written. Never raises.
  - `forget_shown(data: Path | None, name: str) -> int`: removes `shown[name]` under the same lock and returns the value it had (0 when absent). Never raises.
- `cmd_session_index`: with `--hook` and `source` in `COUNTED_SOURCES`, the count is raised once (the call is made in Task 4 together with the showings; in this task call `bump(data_dir(os.environ), key)` with `key = records.project_key(project)` or `None`). The hook log line gains `"count": <total after the bump or null>`.

- [ ] **Step 1: Write the failing tests**

```python
def test_bump_counts_total_and_project(tmp_path):
    assert session_count.bump(tmp_path, "aaaaaaaaaaaa")["total"] == 1
    state = session_count.bump(tmp_path, "bbbbbbbbbbbb")
    assert state["total"] == 2 and state["projects"] == {"aaaaaaaaaaaa": 1, "bbbbbbbbbbbb": 1}
    assert session_count.count_for(state, "aaaaaaaaaaaa") == 1 and session_count.count_for(state, None) == 2

def test_bump_counts_showings_and_forget_returns_them(tmp_path):
    session_count.bump(tmp_path, None, ["project:k:x"]); session_count.bump(tmp_path, None, ["project:k:x"])
    assert session_count.read(tmp_path)["shown"] == {"project:k:x": 2}
    assert session_count.forget_shown(tmp_path, "project:k:x") == 2 and session_count.read(tmp_path)["shown"] == {}

def test_unwritable_or_missing_folder_returns_none_and_never_raises(tmp_path):
    assert session_count.bump(None, "k") is None
    locked = tmp_path / "ro"; locked.mkdir(); locked.chmod(0o500)   # a real permission, not a patch
    try: assert session_count.bump(locked, "k") is None
    finally: locked.chmod(0o700)

def test_a_broken_file_reads_as_zero(tmp_path):
    (tmp_path / "sessions.json").write_text("{not json")
    assert session_count.read(tmp_path) == {"total": 0, "projects": {}, "shown": {}}

def test_a_held_lock_gives_up_within_a_second(tmp_path):   # hold flock on sessions.lock in the test, then bump
    ...  # asserts bump(...) is None and took under 1.0 s

@pytest.mark.parametrize("source,raised", [("startup", 1), ("clear", 1), ("compact", 1), ("resume", 0), (None, 0)])
def test_session_index_hook_raises_the_count_by_source(source, raised, monkeypatch, capsys):
    # feed {"cwd": <tmp project>, "source": source} on stdin to mem.main(["session-index", "--hook"])
    ...  # asserts read(data)["total"] == raised, and the last hook log line has "count" == (raised or None)

def test_session_index_without_hook_raises_nothing(...): ...
```

- [ ] **Step 2: Run them and see them fail** — `uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests/test_session_count.py -q`; expected: import error for `session_count`.
- [ ] **Step 3: Implement `session_count.py` and the call in `cmd_session_index`**, inside its own `try` so the printed text is unchanged by any failure. Values that are not non-negative integers in the file read as 0.
- [ ] **Step 4: Run the file's tests, then `test_core.py` and `test_plugin_shell.py`** (they cover the session start text); expected: all pass.
- [ ] **Step 5: Commit** — `feat(memory): count sessions per project at session start`

### Task 2: The reminder record

**Files:**
- Create: `plugins/memory/engine/reminders.py`
- Test: `plugins/memory/engine/tests/test_reminders.py`

**Interfaces:**
- Consumes: `records.slug_of`, `records.log_before`, `records._split` (front matter), `session_count.count_for`.
- Produces:
  - `FOLDER = "reminders"`, `TOPIC_LIMIT = 40`, `LIVE_LIMIT = 10`, `LEVELS = ("low", "medium", "high")`, `STATUSES = ("active", "done", "closed")`.
  - `@dataclass Reminder`: `scope, path, handle, topic, body, created: date | None, status, armed_count: int, after: date | None, in_sessions: int | None, until: date | None, every: str | None, effort, risk, done_note: str | None, closed_reason: str | None, ended: date | None, shown_at_end: int | None, times_done: int, error: str | None`.
  - `folder_of(memory_folder: Path) -> Path` (`memory_folder / FOLDER`).
  - `load(memory_folder: Path | None, scope: str) -> list[Reminder]`: one per `*.md`, a broken file as a `Reminder` with `error` set, never raising.
  - `write(memory_folder: Path, scope: str, *, topic, body, today, count: int, after=None, in_sessions=None, until=None, every=None, effort="medium", risk="medium") -> Reminder`: validates (`ValueError` with a one-line message), creates the file exclusively with a handle from `records.slug_of(topic)` and a `-2`, `-3` suffix on a clash.
  - `parse_every(text: str) -> tuple[int, str]` (`"30d" -> (30, "d")`), `ValueError` otherwise.
  - `is_live(r, today) -> bool`: no error, status `active`, and `until` is `None` or not before today.
  - `is_due(r, today, count: int) -> bool`: live, `after` is `None` or not after today, and `in_sessions` is `None` or `max(0, count - r.armed_count) >= r.in_sessions`.
  - `sessions_since(r, count: int) -> int`: `max(0, count - r.armed_count)`.
  - `done(r, today, count, note: str, shown: int) -> Reminder`, `close(r, today, reason: str, shown: int) -> Reminder`, `snooze(r, today, count, *, sessions: int | None, until: date | None) -> Reminder`: each logs before, rewrites the file and returns the new record. `done` on a record with `every`: stays `active`, `times_done + 1`, `armed_count = count`, and `Nd` sets `after = today + N days` with `in_sessions = None`, `Ns` sets `in_sessions = N` with `after = None`; without `every`: status `done`, `ended = today`, `done_note`, `shown_at_end = shown`. `close`: status `closed`, `ended`, `closed_reason`, `shown_at_end`. `snooze`: exactly one of the two arguments, sets `armed_count = count` and that one condition, clears the other.

Front matter keys are the field names; dates in ISO form; the body is the text after the front matter. Unknown keys are kept on rewrite.

- [ ] **Step 1: Write the failing tests**

```python
T = datetime.date(2026, 11, 22)

def test_written_with_no_condition_is_due_at_once(tmp_path):
    r = reminders.write(tmp_path, "project", topic="review the docs", body="Check links.", today=T, count=7)
    assert r.handle == "review-the-docs" and r.armed_count == 7 and reminders.is_due(r, T, 7)
    assert reminders.load(tmp_path, "project")[0].topic == "review the docs"
    assert not list(tmp_path.glob("*.md"))          # nothing in the memory folder itself

def test_waits_for_sessions_then_is_due(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=7, in_sessions=3)
    assert not reminders.is_due(r, T, 9) and reminders.is_due(r, T, 10) and reminders.sessions_since(r, 10) == 3

def test_a_count_lower_than_armed_reads_as_zero(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=50, in_sessions=2)
    assert reminders.sessions_since(r, 3) == 0 and not reminders.is_due(r, T, 3)

def test_waits_for_a_date_and_lapses_after_until(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0,
                        after=T + datetime.timedelta(days=2), until=T + datetime.timedelta(days=5))
    assert not reminders.is_due(r, T, 0) and reminders.is_due(r, T + datetime.timedelta(days=2), 0)
    assert not reminders.is_live(r, T + datetime.timedelta(days=6))

def test_done_ends_a_single_one_and_rearms_a_recurring_one(tmp_path):
    one = reminders.write(tmp_path, "project", topic="once", body="b", today=T, count=1)
    assert reminders.done(one, T, 4, "Fixed the links.", 2).status == "done"
    rec = reminders.write(tmp_path, "project", topic="studies", body="b", today=T, count=1, every="30d")
    again = reminders.done(rec, T, 4, "Nothing new.", 1)
    assert again.status == "active" and again.after == T + datetime.timedelta(days=30) and again.times_done == 1
    by_sessions = reminders.done(reminders.write(tmp_path, "project", topic="s", body="b", today=T, count=1, every="10s"), T, 4, "n", 0)
    assert by_sessions.in_sessions == 10 and by_sessions.armed_count == 4 and by_sessions.after is None

def test_every_change_is_logged_before(tmp_path):   # the .curation-log in the reminders folder gains one entry per done, close, snooze
    ...

@pytest.mark.parametrize("bad", [dict(topic=""), dict(topic="x" * 41), dict(body=""), dict(effort="huge"), dict(risk="none"),
                                 dict(every="0d"), dict(every="3w"), dict(in_sessions=0), dict(until=T - datetime.timedelta(days=1))])
def test_write_refuses(bad, tmp_path): ...            # ValueError, no file written

def test_a_broken_file_loads_with_its_error_and_hides_nothing(tmp_path): ...
def test_snooze_takes_exactly_one_condition(tmp_path): ...
def test_unknown_front_matter_keys_survive_a_rewrite(tmp_path): ...
```

- [ ] **Step 2: Run them and see them fail** — expected: import error for `reminders`.
- [ ] **Step 3: Implement `reminders.py`.** `after` later than `until` is refused at write.
- [ ] **Step 4: Run the file's tests**; expected: all pass.
- [ ] **Step 5: Commit** — `feat(memory): reminder records with date and session conditions`

### Task 3: Commands

**Files:**
- Modify: `plugins/memory/engine/mem.py` (new `cmd_remind`, `cmd_reminders`, `cmd_reminder`; `build_parser`)
- Test: `plugins/memory/engine/tests/test_reminder_commands.py`

**Interfaces:**
- Consumes: Task 1 and Task 2; `_refuse_secret`, `_check_terms`, `records.project_root`, `records.project_dir`, `records.project_key`, `records.memories_root`, `data_dir`, `records.last_log_entry`, `records.restore`.
- Produces (exit code 0 on success, 2 on a refusal with one line on stderr starting `mem:`):
  - `mem remind "<topic>" --body TEXT [--after YYYY-MM-DD] [--in-sessions N] [--until YYYY-MM-DD] [--every Nd|Ns] [--effort L] [--risk L] [--global]` prints `r:<handle>\t<scope>\t<when it is due, in words>`. Refuses when the scope already holds 10 live reminders (`mem: 10 reminders are live in this scope: finish or close one first (mem reminders)`), and outside a project without `--global`.
  - `mem reminders [--global] [--all] [--stats]`: without `--global` lists the project's and the global ones. Due ones first, each with handle, topic, effort, risk, sessions since it was armed, showings, and its body; then the waiting ones with what they wait for; then, when at least one is due, this line verbatim: `Low effort and low risk: do the work after the current task and say so. Otherwise name it to the owner and propose it before starting. Then: mem reminder done <handle> --note "<what was done>", or snooze, or close.` `--all` adds ended, lapsed and broken ones. With nothing to list: `No reminders.`
  - `--stats` prints one line per ending kind with a count and the median `shown_at_end`: `done 4 (median 1 showing)`, `closed`, `lapsed` (count only), and `live N`.
  - `mem reminder show <handle>`, `done <handle> --note TEXT`, `close <handle> --reason TEXT`, `snooze <handle> (--sessions N | --until YYYY-MM-DD)`, `restore <handle>`. A handle is accepted with or without `r:`, looked up in the project first, then the global scope; `--global` restricts to the global scope. `done` and `close` read the showings with `session_count.forget_shown` and pass them on. The showings key is `f"{scope}:{project key or 'global'}:{handle}"`, produced by one function `_reminder_key(r, project)` that Task 4 reuses.
- The count passed to `write`, `done` and `snooze` is `session_count.count_for(session_count.read(data), key)` with the project's key for a project reminder and `None` for a global one.

- [ ] **Step 1: Write the failing tests** — through `mem.main([...])` with `MEM_PROJECT` and `MEM_MEMORIES` set as `conftest.py` and `test_quarantine.py` do.

```python
def test_remind_then_reminders_lists_it_due(project, capsys):
    assert mem.main(["remind", "review the docs", "--body", "Check every link."]) == 0
    assert capsys.readouterr().out.startswith("r:review-the-docs\tproject\t")
    assert mem.main(["reminders"]) == 0
    out = capsys.readouterr().out
    assert "r:review-the-docs" in out and "Check every link." in out and "Low effort and low risk:" in out

def test_in_sessions_waits_until_the_count_moves(project, capsys):
    mem.main(["remind", "refactor bins", "--body", "b", "--in-sessions", "2"])
    mem.main(["reminders"]); assert "waits for 2 sessions" in capsys.readouterr().out
    bump_twice(); mem.main(["reminders"]); assert "Low effort and low risk:" in capsys.readouterr().out

def test_the_eleventh_live_reminder_is_refused(project, capsys): ...          # exit 2, the message above, 10 files
def test_global_write_refuses_a_secret_and_a_forbidden_term(gfolder, capsys): ...   # nothing written
def test_done_needs_a_note_and_ends_it(project, capsys): ...                  # then `reminders` prints "No reminders."
def test_done_on_a_recurring_one_keeps_it_waiting(project, capsys): ...
def test_close_then_restore_brings_it_back(project, capsys): ...
def test_snooze_by_sessions_and_by_date(project, capsys): ...
def test_stats_reports_endings_and_median_showings(project, capsys): ...
def test_reminders_do_not_reach_search_memories_or_curate(project, gfolder, capsys):
    mem.main(["remind", "zebra migration", "--body", "zebra"]); mem.main(["remind", "zebra global", "--body", "zebra", "--global"])
    capsys.readouterr()
    for argv in (["search", "--scope", "memories", "zebra"], ["memories"], ["memories", "--global"], ["curate"], ["curate", "--global"]):
        mem.main(argv); assert "zebra" not in capsys.readouterr().out
def test_check_accepts_a_store_whose_memories_hold_a_reminders_folder(hub_root, capsys): ...   # mem check exits as before
def test_unknown_handle_and_outside_a_project(capsys): ...                   # exit 2 each
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the three commands and their parser entries.** "When it is due, in words": `due now`, `waits for N sessions`, `waits until <date>`, with `; ends <date>` and `; repeats every <N> days|sessions` appended when set.
- [ ] **Step 4: Run the file's tests and `test_core.py`**; expected: all pass.
- [ ] **Step 5: Commit** — `feat(memory): mem remind, mem reminders and mem reminder`

### Task 4: The line at session start

**Files:**
- Modify: `plugins/memory/engine/reminders.py` (`summary_line`), `plugins/memory/engine/mem.py` (`session_index`, `cmd_session_index`)
- Test: `plugins/memory/engine/tests/test_reminder_line.py`

**Interfaces:**
- Produces:
  - `LINE_LIMIT = 300`, `TOPICS_SHOWN = 4`, `ASK_AFTER = 5`.
  - `reminders.summary_line(due: Sequence[tuple[Reminder, int, int]], waiting: int) -> str | None`: each tuple is (reminder, sessions since, showings including this one). `None` when `due` is empty. Order: most showings first, then most sessions since, then handle. Form:
    `Reminders: 3 due (refactor the capture bins, 6 sessions; review the docs, 2 sessions, ask the owner: keep or close; new studies, 14 sessions; +1 more); 2 waiting. After the current task: mem reminders.`
    `1 session` in the singular; `, ask the owner: keep or close` only when showings are at least 5; `; N waiting` only when N > 0; `+N more` when more than 4 are due. When the text is over 300 characters, topics are removed from the end (raising `+N more`) until it fits.
  - `session_index(..., reminder: str | None = None)`: the line goes after the rule lines and before `notice`, and is never dropped by the 1500 character limit (the project rows give way).
  - `cmd_session_index`: loads the project's and the global reminders, builds the line from the counts *as they will be after this start*, and with `--hook` and a counted source makes the single `session_count.bump(data, key, shown=[keys of the due ones])` call that replaces Task 1's call. Without `--hook`, or with another source, it reads counts and showings and raises nothing. The hook log line gains `"due": <number due>`.
- Consumes: `_reminder_key` from Task 3.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_due_reminder_adds_no_line(project, capsys): ...       # one waiting only: the text has no "Reminders:"
def test_line_names_topics_sessions_and_waiting(project, capsys):
    # 2 due (one written 3 counted starts ago), 1 waiting
    ...; assert "Reminders: 2 due (" in out and "3 sessions" in out and "; 1 waiting. After the current task: mem reminders." in out
def test_the_fifth_showing_asks_the_owner(project, capsys): ...   # five hook starts; the fifth text holds "ask the owner: keep or close"
def test_showings_rise_only_on_counted_hook_starts(project, capsys): ...   # plain `session-index` and source "resume" leave shown unchanged
def test_line_stays_within_300_characters_with_ten_due_long_topics(project, capsys): ...   # and ends with "+N more"
def test_the_line_survives_the_text_limit(project, capsys): ...   # many long project memories, --list 50: "Reminders:" still present, text <= 1500
def test_a_broken_reminder_or_an_unreadable_data_folder_keeps_the_text(project, capsys): ...   # text printed, rules lines present
def test_done_resets_the_showings(project, capsys): ...           # after done on a recurring one, the next due showing counts from 1
def test_the_real_hook_script_with_only_mem_store(tmp_path):
    # subprocess: plugins/memory/hooks/session-index.sh with env HOME=tmp, MEM_STORE=<store with mem-store.yaml>, MEM_DATA=tmp/data,
    # no MEM_MEMORIES, no MEM_PROJECT, cwd a git project holding one due reminder and the store holding one global due reminder;
    # stdin {"cwd": ..., "source": "compact"}
    ...; assert "Reminders: 2 due" in out and json.loads(last_line_of(data / "hooks" / "log.jsonl"))["due"] == 2
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** The global reminders folder is found with `records.global_memories_root(os.environ)` when `memories` is `None`, as the background commands do since 0.4.1.
- [ ] **Step 4: Run the whole suite in the background** (`uv run --with pytest --with pyyaml pytest plugins/memory/engine/tests -q`, about 4 minutes); expected: all pass, 5 skipped.
- [ ] **Step 5: Commit** — `feat(memory): due reminders as one line at session start`

### Task 5: Skill text and documentation

**Files:**
- Modify: `plugins/memory/skills/memory/SKILL.md` (a `## Reminders` section before `## Not while working`; the `description` line is not touched), `plugins/memory/README.md` (a `## Reminders` section after `## Curation`, and the limits table), `plugins/memory/CHANGELOG.md` (`## [Unreleased]`, `### Added`), `docs/adr/0023-*.md` (append `### Stage B4, first release: reminders`), `docs/superpowers/plans/2026-11-17-memory-plugin.md` (state table and "Current state and where to resume"), the Phases row B4 of the spec.
- Test: `python3 scripts/validate.py` and `claude plugin validate .`

**Interfaces:**
- Consumes: the commands and exact strings of Tasks 3 and 4.

- [ ] **Step 1: `SKILL.md`, at most 14 lines.** It says: when to write one (work that belongs to a later session: a finding deferred from a review, an item left open, a periodic check; not something to do in this session, and not a fact, which is a memory); the command with one example per condition; give `--effort` and `--risk` honestly because they decide whether a later session starts by itself; when the session start text shows `Reminders:`, finish the current task, run `mem reminders`, and follow the rule it prints; end every reminder you act on with `done --note`, `snooze` or `close --reason`; never leave one to be shown again.
- [ ] **Step 2: README section.** What a reminder is and is not; the commands as a table; the line with its limits; the four endings; the session count (what raises it, where it lives); limits: a reset count delays session reminders, two simultaneous starts may lose one count, the line shows at most 4 topics, nothing runs in the background, no measure yet of reminders acted on.
- [ ] **Step 3: CHANGELOG entry**, written for users, naming the three commands and that nothing changes for a store without reminders.
- [ ] **Step 4: ADR 0023 section.** Decisions C40 to C45 by reference, the research sources from the handoff by reference, and kill criteria: the prompt text of the skill ships unmeasured; revisit when `mem reminders --stats` shows, over at least 10 ended reminders, a median of more than 3 showings before `done`, or more closed for "never acted on" than done.
- [ ] **Step 5: State tables, then run `python3 scripts/port.py --check`, `python3 scripts/validate.py`, `claude plugin validate .`**; expected: all exit 0.
- [ ] **Step 6: Commit** — `docs(memory): reminders in the skill, README, changelog and ADR 0023`

---

## After the tasks

- [ ] End-to-end scenario on an isolated home and store: write three reminders (now, in 2 sessions, recurring by date), run the real hook script for `startup`, `compact` and `resume`, read the text and `sessions.json`, act on each (`done`, `snooze`, `close`, `restore`), read `--stats`.
- [ ] One run with a real model session in the scenario: a session started with a due low-effort, low-risk reminder and an unrelated small task; read whether it ran `mem reminders` after the task and ended the reminder. Record the trace's outcome in ADR 0023 as observed, one run.
- [ ] Narrow reviews in parallel (code of the two modules; the commands against this plan; docs against code), then the fixes.
- [ ] Release only with the owner's word (version, changelog date, `validate.py --release`, PR `dev` to `main`).

## Known limits

Filled in by the pre-mortem and at the end of execution.
