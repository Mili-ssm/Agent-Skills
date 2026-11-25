"""promptkit.fragments: marked blocks rendered from shared/fragments/<id>.md."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write

from promptkit import fragments as fr
from promptkit.fragments import FragmentError, find_unmarked, render, strip_markers

FRAGS = {"rule": "Never guess.", "greet": "Hello {{name}}."}


def block(body: str, fid: str = "rule", attrs: str = "") -> str:
    return f"<!-- shared:{fid}{attrs} -->\n{body}\n<!-- /shared:{fid} -->"


def test_render_fills_block() -> None:
    out = render(f"intro\n{block('stale')}\noutro\n", FRAGS)
    assert out == f"intro\n{block('Never guess.')}\noutro\n"


def test_render_is_idempotent() -> None:
    once = render(f"a\n{block('')}\nb\n", FRAGS)
    assert render(once, FRAGS) == once


def test_params_fill_placeholders() -> None:
    out = render(block("", "greet", ' name="Ana"'), FRAGS)
    assert "Hello Ana." in out


def test_missing_param_fails() -> None:
    with pytest.raises(FragmentError, match="name"):
        render(block("", "greet"), FRAGS)


def test_unused_param_fails() -> None:
    with pytest.raises(FragmentError, match="extra"):
        render(block("", "rule", ' extra="x"'), FRAGS)


def test_unknown_id_fails() -> None:
    with pytest.raises(FragmentError, match="nope"):
        render(block("", "nope"), FRAGS)


def test_unclosed_marker_fails() -> None:
    with pytest.raises(FragmentError, match="unclosed"):
        render("<!-- shared:rule -->\ntext\n", FRAGS)
    with pytest.raises(FragmentError, match="mismatch"):
        render("<!-- shared:rule -->\n<!-- /shared:greet -->\n", FRAGS)


def test_markers_in_code_fence_ignored() -> None:
    text = f"```\n{block('stale')}\n```\n"
    assert render(text, FRAGS) == text


def test_nested_fence_four_backticks() -> None:
    text = f"````\n```\n{block('stale')}\n````\n{block('stale')}\n"
    out = render(text, FRAGS)
    assert out.endswith(block("Never guess.") + "\n")
    assert out.startswith(f"````\n```\n{block('stale')}\n````\n")


def test_tilde_fence() -> None:
    text = f"~~~\n{block('stale')}\n~~~\n"
    assert render(text, FRAGS) == text


def test_unclosed_fence() -> None:
    text = f"```\n{block('stale')}\n"
    assert render(text, FRAGS) == text


def test_strip_markers_keeps_content() -> None:
    assert strip_markers(f"a\n{block('body')}\nb\n") == "a\nbody\nb\n"


def make_root(root: Path, agent: str, verbatim: str | None = None) -> None:
    head = f"verbatim-in: {verbatim}\n" if verbatim else ""
    write(root / "shared" / "fragments" / "rule.md", f"{head}Never guess.\n")
    write(root / "plugins" / "p" / "agents" / "a.md", agent)


def test_check_reports_hand_edit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_root(tmp_path, f"---\n---\n{block('Never guess!')}\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 1
    assert "plugins/p/agents/a.md: block 'rule' differs from shared/fragments/rule.md" in capsys.readouterr().out


def test_shared_text_outside_block_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_root(tmp_path, "Intro. Never guess.\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 1
    assert "plugins/p/agents/a.md: text of 'rule' outside a block" in capsys.readouterr().out
    assert find_unmarked(block("Never guess.") + "\n", {"rule": "Never guess."}) == []
    assert find_unmarked("x {{a}}", {"p": "x {{a}}"}) == []


def test_verbatim_in_mismatch_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_root(tmp_path, f"{block('Never guess.')}\n", verbatim="user-config/policy.md")
    write(tmp_path / "user-config" / "policy.md", "Always guess.\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 1
    assert "user-config/policy.md" in capsys.readouterr().out
    write(tmp_path / "user-config" / "policy.md", "Rules: Never guess.\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 0


def test_render_command_rewrites_files(tmp_path: Path) -> None:
    make_root(tmp_path, f"{block('stale')}\n")
    assert fr.main(["--root", str(tmp_path)]) == 0
    assert (tmp_path / "plugins/p/agents/a.md").read_text() == f"{block('Never guess.')}\n"
    assert fr.main(["--check", "--root", str(tmp_path)]) == 0


def test_missing_folder_means_no_fragments(tmp_path: Path) -> None:
    assert fr.check(tmp_path) == []


def test_validate_check_fragments_reads_root(mini_repo: Path) -> None:
    import validate

    errors: list[str] = []
    validate.check_fragments(errors)
    assert errors == []
    write(mini_repo / "shared" / "fragments" / "rule.md", "Never guess.\n")
    write(mini_repo / "plugins" / "memory" / "agents" / "x.md", f"{block('Never guess!')}\n")
    validate.check_fragments(errors)
    assert errors == ["plugins/memory/agents/x.md: block 'rule' differs from shared/fragments/rule.md"]
