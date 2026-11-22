import datetime
import importlib.machinery
import importlib.util
import os
import subprocess
from pathlib import Path

import mem
import records
import session_count
from reminder_fixtures import gfolder, project  # noqa: F401  (pytest fixtures)

BIN = Path(__file__).resolve().parents[2] / "bin" / "mem-synthesize"


def bump_twice(root):
    key = records.project_key(root)
    for _ in range(2):
        session_count.bump(Path(os.environ["MEM_DATA"]), key)


def files(root):
    folder = root / ".memory" / "reminders"
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def test_remind_then_reminders_lists_it_due(project, capsys):
    assert mem.main(["remind", "review the docs", "--body", "Check every link."]) == 0
    assert capsys.readouterr().out.split("\t")[:3] == ["r:review-the-docs", "project", "due now\n"]
    assert mem.main(["reminders"]) == 0
    out = capsys.readouterr().out
    assert "r:review-the-docs" in out and "Check every link." in out and "Low effort and low risk:" in out


def test_in_sessions_waits_until_the_count_moves(project, capsys):
    mem.main(["remind", "refactor bins", "--body", "b", "--in-sessions", "2"])
    mem.main(["reminders"])
    assert "waits for 2 sessions" in capsys.readouterr().out
    bump_twice(project)
    mem.main(["reminders"])
    assert "Low effort and low risk:" in capsys.readouterr().out


def test_in_days_is_computed_by_mem(project, capsys):
    assert mem.main(["remind", "later", "--body", "b", "--in-days", "3"]) == 0
    later = datetime.date.today() + datetime.timedelta(days=3)
    assert capsys.readouterr().out.split("\t")[2] == f"waits until {later.isoformat()}\n"
    assert f"after: '{later.isoformat()}'" in files(project)[0].read_text() or f"after: {later.isoformat()}" in files(project)[0].read_text()
    assert mem.main(["remind", "both", "--body", "b", "--in-days", "3", "--after", later.isoformat()]) == 2
    capsys.readouterr()


def test_the_first_reminder_in_a_git_project_is_excluded_from_git(tmp_path, monkeypatch, capsys):
    root = tmp_path / "gitproj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    monkeypatch.delenv("MEM_PROJECT")  # the project is resolved from the working directory
    monkeypatch.chdir(root)
    assert mem.main(["remind", "first", "--body", "b"]) == 0
    assert files(root)
    assert ".memory/" in (root / ".git" / "info" / "exclude").read_text()
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], check=True, capture_output=True, text=True)
    assert status.stdout == ""


def test_the_eleventh_live_reminder_is_refused(project, capsys):
    for i in range(10):
        assert mem.main(["remind", f"topic {i}", "--body", "b"]) == 0
    capsys.readouterr()
    assert mem.main(["remind", "one more", "--body", "b"]) == 2
    assert "mem: 10 reminders are live in this scope: finish or close one first (mem reminders)" in capsys.readouterr().err
    assert len(files(project)) == 10


def test_global_write_refuses_a_secret_and_a_forbidden_term(gfolder, capsys):
    assert mem.main(["remind", "keys", "--global", "--body", "token AKIAIOSFODNN7EXAMPLE here"]) == 4
    capsys.readouterr()
    records.ensure_terms_file(os.environ)
    forbidden = records.forbidden_file(os.environ)
    forbidden.write_text(forbidden.read_text() + "\nacmecorp\nsoft: softword\n", encoding="utf-8")
    assert mem.main(["remind", "acmecorp work", "--global", "--body", "b"]) == 4
    assert mem.main(["remind", "plain", "--global", "--body", "a softword inside"]) == 5
    capsys.readouterr()
    assert not (gfolder / "reminders").exists() or not list((gfolder / "reminders").glob("*.md"))
    assert mem.main(["remind", "plain", "--global", "--body", "a softword inside", "--owner-approved"]) == 0
    assert len(list((gfolder / "reminders").glob("*.md"))) == 1


def test_a_background_session_cannot_write_one(project, monkeypatch, capsys):
    monkeypatch.setenv("MEM_BACKGROUND", "1")
    assert mem.main(["remind", "nope", "--body", "b"]) == 2
    assert files(project) == []


def test_the_plugins_own_sessions_set_mem_background():
    loader = importlib.machinery.SourceFileLoader("mem_synthesize_bin", str(BIN))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("mem_synthesize_bin", loader))
    loader.exec_module(module)
    assert module.session_env(Path("/x"))["MEM_BACKGROUND"] == "1"


def test_outside_a_project_and_without_a_global_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MEM_PROJECT")
    monkeypatch.chdir(tmp_path)  # not a git repository
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert mem.main(["remind", "x", "--body", "b"]) == 2
    assert mem.main(["remind", "x", "--global", "--body", "b"]) == 2  # no MEM_MEMORIES, no store
    capsys.readouterr()


def test_the_commands_work_with_no_store(project, capsys):
    assert "MEM_STORE" not in os.environ
    assert mem.main(["remind", "free", "--body", "b"]) == 0
    assert mem.main(["reminders"]) == 0
    assert "r:free" in capsys.readouterr().out
    assert mem.main(["reminders", "--global"]) == 0
    assert "No reminders." in capsys.readouterr().out
