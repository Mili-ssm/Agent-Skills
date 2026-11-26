import datetime
import subprocess

import mem
import project_syntheses as ps
import pytest

TODAY = datetime.date(2026, 11, 17)
STALE_HEAD = "-- project syntheses: possibly stale --"
NONE_HEAD = "-- project syntheses: none yet --"


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("a = 1\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    monkeypatch.setenv("MEM_PROJECT", str(root))
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))
    monkeypatch.chdir(root)
    return root


WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]


def memories(root, n):
    folder = root / ".memory"
    folder.mkdir(exist_ok=True)
    for i in range(n):
        (folder / f"m{i}.md").write_text(
            f"---\nkind: decision\nclaim: The {WORDS[i % 8]} {WORDS[(i * 3 + 1) % 8]} job{i} ships {WORDS[(i + 5) % 8]}{i}.\ncreated: '{datetime.date.today().isoformat()}'\n"
            "observed: 1\nstatus: active\n---\n",
            encoding="utf-8",
        )


def add(tmp_path, name="organization", heading="Where the engine lives"):
    body = tmp_path / "body.txt"
    body.write_text("The engine lives in src.", encoding="utf-8")
    assert (
        mem.main([
            "project-synthesis",
            "add",
            name,
            heading,
            "--paths",
            "src/",
            "--body-file",
            str(body),
        ])
        == 0
    )


def run(capsys, *argv):
    code = mem.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_curate_lists_a_possibly_stale_part(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    (proj / "src" / "a.py").write_text("a = 2\n")
    git(proj, "commit", "-qam", "second")
    expected = f"{STALE_HEAD}\np:organization#where-the-engine-lives\t{ps.describe(ps.CHANGED)}\n"
    for args in (("curate",), ("curate", "--project")):
        assert run(capsys, *args) == (0, expected, "")
    for args in (("curate", "--global"), ("curate", "--notes")):
        assert STALE_HEAD not in run(capsys, *args)[1]


def test_curate_prints_nothing_for_a_fresh_part(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    assert run(capsys, "curate") == (0, "", "")


def test_curate_asks_to_organize_five_memories_without_a_synthesis(proj, capsys):
    memories(proj, 5)
    expected = (
        f"{NONE_HEAD}\n5 active memories and no project synthesis: organize them "
        "(see the memory-curation skill).\n"
    )
    assert run(capsys, "curate") == (0, expected, "")
    assert run(capsys, "curate", "--project") == (0, expected, "")
    assert NONE_HEAD not in run(capsys, "curate", "--global")[1]


def test_curate_stays_quiet_with_four_memories(proj, capsys):
    memories(proj, 4)
    assert run(capsys, "curate") == (0, "", "")


def test_curate_does_not_ask_when_a_synthesis_exists(proj, tmp_path, capsys):
    memories(proj, 5)
    add(tmp_path)
    capsys.readouterr()
    assert run(capsys, "curate") == (0, "", "")


def test_session_index_text_ignores_project_syntheses(proj, tmp_path):
    memories(proj, 2)
    before = mem.session_index(None, proj / ".memory", None, TODAY, limit=5)
    for name in ps.NAMES:
        add(tmp_path, name)
    assert mem.session_index(None, proj / ".memory", None, TODAY, limit=5) == before
    assert "Project syntheses" not in before


def test_session_index_runs_no_git(proj, tmp_path, monkeypatch):
    add(tmp_path)

    def fail(*a, **k):
        raise AssertionError("git was called")

    monkeypatch.setattr(ps.subprocess, "run", fail)
    assert mem.session_index(None, proj / ".memory", None, TODAY)


UNREADABLE_HEAD = "-- project syntheses: unreadable --"


def test_curate_lists_a_broken_file_and_still_shows_the_others(proj, tmp_path, capsys):
    add(tmp_path)
    (proj / ".memory" / "syntheses" / "plans.md").write_text(
        "no frontmatter here\n", encoding="utf-8"
    )
    (proj / "src" / "a.py").write_text("a = 2\n")
    capsys.readouterr()
    code, out, err = run(capsys, "curate")
    assert code == 0
    lines = out.splitlines()
    assert UNREADABLE_HEAD in lines
    row = lines[lines.index(UNREADABLE_HEAD) + 1]
    assert row.startswith("syntheses/plans.md\t") and "frontmatter" in row
    assert STALE_HEAD in lines and "p:organization#where-the-engine-lives" in out
    assert not err


def test_session_index_survives_a_broken_file(proj):
    memories(proj, 2)
    (proj / ".memory" / "syntheses").mkdir(exist_ok=True)
    (proj / ".memory" / "syntheses" / "plans.md").write_text("garbage\n", encoding="utf-8")
    assert "Project syntheses" not in mem.session_index(None, proj / ".memory", None, TODAY)


def test_curate_checks_freshness_in_the_sessions_linked_worktree(
    proj, tmp_path, monkeypatch, capsys
):
    add(tmp_path)
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "synthesis")
    linked = tmp_path / "linked"
    git(proj, "worktree", "add", "-q", "-b", "feature", str(linked))
    monkeypatch.delenv("MEM_PROJECT")
    monkeypatch.chdir(proj)
    capsys.readouterr()
    assert STALE_HEAD not in run(capsys, "curate")[1]
    (linked / "src" / "a.py").write_text("a = 2\n")
    git(linked, "commit", "-q", "-am", "change in the linked worktree")
    monkeypatch.chdir(linked)
    out = run(capsys, "curate")[1]
    assert STALE_HEAD in out and "p:organization#where-the-engine-lives" in out
