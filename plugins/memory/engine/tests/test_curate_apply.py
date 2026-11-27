"""`mem curate apply --safe`: only the merges and attaches the code can prove safe run; each is undone by restore."""

import io
import subprocess

import mem
import pytest
from test_curation import put

RC_USAGE = 2
NOTE_BODY = (
    "## Claim\n\nShort recall.\n\n## Evidence\n\nSee the part.\n\n## Applies when\n\nAlways.\n\n"
    "## Does not apply when\n\nNever.\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))
    return root / ".memory"


@pytest.fixture
def run(hub_root, capsys, monkeypatch):
    def go(lines, *argv):
        monkeypatch.setattr("sys.stdin", io.StringIO(lines))
        code = mem.main(["--root", str(hub_root), *argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return go


def body(tmp_path, text, name):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def make_notes(hub_root, tmp_path, capsys, names):
    """A synthesis `attention` whose part `part` cites the first note only; every name is a loose knowledge note."""
    for slug in names:
        assert (
            mem.main([
                "--root",
                str(hub_root),
                "new",
                "knowledge",
                "--slug",
                slug,
                "--claim",
                f"Claim {slug}",
                "--topics",
                "ml",
                "--confidence",
                "low",
                "--level",
                "basic",
                "--origin",
                "experience",
                "--body-file",
                body(tmp_path, NOTE_BODY, f"{slug}.md"),
            ])
            == 0
        )
    assert (
        mem.main([
            "--root",
            str(hub_root),
            "synthesis",
            "new",
            "--title",
            "Attention",
            "--topics",
            "ml",
            "--slug",
            "attention",
            "--summary-file",
            body(tmp_path, "Summary.\n", "s.md"),
        ])
        == 0
    )
    src = f"Sources: [n](../knowledge/computing/{names[0]}.md)"
    for sec in ("part", "other"):
        assert (
            mem.main([
                "--root",
                str(hub_root),
                "synthesis",
                "add",
                "s:attention",
                "--section",
                sec,
                "--body-file",
                body(tmp_path, f"Text.\n\n{src}\n", f"{sec}.md"),
            ])
            == 0
        )
    capsys.readouterr()


def test_merge_runs_only_for_equal_claims_in_one_scope(project, run, tmp_path, monkeypatch):
    put(project, "dup-a", "Use the cache.", observed=1)
    put(project, "dup-b", "  use   THE cache ", observed=2)
    put(project, "num-a", "Pool holds 10 items.")
    put(project, "num-b", "Pool holds 20 items.")
    put(project, "old", "Gone claim.", status="forgotten")
    put(project, "old2", "Gone claim.")
    (tmp_path / "gmem").mkdir()
    put(tmp_path / "gmem", "dup-g", "Use the cache.")
    lines = (
        "# a comment\n\nmerge m:dup-a m:dup-b\nmerge m:num-a m:num-b\nmerge m:old m:old2\n"
        "merge m:dup-a m:dup-g\nforget m:dup-a\n"
    )
    code, out, _ = run(lines, "curate", "apply", "--safe")
    rows = out.splitlines()
    assert code == 0
    assert rows[0] == "applied\tmerge m:dup-a m:dup-b"
    assert rows[1] == "left\tmerge m:num-a m:num-b\tthe claims are not equal"
    assert rows[2].startswith("left\tmerge m:old m:old2\t") and "forgotten" in rows[2]
    assert rows[3].startswith("left\tmerge m:dup-a m:dup-g\t")
    assert rows[4] == "left\tforget m:dup-a\tnot a safe action (forget)"
    assert rows[5] == "applied 1, left 4"
    assert "status: superseded" in (project / "dup-b.md").read_text()
    assert (project / "num-b.md").read_text().count("status: active") == 1
    code, out, _ = run("", "restore", "m:dup-b")
    assert code == 0 and "status: active" in (project / "dup-b.md").read_text()
    run("", "restore", "m:dup-a")
    assert "observed: 1" in (project / "dup-a.md").read_text()


def test_attach_needs_the_sources_link_and_a_free_note(project, run, hub_root, tmp_path, capsys):
    make_notes(hub_root, tmp_path, capsys, ["cited-note", "uncited-note"])
    note = hub_root / "knowledge" / "computing" / "cited-note.md"
    before = note.read_bytes()
    lines = (
        "attach cited-note s:attention#part\nattach uncited-note s:attention#part\n"
        "attach cited-note s:attention#other\nattach nothing s:attention#part\n"
    )
    code, out, _ = run(lines, "curate", "apply", "--safe")
    rows = out.splitlines()
    assert code == 0
    assert rows[0] == "applied\tattach cited-note s:attention#part"
    assert (
        rows[1]
        == "left\tattach uncited-note s:attention#part\tthe part's Sources line does not link the note"
    )
    assert "already part of" in rows[2]  # attached by the first line: a note belongs to one part
    assert rows[3] == "left\tattach nothing s:attention#part\tno such note"
    assert rows[4] == "applied 1, left 3"
    assert "part_of" in note.read_text(encoding="utf-8")
    assert mem.main(["--root", str(hub_root), "check"]) == 0
    capsys.readouterr()
    assert run("", "restore", "cited-note")[0] == 0
    assert note.read_bytes() == before


def test_note_already_part_of_another_synthesis_is_left(project, run, hub_root, tmp_path, capsys):
    make_notes(hub_root, tmp_path, capsys, ["cited-note"])
    assert (
        mem.main([
            "--root",
            str(hub_root),
            "synthesis",
            "attach",
            "cited-note",
            "s:attention#other",
        ])
        == 0
    )
    capsys.readouterr()
    _, out, _ = run("attach cited-note s:attention#part\n", "curate", "apply", "--safe")
    assert out.splitlines()[0].startswith(
        "left\tattach cited-note s:attention#part\tthe note is already part of"
    )


def test_apply_refuses_without_safe_and_a_malformed_file_applies_nothing(project, run, tmp_path):
    put(project, "dup-a", "Use the cache.")
    put(project, "dup-b", "Use the cache.")
    assert run("merge m:dup-a m:dup-b\n", "curate", "apply")[0] == RC_USAGE
    code, out, err = run("merge m:dup-a m:dup-b\nmerge m:dup-a\n", "curate", "apply", "--safe")
    assert code == RC_USAGE and not out and "malformed" in err
    assert "status: active" in (project / "dup-b.md").read_text()
    path = tmp_path / "actions.txt"
    path.write_text("merge m:dup-a m:dup-b\n", encoding="utf-8")
    code, out, _ = run("", "curate", "apply", "--safe", "--from", str(path))
    assert code == 0 and out.endswith("applied 1, left 0\n")
