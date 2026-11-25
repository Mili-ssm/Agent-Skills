"""promptkit.fragments: marked blocks rendered from shared/fragments/<id>.md."""

from __future__ import annotations

import os
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


def test_unclosed_fence_hiding_a_marker_fails() -> None:
    with pytest.raises(FragmentError, match="unclosed code fence opened before a shared marker"):
        render(f"```\n{block('stale')}\n", FRAGS)


def test_unclosed_fence_without_marker_is_fine() -> None:
    text = "```\ncode\n"
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
    make_root(tmp_path, "Intro.\nNever guess.\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 1
    assert "plugins/p/agents/a.md: text of 'rule' outside a block" in capsys.readouterr().out
    assert find_unmarked(block("Never guess.") + "\n", {"rule": "Never guess."}) == []
    assert find_unmarked("x {{a}}", {"p": "x {{a}}"}) == []


def test_verbatim_in_mismatch_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_root(tmp_path, f"{block('Never guess.')}\n", verbatim="user-config/policy.md")
    write(tmp_path / "user-config" / "policy.md", "Always guess.\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 1
    assert "user-config/policy.md" in capsys.readouterr().out
    write(tmp_path / "user-config" / "policy.md", "Rules:\nNever guess.\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 0


def test_render_command_rewrites_files(tmp_path: Path) -> None:
    make_root(tmp_path, f"{block('stale')}\n")
    assert fr.main(["--root", str(tmp_path)]) == 0
    assert (tmp_path / "plugins/p/agents/a.md").read_text() == f"{block('Never guess.')}\n"
    assert fr.main(["--check", "--root", str(tmp_path)]) == 0


def test_missing_folder_means_no_fragments(tmp_path: Path) -> None:
    assert fr.check(tmp_path) == []
    assert fr.load_fragments(tmp_path / "shared" / "fragments") == {}


def test_validate_check_fragments_reads_root(mini_repo: Path) -> None:
    import validate

    errors: list[str] = []
    validate.check_fragments(errors)
    assert errors == []
    write(mini_repo / "shared" / "fragments" / "rule.md", "Never guess.\n")
    write(mini_repo / "plugins" / "memory" / "agents" / "x.md", f"{block('Never guess!')}\n")
    validate.check_fragments(errors)
    assert errors == ["plugins/memory/agents/x.md: block 'rule' differs from shared/fragments/rule.md"]


def test_readme_is_not_a_fragment(tmp_path: Path) -> None:
    write(tmp_path / "shared" / "fragments" / "README.md", "Docs.\n")
    write(tmp_path / "shared" / "fragments" / "rule.md", "Never guess.\n")
    assert fr.load_fragments(tmp_path / "shared" / "fragments") == {"rule": "Never guess."}
    assert "README" not in fr.verbatim_targets(tmp_path / "shared" / "fragments")


def test_indented_marker_is_a_marker() -> None:
    text = "  <!-- shared:rule -->\nstale\n   <!-- /shared:rule -->\n"
    assert render(text, FRAGS) == "  <!-- shared:rule -->\nNever guess.\n   <!-- /shared:rule -->\n"
    assert fr.drifted(text, FRAGS) == ["rule"]
    # 4+ spaces is code at top level but a marker inside a list item: ambiguous, so it is an error
    code = "    <!-- shared:rule -->\nstale\n    <!-- /shared:rule -->\n"
    with pytest.raises(FragmentError, match="unrecognized shared marker"):
        render(code, FRAGS)


def test_check_reports_unclosed_fence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_root(tmp_path, f"```\n{block('stale')}\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 1
    assert "plugins/p/agents/a.md: unclosed code fence opened before a shared marker" in capsys.readouterr().out


def test_render_preserves_crlf(tmp_path: Path) -> None:
    make_root(tmp_path, "")
    path = tmp_path / "plugins/p/agents/a.md"
    path.write_bytes(f"intro\n{block('stale')}\n".replace("\n", "\r\n").encode())
    assert fr.main(["--root", str(tmp_path)]) == 0
    assert path.read_bytes() == f"intro\n{block('Never guess.')}\n".replace("\n", "\r\n").encode()
    assert fr.main(["--check", "--root", str(tmp_path)]) == 0


def test_substring_is_not_an_unmarked_copy() -> None:
    frags = {"g": "guess."}
    assert find_unmarked("I guess.\n", frags) == []
    assert find_unmarked("intro\nguess.\noutro\n", frags) == ["g"]
    assert find_unmarked("guess.", frags) == ["g"]


def test_missing_folder_still_scans_markers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "plugins" / "p" / "agents" / "a.md", f"{block('hand edit')}\n")
    write(tmp_path / "plugins" / "p" / "agents" / "b.md", "No markers.\n")
    assert fr.main(["--check", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "plugins/p/agents/a.md: unknown fragment id 'rule'" in out
    assert "b.md" not in out


def test_unchanged_render_does_not_write(tmp_path: Path) -> None:
    make_root(tmp_path, f"{block('Never guess.')}\n")
    path = tmp_path / "plugins/p/agents/a.md"
    os.utime(path, (1_000_000, 1_000_000))
    assert fr.main(["--root", str(tmp_path)]) == 0
    assert path.stat().st_mtime == 1_000_000


def test_scan_scope(tmp_path: Path) -> None:
    for rel in ("agents/a.md", "commands/c.md", "skills/s/SKILL.md", "skills/s/references/deep/r.md"):
        write(tmp_path / "plugins" / "p" / rel, "x\n")
    write(tmp_path / "plugins" / "p" / "README.md", "x\n")
    write(tmp_path / "user-config" / "u.md", "x\n")
    found = {f.relative_to(tmp_path).as_posix() for f in fr.scan_files(tmp_path)}
    assert found == {
        "plugins/p/agents/a.md",
        "plugins/p/commands/c.md",
        "plugins/p/skills/s/SKILL.md",
        "plugins/p/skills/s/references/deep/r.md",
    }


def test_render_mixed_newlines_keeps_lines_outside_blocks() -> None:
    out = render(f"a\r\nb\n{block('stale')}\n", FRAGS)
    assert out == f"a\r\nb\n{block('Never guess.')}\n"


def test_marker_indented_four_spaces_is_an_error() -> None:
    with pytest.raises(FragmentError, match="unrecognized shared marker"):
        render("- item\n    <!-- shared:rule -->\n    stale\n    <!-- /shared:rule -->\n", FRAGS)


def test_fragment_leaving_a_fence_open_fails(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text("```\nx\n", encoding="utf-8")
    with pytest.raises(FragmentError, match="leaves a code fence open"):
        fr.load_fragments(tmp_path)


def test_markers_in_user_config_are_reported(tmp_path: Path) -> None:
    make_root(tmp_path, "")
    write(tmp_path / "user-config/offload-policy.md", f"intro\n{block('Never guess.')}\n")
    assert "user-config/offload-policy.md: shared markers are not allowed in user-config" in fr.check(tmp_path)


def test_verbatim_in_needs_whole_lines(tmp_path: Path) -> None:
    make_root(tmp_path, "")
    write(tmp_path / "shared/fragments/v.md", "verbatim-in: user-config/p.md\nNever guess.\n")
    write(tmp_path / "user-config/p.md", "I never guess. Never guess. ok\n")
    assert "user-config/p.md: text of 'v' is not verbatim in it (shared/fragments/v.md)" in fr.check(tmp_path)
