import io
import sys

import mem

ARGV = ["new", "knowledge", "--slug", "body-note", "--claim", "A claim about bodies.",
        "--topics", "biology", "--confidence", "low", "--level", "beginner", "--origin", "research"]
GOOD = "## Claim\n\nIt holds.\n\n## Evidence\n\n- Experience (anonymized): seen.\n\n## Applies when\n\nAlways.\n\n## Does not apply when\n\nNever.\n"
NOTE = "knowledge/biology/body-note.md"


def new(root, *extra):
    return mem.main(["--root", str(root), *ARGV, *extra])


def test_body_file_replaces_template_and_reports_no_problems(hub_root, tmp_path, capsys):
    body = tmp_path / "body.md"
    body.write_text(GOOD, encoding="utf-8")
    assert new(hub_root, "--body-file", str(body)) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == NOTE
    assert "check:" not in captured.err
    text = (hub_root / NOTE).read_text(encoding="utf-8")
    assert text.endswith("---\n" + GOOD) and "TODO(hub)" not in text
    assert mem.check(hub_root) == []


def test_body_file_reports_problems_of_the_new_note_only(hub_root, tmp_path, capsys):
    (hub_root / "literature/computing/2017-vaswani-attention.md").write_text("broken", encoding="utf-8")
    body = tmp_path / "b.txt"
    body.write_text("## Claim\n\nOnly a claim.\n", encoding="utf-8")
    assert new(hub_root, "--body-file", str(body)) == 0
    err = capsys.readouterr().err.splitlines()
    assert err[0].startswith("check: ") and err[0].endswith(f" problems in {NOTE}:")
    problems = [line for line in err[1:] if line.startswith(f"{NOTE}:")]
    assert len(problems) == int(err[0].split()[1]) > 0
    assert not any(line.startswith("literature/") for line in err)


def test_body_from_standard_input(hub_root, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(GOOD))
    assert new(hub_root, "--body-file", "-") == 0
    assert "It holds." in (hub_root / NOTE).read_text(encoding="utf-8")


def test_body_refusals_create_nothing(hub_root, tmp_path, monkeypatch, capsys):
    for name, text in {"empty": " \n\n", "fence": "---\nclaim: x\n---\n## Claim\n"}.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        assert new(hub_root, "--body-file", str(path)) == 1
    assert new(hub_root, "--body-file", str(tmp_path / "missing")) == 1
    tty = io.StringIO(GOOD)
    tty.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", tty)
    assert new(hub_root, "--body-file", "-") == 1
    assert capsys.readouterr().err.count("hub.py: ") == 4
    assert not (hub_root / NOTE).exists()


def test_without_body_file_output_is_unchanged(hub_root, capsys):
    assert new(hub_root) == 0
    assert "check:" not in capsys.readouterr().err
    assert "TODO(hub)" in (hub_root / NOTE).read_text(encoding="utf-8")


def test_body_from_standard_input_is_normalized_like_a_file(hub_root, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("﻿" + GOOD.replace("\n", "\r\n")))
    assert new(hub_root, "--body-file", "-") == 0
    assert (hub_root / NOTE).read_text(encoding="utf-8").endswith("---\n" + GOOD)
