import datetime
import subprocess

import pytest

import mem
import project_syntheses as ps

TODAY = datetime.date(2026, 11, 17)
STALE_HEAD = "-- project syntheses: possibly stale --"
NONE_HEAD = "-- project syntheses: none yet --"


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, check=True,
                   capture_output=True)


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
            "observed: 1\nstatus: active\n---\n", encoding="utf-8")


def add(tmp_path, name="organization", heading="Where the engine lives"):
    body = tmp_path / "body.txt"
    body.write_text("The engine lives in src.", encoding="utf-8")
    assert mem.main(["project-synthesis", "add", name, heading, "--paths", "src/", "--body-file", str(body)]) == 0


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
    expected = (f"{NONE_HEAD}\n5 active memories and no project synthesis: organize them "
                "(see the memory-curation skill).\n")
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


SENTENCE = ("Project syntheses: {} (read: mem show p:<name>; each part says whether its files changed since it "
            "was written).")


def first_line(proj):
    return mem.session_index(None, proj / ".memory", None, TODAY).split("\n")[0]


def test_session_index_names_existing_syntheses_only(proj, tmp_path):
    memories(proj, 2)
    add(tmp_path, "pending", "Open work")
    add(tmp_path, "organization")
    line = first_line(proj)
    assert line.endswith(" " + SENTENCE.format("p:organization p:pending"))
    assert "This project: 2 memories." in line


def test_session_index_names_them_in_a_project_without_memories(proj, tmp_path):
    add(tmp_path, "plans", "Next")
    assert first_line(proj) == mem._INDEX_HEAD + " " + SENTENCE.format("p:plans")


def test_session_index_without_syntheses_is_unchanged(proj):
    memories(proj, 2)
    assert first_line(proj) == mem._INDEX_HEAD + " This project: 2 memories."
    assert "Project syntheses" not in mem.session_index(None, proj / ".memory", None, TODAY, limit=5)


def test_the_list_stays_within_its_1500_characters(proj, tmp_path):
    memories(proj, 30)
    for name in ps.NAMES:
        add(tmp_path, name)
    text = mem.session_index(None, proj / ".memory", None, TODAY, limit=30)
    assert len(text) <= 1500 and "Project syntheses: p:organization p:plans p:pending p:conventions" in text


def test_session_index_runs_no_git(proj, tmp_path, monkeypatch):
    add(tmp_path)

    def fail(*a, **k):
        raise AssertionError("git was called")
    monkeypatch.setattr(ps.subprocess, "run", fail)
    assert "p:organization" in first_line(proj)
