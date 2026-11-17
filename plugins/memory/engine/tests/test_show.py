import mem

from test_find_new import write_note

NOTE = (
    "---\nclaim: C\ntopics: [computing]\nconfidence: low\norigin: experience\n"
    "updated: 2026-11-07\n---\n"
    "# Title\n\n## Claim\nthe claim\n\n## Evidence\nev\n```\n## Fake\n```\n\n"
    "## Does not apply when\nnever\n"
)
REL = "knowledge/computing/c.md"


def run(hub_root, capsys, *argv):
    code = mem.main(["--root", str(hub_root), "show", *argv])
    return code, capsys.readouterr().out


def test_sections_in_note_order_case_insensitive(hub_root, capsys):
    write_note(hub_root, REL, NOTE)
    code, out = run(hub_root, capsys, REL, "--section", "does not apply WHEN", "--section", " claim ")
    assert code == 0
    assert out.splitlines()[:2] == [f"== {REL}", "confidence: low · updated: 2026-11-07"]
    assert out.index("## Claim") < out.index("## Does not apply when")
    assert "the claim" in out and "never" in out and "## Evidence" not in out


def test_section_keeps_fenced_pseudo_heading(hub_root, capsys):
    write_note(hub_root, REL, NOTE)
    _, out = run(hub_root, capsys, REL, "--section", "Evidence")
    assert "## Fake" in out and "never" not in out


def test_missing_section_message(hub_root, capsys):
    write_note(hub_root, REL, NOTE)
    code, out = run(hub_root, capsys, REL, "--section", "Nope")
    assert code == 0
    assert '(no section "Nope")' in out


def test_outline_line_numbers_ignore_fenced(hub_root, capsys):
    path = write_note(hub_root, REL, NOTE)
    _, out = run(hub_root, capsys, REL, "--outline")
    lines = path.read_text().split("\n")
    expected = [f"{i + 1}: {l}" for i, l in enumerate(lines) if l.startswith("#") and l != "## Fake"]
    assert out.splitlines()[2:] == expected


def test_no_flags_prints_body(hub_root, capsys):
    write_note(hub_root, REL, NOTE)
    _, out = run(hub_root, capsys, REL)
    assert "# Title" in out and "claim: C" not in out


def test_key_facts_per_type(hub_root, capsys):
    code, out = run(hub_root, capsys, "literature/computing/2017-vaswani-attention.md",
                    "research/2026-11-llm-eval-methods/README.md", "--section", "x")
    lines = out.splitlines()
    assert lines[1].startswith("year: 2017 · kind: paper · url: http")
    assert any(l.startswith("status: ") and " · started: " in l for l in lines)


def test_not_found_and_outside_hub(hub_root, capsys, tmp_path):
    write_note(hub_root, REL, NOTE)
    outside = tmp_path / "out.md"
    outside.write_text("x")
    code, out = run(hub_root, capsys, "knowledge/computing/zzz.md", str(outside), "../out.md",
                    REL, "--section", "Claim")
    assert code == 1
    assert out.count("(not found)") == 3
    assert "the claim" in out


def test_absolute_path_inside_hub(hub_root, capsys):
    path = write_note(hub_root, REL, NOTE)
    code, out = run(hub_root, capsys, str(path), "--outline")
    assert code == 0 and out.startswith(f"== {REL}")


def test_bad_frontmatter_still_prints(hub_root, capsys):
    write_note(hub_root, REL, "no frontmatter\n## Claim\nhi\n")
    code, out = run(hub_root, capsys, REL, "--section", "claim")
    assert code == 0
    assert out.splitlines() == [f"== {REL}", "## Claim", "hi"]


def test_outline_with_section_is_usage_error(hub_root, capsys):
    code, _ = run(hub_root, capsys, REL, "--outline", "--section", "Claim")
    assert code == 2


def test_key_facts_include_level_when_present(hub_root, capsys):
    _, out = run(hub_root, capsys, "literature/computing/2017-vaswani-attention.md",
                 "knowledge/computing/attention-replaces-recurrence.md", "--section", "x")
    lines = out.splitlines()
    assert lines[1].endswith(" · level: advanced")
    assert any(l.startswith("confidence: ") and l.endswith(" · level: intermediate") for l in lines)


def test_show_outline_ranges(hub_root, capsys):
    rel = "knowledge/computing/attention-replaces-recurrence.md"
    assert mem.main(["--root", str(hub_root), "show", rel, "--outline"]) == 0
    plain = [l for l in capsys.readouterr().out.splitlines() if ": #" in l]
    assert mem.main(["--root", str(hub_root), "show", rel, "--outline", "--ranges"]) == 0
    ranged = [l.split("\t") for l in capsys.readouterr().out.splitlines() if "\t#" in l]
    assert [r[2] for r in ranged] == [l.split(": ", 1)[1] for l in plain]
    starts = [int(r[0].split("-")[0]) for r in ranged]
    ends = [int(r[0].split("-")[1]) for r in ranged]
    assert starts == [int(l.split(":")[0]) for l in plain]
    assert all(s <= e for s, e in zip(starts, ends)) and all(r[1].endswith("w") and int(r[1][:-1]) >= 2 for r in ranged)
    total = len((hub_root / rel).read_text(encoding="utf-8").rstrip("\n").split("\n"))
    assert ends[-1] == total


def test_show_ranges_needs_outline(hub_root):
    import pytest
    with pytest.raises(SystemExit) as exc:
        mem.main(["--root", str(hub_root), "show", "knowledge/computing/attention-replaces-recurrence.md", "--ranges"])
    assert exc.value.code == 2
