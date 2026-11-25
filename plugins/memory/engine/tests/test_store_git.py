import fcntl
import multiprocessing
import os
import subprocess
import threading
import time
from pathlib import Path

import auto_state
import mem
import pytest
import store_git

REAL_RUN = subprocess.run
SHORT_LOCK_WAIT = 0.2
EXIT_USAGE = 2
TRIMMED_LINES = 3
UNDONE_LINE = 4
HELD_BACK_COUNT = 2
LAST_COMMITS = 2


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch, tmp_path):
    """No real git config: not the owner's identity, signing or hooks."""
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "gitconfig").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def git(cwd, *args):
    return REAL_RUN(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


def commits(store):
    return git(store, "log", "--format=%s").splitlines()


@pytest.fixture
def store(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "store"
    monkeypatch.setenv("MEM_STORE", str(folder))
    assert mem.main(["init", str(folder)]) == 0
    capsys.readouterr()
    return folder


@pytest.fixture
def repo(store):
    store_git.init(store)
    return store


def remember(claim="Retries need idempotency keys."):
    return mem.main(["remember", "--global", "--kind", "lesson", "--claim", claim])


HANDLE = "m:retries-need-idempotency-keys"


def test_init_writes_identity_ignores_and_commits_everything_present(store):
    (store / "memories" / "early.md").write_text("early\n", encoding="utf-8")
    store_git.init(store)
    assert git(store, "config", "user.name").strip() == "mem"
    assert git(store, "config", "user.email").strip() == "mem@localhost"
    tracked = git(store, "ls-files").splitlines()
    assert "memories/early.md" in tracked and "mem-store.yaml" in tracked
    assert not git(store, "status", "--porcelain")


def test_the_ignore_rules_keep_local_files_out(repo):
    for rel in (
        ".curation-log",
        "syntheses/.curation-log",
        ".sources/a.pdf",
        "research/x/data/big.csv",
        ".note.md.tmp",
        "node_modules/p.js",
    ):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    (repo / "knowledge" / "kept.md").write_text("kept\n", encoding="utf-8")
    store_git.commit_if_changed(repo, "mem test")
    assert git(repo, "ls-files").splitlines().count("knowledge/kept.md") == 1
    tracked = git(repo, "ls-files")
    for name in (".curation-log", ".sources", "data/big.csv", ".tmp", "node_modules"):
        assert name not in tracked


def test_files_over_the_limit_are_not_staged(repo, monkeypatch):
    monkeypatch.setattr(store_git, "MAX_FILE_BYTES", 100)
    (repo / "knowledge" / "huge.bin").write_bytes(b"x" * 500)
    (repo / "knowledge" / "small.md").write_text("small\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem test")
    tracked = git(repo, "ls-files")
    assert "small.md" in tracked and "huge.bin" not in tracked


def test_nothing_changed_gives_none(repo):
    assert store_git.commit_if_changed(repo, "mem noop") is None


def test_the_short_id_is_returned(repo):
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert (
        store_git.commit_if_changed(repo, "mem a")
        == git(repo, "rev-parse", "--short", "HEAD").strip()
    )


def test_a_stale_index_lock_is_removed_and_a_fresh_one_is_not(repo):
    lock = repo / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 700
    os.utime(lock, (old, old))
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem a")
    assert not lock.exists()
    lock.write_text("", encoding="utf-8")  # fresh: another git may be running
    (repo / "knowledge" / "b.md").write_text("b\n", encoding="utf-8")
    reasons = []
    assert store_git.commit_if_changed(repo, "mem b", report=reasons.append) is None
    assert reasons and lock.exists()


def test_a_held_lock_is_waited_for(repo, monkeypatch):
    fd = os.open(repo / ".git" / store_git.LOCK_NAME, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    threading.Timer(0.5, lambda: os.close(fd)).start()
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem a")


def _commit_in_process(store, name):
    (Path(store) / "knowledge" / f"{name}.md").write_text(name + "\n", encoding="utf-8")
    store_git.commit_if_changed(Path(store), f"mem {name}")


def test_concurrent_commits_both_land(repo):
    procs = [
        multiprocessing.Process(target=_commit_in_process, args=(str(repo), n)) for n in ("a", "b")
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    tracked = git(repo, "ls-files")
    assert "knowledge/a.md" in tracked and "knowledge/b.md" in tracked
    assert not git(repo, "status", "--porcelain")


def test_constants_match_mem():
    assert store_git.LOCAL_DIRS == mem._LOCAL_DIRS
    assert store_git.MAX_FILE_BYTES == mem.MAX_FILE_BYTES


def test_an_oversized_ignored_file_does_not_break_the_commit(repo, monkeypatch):
    monkeypatch.setattr(store_git, "MAX_FILE_BYTES", 100)
    (repo / "syntheses" / ".curation-log").write_bytes(b"x" * 500)
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem a")
    assert ".curation-log" not in git(repo, "ls-files")


@pytest.mark.parametrize(
    "argv",
    [
        ["remember", "--global", "--kind", "lesson", "--claim", "No git here."],
        ["session-index"],
        ["signal"],
    ],
)
def test_no_command_runs_git_by_itself(repo, monkeypatch, argv):
    def refuse(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            raise AssertionError(f"git was run: {cmd}")
        return REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))
    mem.main(argv)
    assert git(repo, "log", "--format=%s").splitlines() == ["mem history init"]


def test_a_git_failure_is_reported_not_raised(repo, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, *a, **k: (_ for _ in ()).throw(FileNotFoundError("git"))
    )
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    reasons = []
    assert store_git.commit_if_changed(repo, "mem a", report=reasons.append) is None
    assert reasons and "git" in reasons[0]


def test_every_call_disables_signing_and_hooks(repo, monkeypatch):
    seen = []

    def spy(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            seen.append(cmd)
        return REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    store_git.commit_if_changed(repo, "mem a")
    assert seen
    for cmd in seen:
        assert "commit.gpgsign=false" in cmd and "core.hooksPath=" in cmd


def test_a_lock_of_five_minutes_is_not_removed(repo):
    lock = repo / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 300
    os.utime(lock, (old, old))
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem a", report=lambda r: None) is None
    assert lock.exists()


def test_inherited_git_variables_do_not_redirect_the_commit(repo, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "wrong-index"))
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem a")
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert "knowledge/a.md" in git(repo, "ls-files")
    assert not (tmp_path / "wrong-index").exists()


def test_init_keeps_an_existing_gitignore_and_appends_the_missing_lines(store):
    (store / ".gitignore").write_text("mine/\n.sources/", encoding="utf-8")
    store_git.init(store)
    lines = (store / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["mine/", ".sources/"]
    assert lines.count(".sources/") == 1
    assert ".curation-log" in lines and "node_modules/" in lines


# ---- history commands, commit points, trimming ----

import datetime
import json


def aged(path, numbers, days=40):
    """Rewrite the `t` of the given 0-based lines of a curation log to `days` ago."""
    old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    lines = path.read_text(encoding="utf-8").split("\n")
    for n in numbers:
        entry = json.loads(lines[n])
        entry["t"] = old
        lines[n] = json.dumps(entry, ensure_ascii=False)
    path.write_text("\n".join(lines), encoding="utf-8")


def test_history_init_makes_a_repository_and_prints_the_first_commit(store, capsys):
    (store / "memories" / "early.md").write_text("early\n", encoding="utf-8")
    assert mem.main(["history", "init"]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == git(store, "rev-parse", "--short", "HEAD").strip()
    assert "memories/early.md" in git(store, "ls-files")


def test_history_init_accepts_a_store_argument(store, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MEM_STORE")
    assert mem.main(["history", "init", str(store)]) == 0
    assert store_git.is_repo(store)


def test_history_init_refuses_a_repository_and_a_read_only_folder(repo, tmp_path, capsys):
    assert mem.main(["history", "init"]) == EXIT_USAGE
    assert "already" in capsys.readouterr().err
    plain = tmp_path / "plain"
    plain.mkdir()
    assert mem.main(["history", "init", str(plain)]) == EXIT_USAGE
    assert "read-only" in capsys.readouterr().err
    assert not (plain / ".git").exists()


def test_history_lists_the_last_commits(repo, capsys):
    for name in ("a", "b", "c"):
        (repo / "knowledge" / f"{name}.md").write_text(name + "\n", encoding="utf-8")
        store_git.commit_if_changed(repo, f"mem {name}")
    capsys.readouterr()
    assert mem.main(["history", "-n", "2"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert (
        len(lines) == HELD_BACK_COUNT
        and lines[0].endswith(" mem c")
        and lines[1].endswith(" mem b")
    )
    assert datetime.date.today().isoformat() in lines[0]


def test_history_without_a_repository_is_an_error(store, capsys):
    assert mem.main(["history"]) == EXIT_USAGE
    assert "not a git repository" in capsys.readouterr().err


def test_history_commit_commits_with_the_message_or_says_nothing(repo, capsys):
    (repo / "scratch-a.txt").write_text("a\n", encoding="utf-8")
    capsys.readouterr()
    assert mem.main(["history", "commit", "-m", "by hand"]) == 0
    assert capsys.readouterr().out.strip() == git(repo, "rev-parse", "--short", "HEAD").strip()
    assert commits(repo)[0] == "by hand"
    assert mem.main(["history", "commit"]) == 0
    assert capsys.readouterr().out.strip() == "nothing to commit"


def test_history_commit_without_a_message_names_the_files(repo, capsys):
    (repo / "scratch-a.txt").write_text("a\n", encoding="utf-8")
    (repo / "scratch-b.txt").write_text("b\n", encoding="utf-8")
    assert mem.main(["history", "commit"]) == 0
    assert commits(repo)[0].startswith("manual commit ") and commits(repo)[0].endswith(": 2 files")


def test_history_commit_hook_is_silent_and_exit_0_when_git_fails(repo, monkeypatch, capsys):
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, *a, **k: (_ for _ in ()).throw(FileNotFoundError("git"))
    )
    capsys.readouterr()
    assert mem.main(["history", "commit", "--hook"]) == 0
    out = capsys.readouterr()
    assert not out.out and not out.err
    hooks = (Path(os.environ["MEM_DATA"]) / "hooks" / "log.jsonl").read_text(encoding="utf-8")
    assert '"hook": "session-end"' in hooks and '"failed": true' in hooks


def test_history_commit_hook_commits_a_session_end_message(repo, capsys):
    (repo / "scratch-a.txt").write_text("a\n", encoding="utf-8")
    assert mem.main(["history", "commit", "--hook"]) == 0
    assert commits(repo)[0].startswith("session end ") and commits(repo)[0].endswith(": 1 files")


def test_history_commit_hook_exits_0_without_a_store_or_a_repository(store, monkeypatch):
    assert mem.main(["history", "commit", "--hook"]) == 0  # a store that is not a repository
    monkeypatch.delenv("MEM_STORE")
    assert mem.main(["history", "commit", "--hook"]) == 0  # no store at all


def test_curate_done_commits_with_the_pass_message(repo, capsys):
    (repo / "scratch-a.txt").write_text("a\n", encoding="utf-8")
    (repo / "scratch-b.txt").write_text("b\n", encoding="utf-8")
    assert mem.main(["curate", "--done"]) == 0
    assert commits(repo)[0] == f"curation pass {datetime.date.today().isoformat()}: 2 files"
    assert not git(repo, "status", "--porcelain")


def test_curate_done_with_nothing_changed_makes_no_commit(repo):
    before = commits(repo)
    assert mem.main(["curate", "--done"]) == 0
    assert commits(repo) == before


def test_curate_done_in_a_store_without_git_trims_nothing(store):
    log = store / "memories" / ".curation-log"
    remember()
    mem.main(["forget", HANDLE, "--global", "--because", "x"])
    aged(log, [0])
    before = log.read_text(encoding="utf-8")
    assert mem.main(["curate", "--done"]) == 0
    assert log.read_text(encoding="utf-8") == before and not (store / ".git").exists()


def test_curate_done_trims_old_entries_in_every_store_log(repo):
    remember()
    mem.main(["forget", HANDLE, "--global", "--because", "x"])
    mem.main(["restore", HANDLE, "--global"])
    mem.main(["forget", HANDLE, "--global", "--because", "y"])
    log = repo / "memories" / ".curation-log"
    aged(log, [0, 1])
    for name in ("", "syntheses"):  # the other store logs
        other = repo / name / ".curation-log"
        other.write_text(
            json.dumps({"t": "2020-01-01T00:00:00Z", "action": "x", "handle": "s:y", "before": "b"})
            + "\n"
            + json.dumps({
                "t": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "action": "x",
                "handle": "s:y",
                "before": "b",
            })
            + "\n",
            encoding="utf-8",
        )
    assert mem.main(["curate", "--done"]) == 0
    lines = log.read_text(encoding="utf-8").split("\n")
    assert not lines[0] and not lines[1] and lines[2]  # line numbers stay
    for name in ("", "syntheses"):
        lines = (repo / name / ".curation-log").read_text(encoding="utf-8").split("\n")
        assert not lines[0] and json.loads(lines[1])["handle"] == "s:y"


def test_trim_leaves_a_project_log_alone(repo, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".memory").mkdir(parents=True)
    git(project, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(project))
    log = project / ".memory" / ".curation-log"
    log.write_text(
        json.dumps({"t": "2020-01-01T00:00:00Z", "action": "x", "handle": "m:y", "before": "b"})
        + "\n",
        encoding="utf-8",
    )
    before = log.read_text(encoding="utf-8")
    assert mem.main(["curate", "--done"]) == 0
    assert log.read_text(encoding="utf-8") == before


def test_nothing_is_trimmed_when_the_commit_fails(repo, monkeypatch):
    remember()
    mem.main(["forget", HANDLE, "--global", "--because", "x"])
    log = repo / "memories" / ".curation-log"
    aged(log, [0])
    before = log.read_text(encoding="utf-8")
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, *a, **k: (_ for _ in ()).throw(FileNotFoundError("git"))
    )
    assert mem.main(["curate", "--done"]) == 0
    assert log.read_text(encoding="utf-8") == before


def test_trim_keeps_unreadable_and_undated_lines(repo):
    log = repo / "memories" / ".curation-log"
    log.write_text("not json\n" + json.dumps({"action": "x"}) + "\n", encoding="utf-8")
    assert store_git.trim_logs(repo) == 0
    assert log.read_text(encoding="utf-8").startswith("not json\n")


def test_restore_still_works_on_the_entries_left_after_trimming(repo, capsys):
    remember()
    mem.main(["forget", HANDLE, "--global", "--because", "first"])  # line 0
    mem.main(["restore", HANDLE, "--global"])  # line 1, marker undoing 0
    mem.main(["forget", HANDLE, "--global", "--because", "second"])  # line 2
    mem.main(["restore", HANDLE, "--global"])  # line 3, marker undoing 2
    mem.main(["forget", HANDLE, "--global", "--because", "third"])  # line 4
    log = repo / "memories" / ".curation-log"
    aged(log, [0, 1, 2])
    assert store_git.trim_logs(repo) == TRIMMED_LINES
    capsys.readouterr()
    assert mem.main(["restore", HANDLE, "--global"]) == 0  # undoes line 4, not the blanked ones
    memory = next(repo.glob("memories/*.md"))
    assert "second" not in memory.read_text(encoding="utf-8") and "third" not in memory.read_text(
        encoding="utf-8"
    )
    assert json.loads(log.read_text(encoding="utf-8").split("\n")[5])["undone"] == UNDONE_LINE
    assert mem.main(["restore", HANDLE, "--global"]) != 0  # nothing left to undo


# ---- the automatic run's lock ----


def test_curate_done_skips_trimming_while_a_run_holds_the_lock(repo, tmp_path, monkeypatch):
    log = repo / "memories" / ".curation-log"
    remember()
    mem.main(["forget", HANDLE, "--global", "--because", "x"])
    aged(log, [0])
    before = log.read_text(encoding="utf-8")
    fd = auto_state.take_run_lock(auto_state.auto_dir(Path(os.environ["MEM_DATA"]), repo))
    assert fd is not None
    try:
        assert mem.main(["curate", "--done"]) == 0
        assert log.read_text(encoding="utf-8") == before
    finally:
        os.close(fd)
    assert mem.main(["curate", "--done"]) == 0
    assert log.read_text(encoding="utf-8") != before  # trimmed once the lock is free


def test_trimming_waits_for_nothing_when_the_commit_lock_is_busy(repo):
    remember()
    mem.main(["forget", HANDLE, "--global", "--because", "x"])
    log = repo / "memories" / ".curation-log"
    aged(log, [0])
    before = log.read_text(encoding="utf-8")
    fd = store_git._lock(repo)
    try:
        monkey = pytest.MonkeyPatch()
        monkey.setattr(store_git, "LOCK_WAIT", 0)
        try:
            assert store_git.trim_logs_locked(repo) == 0
        finally:
            monkey.undo()
        assert log.read_text(encoding="utf-8") == before
    finally:
        os.close(fd)
    assert store_git.trim_logs_locked(repo) == 1


# --- notes that fail `mem check` are held back (gap G1) ---

NOTE = """---
claim: {claim}
topics: [notes]
confidence: medium
level: intermediate
origin: literature
updated: 2026-11-07
---

## Claim

C.

## Evidence

E.
{tail}"""
FULL_TAIL = "\n## Applies when\n\nA.\n\n## Does not apply when\n\nB.\n"


def note(store, name, *, valid=True, claim=None):
    """Write a knowledge note (invalid: its last two headings are missing) and refresh the folder index."""
    folder = store / "knowledge" / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(
        NOTE.format(claim=claim or name, tail=FULL_TAIL if valid else ""), encoding="utf-8"
    )
    assert mem.main(["index"]) == 0
    return f"knowledge/notes/{name}.md"


def tracked(store):
    return git(store, "ls-files").splitlines()


def test_invalid_note_is_held_back(repo):
    good = note(repo, "good")
    bad = note(repo, "bad", valid=False)
    assert store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    assert good in tracked(repo) and bad not in tracked(repo)
    assert store_git.held_back(repo) == [bad]
    assert (repo / bad).exists()


def test_invalid_note_in_new_folder_is_held_back(repo):
    bad = note(repo, "bad", valid=False)  # knowledge/notes/ is untracked as a whole
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    assert bad not in tracked(repo) and store_git.held_back(repo) == [bad]


def test_fixed_note_is_committed_next_time(repo):
    bad = note(repo, "bad", valid=False)
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    note(repo, "bad")
    assert store_git.commit_if_changed(repo, "m2", validate=mem.invalid_changed(repo))
    assert bad in tracked(repo) and store_git.held_back(repo) == []
    assert not (repo / ".git" / "mem-held-back").exists()


def test_deleted_note_is_not_held_back(repo):
    gone = note(repo, "gone")
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    (repo / gone).unlink()
    assert mem.main(["index"]) == 0
    assert store_git.commit_if_changed(repo, "m2", validate=mem.invalid_changed(repo))
    assert gone not in tracked(repo) and store_git.held_back(repo) == []


def test_validator_error_commits_everything(repo, capsys):
    bad = note(repo, "bad", valid=False)
    warned, reported = [], []

    def broken(paths):
        raise RuntimeError("boom")

    assert store_git.commit_if_changed(
        repo, "m", validate=broken, warn=warned.append, report=reported.append
    )
    assert bad in tracked(repo) and len(warned) == 1 and "boom" in warned[0] and reported == []


def test_validator_exception_through_history_commit_exits_0(repo, monkeypatch, capsys):
    bad = note(repo, "bad", valid=False)

    def broken(store):
        def validate(paths):
            raise RuntimeError("boom")

        return validate

    monkeypatch.setattr(mem, "invalid_changed", broken)
    capsys.readouterr()
    assert mem.main(["history", "commit"]) == 0
    assert "boom" in capsys.readouterr().err and bad in tracked(repo)


def test_note_changed_during_check_is_held_back(repo):
    late = note(repo, "late")

    def validate(paths):
        (repo / late).write_text("changed while the check ran\n", encoding="utf-8")
        return []

    store_git.commit_if_changed(repo, "m", validate=validate)
    assert (
        late not in tracked(repo) and store_git.held_back(repo) == []
    )  # committed next time, not a check failure


def test_no_validator_keeps_old_behavior(repo):
    bad = note(repo, "bad", valid=False)
    assert store_git.commit_if_changed(repo, "m")
    assert bad in tracked(repo) and store_git.held_back(repo) == []


def test_held_back_file_written_when_nothing_else_staged(repo):
    bad = note(repo, "bad", valid=False)
    for rel in git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
        if rel != bad:
            git(repo, "add", rel)
            git(repo, "commit", "-q", "-m", "rest")
    # only the invalid note and files it drags along remain; hold everything that fails
    assert store_git.commit_if_changed(repo, "m", validate=list) is None
    assert store_git.held_back(repo) == [bad]


def test_valid_note_linking_held_back_note_is_committed(repo):
    bad = note(repo, "bad", valid=False)
    good = note(repo, "good")
    (repo / good).write_text(
        (repo / good).read_text(encoding="utf-8").replace("E.", "See [bad](bad.md).", 1),
        encoding="utf-8",
    )
    assert mem.main(["index"]) == 0
    assert store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    assert good in tracked(repo) and bad not in tracked(repo)


def test_history_commit_prints_held_back_paths(repo, capsys):
    bad = note(repo, "bad", valid=False)
    capsys.readouterr()
    assert mem.main(["history", "commit"]) == 0
    assert f"held back: {bad}" in capsys.readouterr().err


def test_held_back_rename_keeps_old_note_in_history(repo):
    old = note(repo, "old")
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    git(repo, "mv", old, "knowledge/notes/new.md")
    (repo / "knowledge/notes/new.md").write_text(
        NOTE.format(claim="new", tail=""), encoding="utf-8"
    )
    assert mem.main(["index"]) == 0
    store_git.commit_if_changed(repo, "m2", validate=mem.invalid_changed(repo))
    assert old in tracked(repo) and "knowledge/notes/new.md" not in tracked(repo)
    assert store_git.held_back(repo) == ["knowledge/notes/new.md"]


def test_note_in_stray_folder_is_held_back(repo):
    note(repo, "ok")
    stray = repo / "knowledge" / "notes" / "stray"
    stray.mkdir()
    (stray / "deep.md").write_text(NOTE.format(claim="deep", tail=FULL_TAIL), encoding="utf-8")
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    assert "knowledge/notes/stray/deep.md" not in tracked(repo)
    assert store_git.held_back(repo) == ["knowledge/notes/stray/deep.md"]


def test_lock_failure_prints_no_stale_held_paths(repo, capsys, monkeypatch):
    bad = note(repo, "bad", valid=False)
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    assert store_git.held_back(repo) == [bad]
    monkeypatch.setattr(store_git, "LOCK_WAIT", 0)
    fd = store_git._lock(repo)
    try:
        capsys.readouterr()
        assert mem.main(["history", "commit"]) == 1
    finally:
        os.close(fd)
    assert "held back:" not in capsys.readouterr().err


def test_unwritable_held_list_still_commits(repo):
    good = note(repo, "good")
    bad = note(repo, "bad", valid=False)
    (repo / ".git" / "mem-held-back").mkdir()  # a directory: writing the list fails
    warned = []
    assert store_git.commit_if_changed(
        repo, "m", validate=mem.invalid_changed(repo), warn=warned.append
    )
    assert good in tracked(repo) and bad not in tracked(repo) and warned


def test_a_lock_loser_leaves_the_holders_list_unchanged(repo, monkeypatch):
    monkeypatch.setattr(store_git, "LOCK_WAIT", SHORT_LOCK_WAIT)
    bad = note(repo, "bad", valid=False)
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    before = (repo / ".git" / "mem-held-back").read_text(encoding="utf-8")
    note(repo, "other")
    fd = store_git._lock(repo)
    try:
        assert (
            store_git.commit_if_changed(
                repo, "m2", report=lambda r: None, validate=mem.invalid_changed(repo)
            )
            is None
        )
    finally:
        os.close(fd)
    assert (repo / ".git" / "mem-held-back").read_text(encoding="utf-8") == before == f"{bad}\n"


def test_the_list_is_never_empty_or_partial_while_a_commit_runs(repo):
    first = note(repo, "bad1", valid=False)
    store_git.commit_if_changed(repo, "m", validate=mem.invalid_changed(repo))
    note(repo, "bad2", valid=False)
    seen = []
    real = mem.invalid_changed(repo)

    def validate(paths):
        seen.append(store_git.held_back(repo))  # between the gate's start and the write
        result = real(paths)
        seen.append(store_git.held_back(repo))  # the gate ran, the new list is not written yet
        return result

    store_git.commit_if_changed(repo, "m2", validate=validate)
    assert seen == [[first], [first]]
    assert len(store_git.held_back(repo)) == HELD_BACK_COUNT
    assert not [p for p in (repo / ".git").iterdir() if p.name.startswith("mem-held-back.")]


def test_history_commit_prints_no_stale_held_back_after_a_failed_run(repo, capsys, monkeypatch):
    note(repo, "bad", valid=False)
    assert mem.main(["history", "commit"]) == 0
    capsys.readouterr()
    note(repo, "more")
    monkeypatch.setattr(
        store_git, "_git", lambda *a, **k: (_ for _ in ()).throw(store_git.GitError("boom"))
    )
    assert mem.main(["history", "commit"]) == 1
    assert "held back:" not in capsys.readouterr().err
