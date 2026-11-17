import json
from pathlib import Path

import pytest
from conftest import usage_log_path

import mem
import records

ARGS = ["remember", "--global", "--kind", "lesson"]


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


@pytest.fixture
def terms_file(tmp_path):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True)
    return f


def remember(*extra, claim="Retries need keys."):
    return mem.main([*ARGS, "--claim", claim, *extra])


def test_parse_term_classes():
    assert records.parse_term("# note") is None and records.parse_term("   ") is None
    assert records.parse_term("Acme", 3) == records.Term(3, "Acme", False, None)
    assert records.parse_term("soft: Zeta ", 4) == records.Term(4, "Zeta", True, None)
    assert records.parse_term("soft[lesson]: Zeta", 5) == records.Term(5, "Zeta", True, "lesson")


def test_comments_are_ignored_and_the_line_number_counts_them(gfolder, terms_file, capsys):
    terms_file.write_text("# acme is only a comment here\n\nzeta\n")
    assert remember(claim="Acme retries.") == 0
    assert remember(claim="Zeta retries.") == 4
    assert "line 3 of the forbidden-terms list" in capsys.readouterr().err


def test_soft_term_exits_5_until_the_owner_approves(gfolder, terms_file, capsys):
    terms_file.write_text("soft: Zeta\n")
    assert remember(claim="Zeta retries.") == 5
    err = capsys.readouterr().err.strip()
    assert err == ('mem: the text mentions "Zeta" (a soft term): ask the owner whether this may be written to the '
                   "global scope; if they agree, repeat with --owner-approved.")
    assert not gfolder.exists() or not list(gfolder.glob("*.md"))
    assert remember("--owner-approved", claim="Zeta retries.") == 0
    assert any(gfolder.glob("*.md"))
    entries = [json.loads(l) for l in usage_log_path().read_text().splitlines()]
    assert entries[-1]["owner_approved"] is True and "Zeta" not in json.dumps(entries)


def test_owner_approval_does_not_pass_hard_terms_or_secrets(gfolder, terms_file):
    terms_file.write_text("soft: Zeta\nacme\n")
    assert remember("--owner-approved", claim="Zeta and Acme.") == 4
    assert remember("--owner-approved", "--context", "password = hunter2hunter2", claim="Zeta retries.") == 4


def test_soft_term_with_a_kind_applies_only_to_that_kind(gfolder, terms_file):
    terms_file.write_text("soft[decision]: Zeta\n")
    assert remember(claim="Zeta retries.") == 0           # a lesson
    assert mem.main(["remember", "--global", "--kind", "decision", "--claim", "Zeta wins."]) == 5


def test_project_memories_skip_the_term_check(tmp_path, monkeypatch, terms_file):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.setenv("MEM_PROJECT", str(repo))
    terms_file.write_text("acme\nsoft: zeta\n")
    assert mem.main(["remember", "--kind", "lesson", "--claim", "Acme and zeta."]) == 0


def test_reason_for_a_global_memory_checks_soft_terms(gfolder, terms_file, tmp_path, capsys, monkeypatch):
    assert remember() == 0
    capsys.readouterr()
    terms_file.write_text("soft: zeta\n")
    assert mem.main(["forget", "m:retries-need-keys", "--global", "--because", "Zeta said so"]) == 5
    assert "(a soft term)" in capsys.readouterr().err
    assert mem.main(["forget", "m:retries-need-keys", "--global", "--because", "Zeta said so", "--owner-approved"]) == 0


def test_terms_list_add_remove(tmp_path, capsys):
    terms = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    assert mem.main(["terms", "list"]) == 0 and capsys.readouterr().out == ""
    assert mem.main(["terms", "add", "Acme Corp"]) == 0
    assert mem.main(["terms", "add", "Zeta", "--soft"]) == 0
    assert mem.main(["terms", "add", "Zeta", "--soft", "--kind", "lesson"]) == 0
    capsys.readouterr()
    assert terms.read_text().startswith("#")
    assert mem.main(["terms", "list"]) == 0
    assert capsys.readouterr().out == "hard\tAcme Corp\nsoft\tZeta\nsoft[lesson]\tZeta\n"
    assert mem.main(["terms", "add", "Zeta", "--soft"]) == 0 and capsys.readouterr().out == "already listed\n"
    assert terms.read_text().count("Zeta") == 2
    assert mem.main(["terms", "add", "Zeta"]) == 0  # the hard class is another one
    capsys.readouterr()
    assert mem.main(["terms", "remove", "Zeta"]) == 0
    capsys.readouterr()
    assert mem.main(["terms", "list"]) == 0 and capsys.readouterr().out == "hard\tAcme Corp\n"
    assert terms.read_text().startswith("#")  # comments stay
    assert mem.main(["terms", "remove", "Zeta"]) == 2 and "no term" in capsys.readouterr().err


def test_terms_commands_need_no_store(capsys):
    assert mem.main(["terms", "add", "x"]) == 0


def test_terms_add_refuses_a_misparsed_term(capsys):
    assert mem.main(["terms", "add", "# x"]) == 2
    assert mem.main(["terms", "add", "soft: x"]) == 2


def test_init_creates_the_terms_file_once(tmp_path, capsys):
    terms = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    assert mem.main(["init", str(tmp_path / "store")]) == 0
    assert len(terms.read_text().splitlines()) == 3
    terms.write_text("mine\n")
    assert mem.main(["init", str(tmp_path / "store2")]) == 0
    assert terms.read_text() == "mine\n"
