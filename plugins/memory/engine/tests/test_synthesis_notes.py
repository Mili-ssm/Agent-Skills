"""Stage 5b amendments A to C: a synthesis section and its note, sections that grow, search and overlap."""

import mem
import pytest
from syntheses import document

NOTE = "../knowledge/computing/attention-replaces-recurrence.md"
SRC = f"Sources: [attention]({NOTE})"
NOTE_BODY = (
    "## Claim\n\nShort recall.\n\n## Evidence\n\nSee the part.\n\n## Applies when\n\nAlways.\n\n"
    "## Does not apply when\n\nNever.\n"
)
RECALL = "A short recall of the part"
USAGE_ERROR = 2


@pytest.fixture
def run(hub_root, capsys):
    def go(*argv):
        code = mem.main(["--root", str(hub_root), *argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return go


def body(tmp_path, text, name="body.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.fixture
def made(run, tmp_path, hub_root):
    assert (
        run(
            "synthesis",
            "new",
            "--title",
            "Attention",
            "--topics",
            "ml",
            "--slug",
            "attention",
            "--summary-file",
            body(tmp_path, "How attention works here.\n", "s.md"),
        )[0]
        == 0
    )
    return hub_root / "syntheses" / "attention.md"


def one_call(run, tmp_path, slug="attention-is-cheap", note_body=NOTE_BODY):
    return run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Why It Works",
        "--body-file",
        body(tmp_path, f"The reasons, in full.\n\n{SRC}\n", "part.md"),
        "--note-slug",
        slug,
        "--note-claim",
        RECALL,
        "--note-body-file",
        body(tmp_path, note_body, "n.md"),
        "--confidence",
        "medium",
        "--level",
        "intermediate",
    )


def note_path(hub_root, slug="attention-is-cheap"):
    return hub_root / "knowledge" / "computing" / f"{slug}.md"


# ---- A: one call -------------------------------------------------------------------------------------------


def test_one_call_writes_section_and_note_with_part_of_and_hash(run, made, tmp_path, hub_root):
    code, out, err = one_call(run, tmp_path)
    assert code == 0, err
    assert out.splitlines()[0] == "s:attention#why-it-works\tadded"
    assert out.splitlines()[1] == "knowledge/computing/attention-is-cheap.md"
    text = note_path(hub_root).read_text(encoding="utf-8")
    section = document.load_one(made).sections[-1]
    assert 'part_of: "attention#why-it-works"' in text or "part_of: attention#why-it-works" in text
    assert document.fingerprint(section.text) in text
    assert "topics: [ml, computing]" in text
    assert run("check")[:2] == (0, "")
    code, out, _ = run("show", "attention-is-cheap")
    assert (
        "part of: s:attention#why-it-works (extended version: mem show s:attention#why-it-works)"
        in out
    )


def test_one_call_is_both_or_neither(run, made, tmp_path, hub_root):
    before = made.read_bytes()
    bad = one_call(run, tmp_path, note_body="## Claim\n\nNo other headings.\n")
    assert bad[0] == 1 and bad[2].startswith("mem:")
    assert made.read_bytes() == before and not note_path(hub_root).exists()
    assert not (made.parent / ".curation-log").exists()
    assert run("check")[:2] == (0, "")
    dup = one_call(run, tmp_path, slug="attention-replaces-recurrence")
    assert dup[0] == 1 and made.read_bytes() == before


def test_one_call_group_must_be_complete(run, made, tmp_path):
    with pytest.raises(SystemExit) as exc:
        run(
            "synthesis",
            "add",
            "s:attention",
            "--section",
            "X",
            "--body-file",
            body(tmp_path, f"t\n\n{SRC}\n"),
            "--note-slug",
            "x-y",
        )
    assert exc.value.code == USAGE_ERROR


def test_check_reports_a_part_of_whose_section_is_missing(run, made, tmp_path, hub_root):
    one_call(run, tmp_path)
    text = made.read_text(encoding="utf-8").replace("## Why It Works", "## Renamed")
    made.write_text(text, encoding="utf-8")
    code, out, _ = run("check")
    assert code != 0 and "part_of names the section why-it-works" in out
    assert run("show", "attention-is-cheap")[0] == 0


@pytest.mark.parametrize(
    "line,ok",
    [
        ("Sources: [x](https://example.org/x)", True),
        ("Sources: https://example.org/x", True),
        ("Sources: experience 2026-11-17", True),
        ("Sources: experience 2026-13-45", False),
        ("Sources: experience yesterday", False),
        ("Sources: [x](http://example.org/x)", False),
    ],
)
def test_sources_line_accepts_a_note_https_or_experience(hub_root, line, ok):
    assert (document.validate_section(f"Text.\n\n{line}\n", hub_root) == []) is ok


def test_new_knowledge_on_a_covered_topic_is_written_with_a_hint(run, made, hub_root, capsys):
    args = (
        "new",
        "knowledge",
        "--slug",
        "loose-note",
        "--claim",
        "A loose claim",
        "--topics",
        "ml",
        "--confidence",
        "low",
        "--level",
        "basic",
        "--origin",
        "experience",
        "--body-file",
    )
    code, out, err = run(*args, body(hub_root.parent, NOTE_BODY, "b.md"))
    assert code == 0 and out == "knowledge/computing/loose-note.md\n"
    assert (
        "mem: s:attention (Attention) covers this topic; a curation pass can attach this note to it "
        "(mem curate --notes)."
    ) in err
    assert err.count("covers this topic") == 1


def test_new_knowledge_is_unchanged_without_syntheses_or_on_another_topic(run, hub_root, tmp_path):
    args = (
        "new",
        "knowledge",
        "--slug",
        "loose-note",
        "--claim",
        "A loose claim",
        "--topics",
        "ml",
        "--confidence",
        "low",
        "--level",
        "basic",
        "--origin",
        "experience",
        "--body-file",
        body(tmp_path, NOTE_BODY),
    )
    code, _, err = run(*args)
    assert code == 0 and "covers this topic" not in err
    # a synthesis on the root topic does not cover its descendants
    run("synthesis", "new", "--title", "Root", "--topics", "computing", "--slug", "root")
    other = (
        "new",
        "knowledge",
        "--slug",
        "other-note",
        "--claim",
        "Another claim",
        "--topics",
        "algorithms",
        "--confidence",
        "low",
        "--level",
        "basic",
        "--origin",
        "experience",
        "--body-file",
        body(tmp_path, NOTE_BODY, "o.md"),
    )
    assert "covers this topic" not in run(*other)[2]


def test_new_knowledge_part_of_records_the_fields(run, made, tmp_path, hub_root):
    run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Part",
        "--body-file",
        body(tmp_path, f"Text.\n\n{SRC}\n"),
    )
    args = (
        "new",
        "knowledge",
        "--slug",
        "loose-note",
        "--claim",
        "A loose claim",
        "--topics",
        "ml",
        "--confidence",
        "low",
        "--level",
        "basic",
        "--origin",
        "experience",
        "--body-file",
        body(tmp_path, NOTE_BODY, "b.md"),
    )
    code, _, err = run(*args, "--part-of", "s:attention#part")
    assert code == 0 and "covers this topic" not in err
    text = note_path(hub_root, "loose-note").read_text(encoding="utf-8")
    assert "attention#part" in text and "part_of_hash" in text
    assert (
        run(
            "new",
            "knowledge",
            "--slug",
            "other-note",
            "--claim",
            "C",
            "--topics",
            "ml",
            "--confidence",
            "low",
            "--level",
            "basic",
            "--origin",
            "experience",
            "--part-of",
            "s:attention#nope",
        )[0]
        == 1
    )


def loose(run, tmp_path, slug="loose-note"):
    return run(
        "new",
        "knowledge",
        "--slug",
        slug,
        "--claim",
        "A loose claim",
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
    )


def test_attach_sets_part_of_and_is_undone_by_restore(run, made, tmp_path, hub_root):
    run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Part",
        "--body-file",
        body(tmp_path, f"Text.\n\n{SRC}\n"),
    )
    loose(run, tmp_path)
    note = note_path(hub_root, "loose-note")
    before = note.read_bytes()
    _, out, _ = run("curate", "--notes")
    assert out.splitlines()[0].startswith(
        "notes on a topic that has a synthesis, not yet part of it"
    )
    assert "  loose-note  →  s:attention  A loose claim" in out
    code, out, _ = run("synthesis", "attach", "loose-note", "s:attention#part")
    assert (code, out) == (0, "loose-note\tpart of s:attention#part\n")
    text = note.read_text(encoding="utf-8")
    assert 'part_of: "attention#part"' in text and "part_of_hash:" in text
    assert run("check")[:2] == (0, "")
    assert not run("curate", "--notes")[1]
    assert (hub_root / ".curation-log").is_file()
    code, out, _ = run("restore", "loose-note")
    assert code == 0 and out.startswith("loose-note\trestored")
    assert note.read_bytes() == before
    assert "loose-note" in run("curate", "--notes")[1]


def test_attach_to_a_missing_section_or_note_exits_2(run, made, tmp_path, hub_root):
    loose(run, tmp_path)
    before = note_path(hub_root, "loose-note").read_bytes()
    assert run("synthesis", "attach", "loose-note", "s:attention#nope")[0] == USAGE_ERROR
    assert run("synthesis", "attach", "loose-note", "s:nope#x")[0] == USAGE_ERROR
    assert run("synthesis", "attach", "no-such-note", "s:attention#summary")[0] == USAGE_ERROR
    assert note_path(hub_root, "loose-note").read_bytes() == before
    assert not (hub_root / ".curation-log").exists()


def test_curate_notes_prints_nothing_without_items_and_flags_notes_older_than_their_section(
    run, made, tmp_path
):
    assert run("curate", "--notes") == (0, "", "")
    one_call(run, tmp_path)
    assert run("curate", "--notes") == (0, "", "")
    assert (
        run(
            "synthesis",
            "append",
            "s:attention#why-it-works",
            "--body-file",
            body(tmp_path, "More text.\n"),
        )[0]
        == 0
    )
    _, out, _ = run("curate", "--notes")
    assert out.splitlines() == [
        (
            "notes older than their section (rewrite the note from the section: "
            "mem show s:<h>#<section>)"
        ),
        "  attention-is-cheap  s:attention#why-it-works",
    ]


# ---- B: sections grow --------------------------------------------------------------------------------------


def test_append_adds_text_before_sources_and_merges_links(run, made, tmp_path, hub_root):
    run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Part",
        "--body-file",
        body(tmp_path, f"First.\n\n{SRC}\n"),
    )
    code, out, _ = run(
        "synthesis",
        "append",
        "s:attention#part",
        "--body-file",
        body(tmp_path, f"Second.\n\nSources: {SRC[9:]}, experience 2026-11-17\n", "a.md"),
    )
    assert (code, out) == (0, "s:attention#part\tappended\n")
    sec = document.load_one(made).sections[-1]
    assert sec.text == f"First.\n\nSecond.\n\n{SRC}, experience 2026-11-17"
    assert run("check")[:2] == (0, "")


def test_edit_refuses_to_lose_words_or_links_unless_shrink(run, made, tmp_path):
    run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Part",
        "--body-file",
        body(tmp_path, "One two three four five six seven eight nine ten.\n\n" + SRC + "\n"),
    )
    before = made.read_bytes()
    code, _, err = run(
        "synthesis",
        "edit",
        "s:attention#part",
        "--body-file",
        body(tmp_path, f"One.\n\n{SRC}\n", "e.md"),
    )
    assert (
        code == 1
        and err.startswith("mem: the new text drops ")
        and "use --shrink if that is meant." in err
    )
    nolink = "One two three four five six seven eight nine ten.\n\nSources: experience 2026-11-17\n"
    code, _, err = run(
        "synthesis", "edit", "s:attention#part", "--body-file", body(tmp_path, nolink, "f.md")
    )
    assert code == 1 and NOTE in err and made.read_bytes() == before
    assert (
        run(
            "synthesis",
            "edit",
            "s:attention#part",
            "--body-file",
            body(tmp_path, nolink, "f.md"),
            "--shrink",
        )[0]
        == 0
    )


def test_show_prints_the_outline_by_default_and_the_file_with_all(run, made, tmp_path):
    run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "One",
        "--body-file",
        body(tmp_path, f"Text of One.\n\n{SRC}\n"),
    )
    _, out, _ = run("show", "s:attention")
    assert "Text of One." not in out and out.splitlines()[2].endswith("\t## One")
    _, out, _ = run("show", "s:attention", "--all")
    assert "Text of One." in out and out.splitlines()[1] == "---"
    assert "Text of One." in run("show", "s:attention#one")[1]


def test_a_section_over_800_words_prints_a_note_on_stderr(run, made, tmp_path):
    long = " ".join(["word"] * 801)
    code, _, err = run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Long",
        "--body-file",
        body(tmp_path, f"{long}\n\n{SRC}\n"),
    )
    assert code == 0 and "s:attention#long has 803 words" in err and "splitting" in err
    code, _, err = run(
        "synthesis", "append", "s:attention#long", "--body-file", body(tmp_path, "more\n", "m.md")
    )
    assert code == 0 and "has 804 words" in err
    short = run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Short",
        "--body-file",
        body(tmp_path, f"x\n\n{SRC}\n", "s.md"),
    )
    assert not short[2]


# ---- C: search and overlap ---------------------------------------------------------------------------------


def test_a_section_matches_on_heading_and_first_paragraph_only(run, made, tmp_path):
    text = f"Opening paragraph about gradients.\n\nA later paragraph mentions zebra stripes.\n\n{SRC}\n"
    run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        "Training",
        "--body-file",
        body(tmp_path, text),
    )
    assert "s:attention#training" in run("search", "gradients training", "--deep")[1]
    assert "-- syntheses" not in run("search", "zebra stripes", "--deep")[1]


def test_synthesis_new_refuses_a_topic_another_synthesis_lists(run, made):
    code, _, err = run(
        "synthesis", "new", "--title", "Other", "--topics", "ml,algorithms", "--slug", "other"
    )
    assert code == 1 and err == "mem: s:attention already covers the topic ml; add a part to it.\n"
    assert not (made.parent / "other.md").exists()
    assert (
        run("synthesis", "new", "--title", "Other", "--topics", "computing", "--slug", "other")[0]
        == 0
    )
