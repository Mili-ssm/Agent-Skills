import multiprocessing
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

import mem
import store_git

REAL_RUN = subprocess.run


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
    return REAL_RUN(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def commits(store):
    out = git(store, "log", "--format=%s").splitlines()
    return out


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


def test_a_write_makes_one_commit_that_names_it(repo):
    before = len(commits(repo))
    assert remember() == 0
    log = commits(repo)
    assert len(log) == before + 1
    assert log[0] == "mem remember"
    assert git(repo, "status", "--porcelain") == ""


def test_two_writes_give_two_commits(repo):
    before = len(commits(repo))
    remember("First claim here.")
    remember("Second claim here.")
    assert len(commits(repo)) == before + 2


def test_forget_and_restore_commit(repo, capsys):
    remember()
    assert mem.main(["forget", HANDLE, "--global", "--because", "stale"]) == 0
    assert commits(repo)[0] == f"mem forget {HANDLE}"
    assert mem.main(["restore", HANDLE, "--global"]) == 0
    assert commits(repo)[0] == f"mem restore {HANDLE}"


def test_project_remember_does_not_commit_to_the_store(repo, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    git(project, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(project))
    before = commits(repo)
    assert mem.main(["remember", "--kind", "lesson", "--claim", "Only in the project."]) == 0
    assert commits(repo) == before


def test_the_message_never_holds_the_claim(repo):
    remember("A secret claim that must stay out of history.")
    assert "secret" not in "\n".join(commits(repo))
    assert "secret" not in git(repo, "log", "-1", "--format=%B")


def test_a_failing_command_makes_no_commit(repo):
    before = commits(repo)
    assert mem.main(["forget", "m:does-not-exist", "--global", "--because", "x"]) != 0
    assert commits(repo) == before


def test_a_store_without_git_is_untouched(store):
    assert remember() == 0
    assert not (store / ".git").exists()


def test_read_and_hook_commands_run_no_git(repo, monkeypatch, capsys):
    remember()

    def refuse(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            raise AssertionError(f"git was run: {cmd}")
        return REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", refuse)
    for argv in (["session-index"], ["search", "retries"], ["show", HANDLE], ["memories", "--global"],
                 ["stats"], ["curate"]):
        mem.main(argv)  # exit code irrelevant; only that git never ran
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))
    mem.main(["signal"])


@pytest.mark.parametrize("failure", ["raises", "nonzero", "missing"])
def test_a_git_failure_keeps_the_exit_code(repo, monkeypatch, capsys, failure):
    def broken(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            if failure == "raises":
                raise subprocess.TimeoutExpired(cmd, 10)
            if failure == "missing":
                raise FileNotFoundError("git")
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: boom")
        return REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", broken)
    assert remember() == 0
    assert "mem: history:" in capsys.readouterr().err


def test_a_git_failure_is_in_the_usage_log(repo, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: (_ for _ in ()).throw(FileNotFoundError("git"))
                        if cmd and cmd[0] == "git" else REAL_RUN(cmd, *a, **k))
    remember()
    log = (Path(os.environ["MEM_DATA"]) / "usage" / "log.jsonl").read_text(encoding="utf-8")
    assert '"cmd": "history"' in log


def test_every_call_disables_signing_and_hooks(repo, monkeypatch):
    seen = []

    def spy(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            seen.append(cmd)
        return REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    remember()
    assert seen
    for cmd in seen:
        assert "commit.gpgsign=false" in cmd and "core.hooksPath=" in cmd


def test_init_writes_identity_ignores_and_commits_everything_present(store):
    (store / "memories" / "early.md").write_text("early\n", encoding="utf-8")
    store_git.init(store)
    assert git(store, "config", "user.name").strip() == "mem"
    assert git(store, "config", "user.email").strip() == "mem@localhost"
    tracked = git(store, "ls-files").splitlines()
    assert "memories/early.md" in tracked and "mem-store.yaml" in tracked
    assert git(store, "status", "--porcelain") == ""


def test_the_ignore_rules_keep_local_files_out(repo):
    for rel in (".curation-log", "syntheses/.curation-log", ".sources/a.pdf", "research/x/data/big.csv",
                ".note.md.tmp", "node_modules/p.js"):
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
    assert store_git.commit_if_changed(repo, "mem a") == git(repo, "rev-parse", "--short", "HEAD").strip()


def test_a_stale_index_lock_is_removed_and_a_fresh_one_is_not(repo):
    lock = repo / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 120
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
    import fcntl
    fd = os.open(repo / ".git" / store_git.LOCK_NAME, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    threading.Timer(0.5, lambda: os.close(fd)).start()
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem a")


def _commit_in_process(store, name):
    (Path(store) / "knowledge" / f"{name}.md").write_text(name + "\n", encoding="utf-8")
    store_git.commit_if_changed(Path(store), f"mem {name}")


def test_concurrent_commits_both_land(repo):
    procs = [multiprocessing.Process(target=_commit_in_process, args=(str(repo), n)) for n in ("a", "b")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    tracked = git(repo, "ls-files")
    assert "knowledge/a.md" in tracked and "knowledge/b.md" in tracked
    assert git(repo, "status", "--porcelain") == ""


def test_constants_match_mem():
    assert store_git.LOCAL_DIRS == mem._LOCAL_DIRS
    assert store_git.MAX_FILE_BYTES == mem.MAX_FILE_BYTES


def test_an_oversized_ignored_file_does_not_break_the_commit(repo, monkeypatch):
    monkeypatch.setattr(store_git, "MAX_FILE_BYTES", 100)
    (repo / "syntheses" / ".curation-log").write_bytes(b"x" * 500)
    (repo / "knowledge" / "a.md").write_text("a\n", encoding="utf-8")
    assert store_git.commit_if_changed(repo, "mem a")
    assert ".curation-log" not in git(repo, "ls-files")
