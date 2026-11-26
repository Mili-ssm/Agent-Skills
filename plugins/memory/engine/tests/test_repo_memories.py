"""Memories a repository commits carry no owner trust: `owner_confirmed` in a tracked file does not count (task 3a)."""

import datetime
import subprocess
from pathlib import Path

import corroborate
import mem
import pytest
import records

K1, K2 = "0123456789ab", "ba9876543210"
SHORT = "Retries need idempotency keys on payment calls."
TODAY = datetime.date.today()


def git(root, *args):
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(root))
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))
    return root


def lesson(sessions=0, confirmed=True):
    args = [
        "remember",
        "--kind",
        "lesson",
        "--claim",
        "Payment retries need idempotency keys.",
        "--origin",
        "transcript",
        "--weight",
        "light",
        "--reach",
        "project",
        "--short",
        SHORT,
    ]
    for name, key in list(zip("ab", (K1, K2), strict=True))[:sessions]:
        args += ["--source", f"session {name} project {key}"]
    assert mem.main(args) == 0
    folder = records.project_dir(Path(__import__("os").environ["MEM_PROJECT"]))
    (m,) = records.load_memories(folder, "project")
    if confirmed:
        records.update(m, TODAY, owner_confirmed=TODAY.isoformat())
    return folder


def index(capsys):
    capsys.readouterr()
    assert mem.main(["session-index"]) == 0
    return capsys.readouterr().out


def commit(repo):
    git(repo, "add", "-f", ".memory")
    git(repo, "commit", "-q", "-m", "memories")


def test_tracked_lesson_with_forged_owner_confirmation_is_not_vouched(repo, capsys):
    lesson(sessions=0)
    commit(repo)
    out = index(capsys)
    assert "the user vouched for it" not in out and SHORT not in out


def test_tracked_established_lesson_loads_marked_from_repository(repo, capsys):
    lesson(sessions=2)
    commit(repo)
    out = index(capsys)
    (line,) = [x for x in out.splitlines() if SHORT in x]
    assert line.endswith("(from repository)") and "vouched" not in line


def test_untracked_owner_confirmed_lesson_keeps_its_mark(repo, capsys):
    lesson(sessions=0)
    out = index(capsys)
    (line,) = [x for x in out.splitlines() if SHORT in x]
    assert line.endswith("(the user vouched for it)")


def test_submodule_memory_folder_counts_as_tracked(repo, tmp_path, capsys):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    (other / "README").write_text("x")
    git(other, "add", "README")
    git(other, "commit", "-q", "-m", "x")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(other), ".memory")
    lesson(sessions=2)
    assert records.tracked_memories(repo) is None
    out = index(capsys)
    (line,) = [x for x in out.splitlines() if SHORT in x]
    assert line.endswith("(from repository)")


def test_uninitialized_submodule_gitlink_counts_as_tracked(repo, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    (other / "README").write_text("x")
    git(other, "add", "README")
    git(other, "commit", "-q", "-m", "x")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(other), ".memory")
    git(repo, "commit", "-q", "-m", "submodule")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True)
    assert not (clone / ".memory" / ".git").exists()  # not checked out: only the gitlink
    assert records.tracked_memories(clone) is None


def test_corroboration_ignores_repository_lessons(repo, tmp_path):
    lesson(sessions=2, confirmed=False)
    assert [x.id for x in corroborate.collect([repo], None, TODAY)] == [
        "p1:payment-retries-need-idempotency-keys"
    ]
    commit(repo)
    assert corroborate.collect([repo], None, TODAY) == []


def test_fill_job_never_picks_a_tracked_lesson(repo):
    mem.main([
        "remember",
        "--kind",
        "lesson",
        "--claim",
        "Payment retries need idempotency keys.",
        "--origin",
        "transcript",
        "--weight",
        "light",
        "--reach",
        "project",
        "--source",
        f"session a project {K1}",
        "--source",
        f"session b project {K2}",
    ])
    before = corroborate.fill_candidates([repo], None, TODAY)
    commit(repo)
    assert before and corroborate.fill_candidates([repo], None, TODAY) == []
    assert corroborate.fill_records([repo], None) == []
    assert corroborate.reword_candidates([repo], None, TODAY, {}, every=True) == []


def test_reword_job_never_picks_a_tracked_lesson(repo):
    lesson(sessions=2, confirmed=False)
    before = corroborate.reword_candidates([repo], None, TODAY, {}, every=True)
    commit(repo)
    assert before and corroborate.reword_candidates([repo], None, TODAY, {}, every=True) == []
