"""Inline note references in syntheses: the unit parser, the fingerprint that ignores them, and the edit guard."""
import pytest

import mem
import syntheses

A = "../knowledge/computing/attention-replaces-recurrence.md"
B = "../literature/computing/2017-vaswani-attention.md"
SRC = f"Sources: [attention]({A})"


def parse(text):
    return syntheses.units(text)


def plains(text):
    return [u.plain for u in parse(text)[0]]


# ---- parser ------------------------------------------------------------------------------------------------

def test_decimal_and_plain_sentences():
    found, orphans = parse("The score was 0.82 on average. It then fell! Did it? Yes.")
    assert [u.text for u in found] == ["The score was 0.82 on average.", "It then fell!", "Did it?", "Yes."]
    assert [u.n for u in found] == [1, 2, 3, 4] and orphans == []


@pytest.mark.parametrize("text", [
    "Some tools, e.g. the cheap ones, are fine.",
    "That is, i.e. the usual case, fine.",
    "Smith et al. found it so.",
    "Cheap vs. costly is the question.",
    "Compare cf. the other part for details.",
])
def test_abbreviations_do_not_end_a_sentence(text):
    assert [u.text for u in parse(text)[0]] == [text]


def test_a_link_with_dots_and_a_code_span_do_not_split():
    text = "See [the v1.2 notes](https://example.org/a.b.html) for more. Run `a. b? c` first."
    assert [u.text for u in parse(text)[0]] == [
        "See [the v1.2 notes](https://example.org/a.b.html) for more.", "Run `a. b? c` first."]


def test_closing_quote_or_bracket_belongs_to_the_sentence():
    assert [u.text for u in parse('He said "it works." Then (maybe.) left.')[0]] == [
        'He said "it works."', "Then (maybe.)", "left."]


def test_code_fence_lines_are_not_units():
    assert plains("Before it.\n\n```\nCode. More code.\n```\n\nAfter it.") == ["Before it.", "After it."]


def test_bold_label_is_no_unit_and_not_in_the_span():
    text = "**What it is.** A small thing. It helps.\n\n- **3. Some title.** Item text here."
    found, _ = parse(text)
    assert [u.text for u in found] == ["A small thing.", "It helps.", "Item text here."]
    assert text[found[0].span[0]:found[0].span[1]] == "A small thing."
    assert plains("**Label:** body.") == ["body."]
    assert plains("A **bold** word starts it.") == ["A **bold** word starts it."]


def test_a_list_item_with_two_sentences_gives_two_units():
    assert plains("- First here. Second here.\n- Third here.") == ["First here.", "Second here.", "Third here."]


def test_table_rows_are_units_and_the_separator_is_not():
    text = "| a | b |\n|---|:--:|\n| one. | two. |"
    assert [u.text for u in parse(text)[0]] == ["| a | b |", "| one. | two. |"]


def test_references_after_a_sentence_belong_to_it():
    text = f"It works.[a]({A}), [b]({B}) Next one."
    found, orphans = parse(text)
    assert found[0].text == f"It works.[a]({A}), [b]({B})"
    assert found[0].plain == "It works." and found[0].refs == [A, B]
    assert text[slice(*found[0].span)] == found[0].text
    assert found[1].text == "Next one." and found[1].refs == [] and orphans == []


def test_a_reference_after_white_space_and_a_semicolon():
    found, _ = parse(f"It works. ; [a]({A})")
    assert found[0].plain == "It works." and found[0].refs == [A]


def test_a_reference_inside_a_sentence_is_reduced_to_its_label():
    found, _ = parse(f"The [attention paper]({A}) shows it.")
    assert found[0].refs == [A] and found[0].plain == "The attention paper shows it."
    assert found[0].text == f"The [attention paper]({A}) shows it."


def test_a_reference_alone_on_a_line_has_no_owner():
    found, orphans = parse(f"One sentence.\n[a]({A})\nAnother one.")
    assert orphans == [A] and [u.refs for u in found] == [[], []]


def test_other_links_are_plain_text():
    text = "See [site](https://example.org/x.md) and [sec](#part) and [other](other-synthesis.md#a)."
    found, orphans = parse(text)
    assert found[0].refs == [] and found[0].plain == text and orphans == []


def test_a_table_row_owns_its_references():
    found, _ = parse(f"| a | b. [n]({A}) |\n|---|---|\n| c | [m]({B}) d |")
    assert [u.refs for u in found] == [[A], [B]]
    assert [u.plain for u in found] == ["| a | b. |", "| c | m d |"]


def test_the_sources_line_is_not_part_of_the_body():
    with_line, _ = parse(f"A claim.[a]({A})\n\n{SRC}\n")
    assert [u.n for u in with_line] == [1] and with_line[0].refs == [A]
    without, _ = parse("A claim. Another claim.")
    assert len(without) == 2


# ---- fingerprint ---------------------------------------------------------------------------------------------

BASE = f"The reasons are clear. Another reason holds.\n\n{SRC}\n"


def test_fingerprint_ignores_references_and_their_targets():
    plain = syntheses.fingerprint(BASE)
    with_ref = f"The reasons are clear.[x]({A}) Another reason holds.\n\n{SRC}\n"
    moved = f"The reasons are clear.[x]({B}) Another reason holds.\n\n{SRC}\n"
    assert syntheses.fingerprint(with_ref) == plain == syntheses.fingerprint(moved)
    assert syntheses.fingerprint(BASE.replace("clear", "unclear")) != plain


def test_fingerprint_sees_a_change_of_the_text_around_a_reference():
    inline = f"See [the paper]({A}) now.\n\n{SRC}\n"
    assert syntheses.fingerprint(inline) != syntheses.fingerprint(inline.replace("now", "later"))
    assert syntheses.fingerprint(inline) == syntheses.fingerprint(inline.replace(A, B))


def test_legacy_fingerprint_is_the_old_hash_and_still_current():
    assert syntheses.fingerprint_legacy(BASE) == syntheses.fingerprint(BASE)  # no references: the same
    with_ref = f"The reasons are clear.[x]({A}) Another reason holds.\n\n{SRC}\n"
    assert syntheses.fingerprint_legacy(with_ref) != syntheses.fingerprint(with_ref)
    old, new = syntheses.fingerprint_legacy(with_ref), syntheses.fingerprint(with_ref)
    assert syntheses.is_current(old, with_ref) and syntheses.is_current(new, with_ref)
    assert not syntheses.is_current("0" * 10, with_ref) and not syntheses.is_current(None, with_ref)


# ---- CLI -----------------------------------------------------------------------------------------------------

@pytest.fixture
def run(hub_root, capsys):
    def go(*argv):
        code = mem.main(["--root", str(hub_root), *argv])
        out = capsys.readouterr()
        return code, out.out, out.err
    return go


def text_file(tmp_path, text, name="body.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def note_body(claim):
    return (f"## Claim\n\n{claim}\n\n## Evidence\n\nObserved.\n\n## Applies when\n\nAlways.\n\n"
            "## Does not apply when\n\nNever.\n")


PART = f"The first claim stands firmly.[a]({A}) The second claim stands too, in this case.\n\n{SRC}\n"


@pytest.fixture
def made(run, tmp_path, hub_root):
    """A synthesis `attention` whose part Alpha carries a reference; one-note and two-note are part of Alpha."""
    assert run("synthesis", "new", "--title", "Attention", "--topics", "ml", "--slug", "attention",
               "--summary-file", text_file(tmp_path, "How attention works here.\n", "s.md"))[0] == 0
    assert run("synthesis", "add", "s:attention", "--section", "Alpha", "--body-file",
               text_file(tmp_path, PART, "p.md"))[0] == 0
    for slug in ("one-note", "two-note"):
        assert run("new", "knowledge", "--slug", slug, "--claim", f"Claim of {slug}", "--topics", "ml",
                   "--confidence", "low", "--level", "basic", "--origin", "experience", "--body-file",
                   text_file(tmp_path, note_body(f"Claim of {slug}"), f"{slug}.md"))[0] == 0
        assert run("synthesis", "attach", slug, "s:attention#alpha")[0] == 0
    assert run("check")[0] == 0
    assert "s:attention#alpha" not in run("curate", "--notes")[1]
    return hub_root


def edit(run, tmp_path, text, *flags):
    return run("synthesis", "edit", "s:attention#alpha", "--body-file", text_file(tmp_path, text, "e.md"), *flags)


def test_rename_of_a_referenced_note_leaves_the_member_notes_current(run, made):
    assert run("rename", "knowledge/computing/attention-replaces-recurrence.md", "attention-beats-recurrence.md")[0] == 0
    section = syntheses.load_one(made / "syntheses" / "attention.md").sections[-1]
    assert "attention-beats-recurrence.md" in section.text and "attention-replaces-recurrence" not in section.text
    assert "s:attention#alpha" not in run("curate", "--notes")[1]


def test_a_note_stamped_with_the_old_fingerprint_is_current(run, made):
    path = next((made / "knowledge").rglob("one-note.md"))
    section = syntheses.load_one(made / "syntheses" / "attention.md").sections[-1]
    legacy = syntheses.fingerprint_legacy(section.text)
    assert legacy != syntheses.fingerprint(section.text)
    path.write_text(path.read_text(encoding="utf-8").replace(syntheses.fingerprint(section.text), legacy),
                    encoding="utf-8")
    assert "one-note  s:attention#alpha" not in run("curate", "--notes")[1]


def test_an_edit_that_only_adds_references_needs_no_shrink(run, made, tmp_path):
    text = PART.replace("too, in this case.", f"too, in this case.[b]({B})")
    code, out, err = edit(run, tmp_path, text)
    assert code == 0, err
    assert f"[b]({B})" in (made / "syntheses" / "attention.md").read_text(encoding="utf-8")
    assert "s:attention#alpha" not in run("curate", "--notes")[1]


def test_a_dropped_reference_on_an_unchanged_sentence_is_refused_with_and_without_shrink(run, made, tmp_path):
    text = PART.replace(f"[a]({A})", "")
    for flags in ((), ("--shrink",)):
        code, _, err = edit(run, tmp_path, text, *flags)
        assert code == 1 and f"drops the reference {A}" in err and "--drop-references" in err
    assert f"[a]({A})" in (made / "syntheses" / "attention.md").read_text(encoding="utf-8")


def test_drop_references_accepts_the_dropped_reference(run, made, tmp_path):
    text = PART.replace(f"[a]({A})", "")
    code, out, err = edit(run, tmp_path, text, "--drop-references")
    assert code == 0, err
    assert f"[a]({A})" not in (made / "syntheses" / "attention.md").read_text(encoding="utf-8").split("Sources:")[0]


def test_a_reference_may_go_with_its_changed_sentence(run, made, tmp_path):
    text = PART.replace("The first claim stands firmly.", "A rewritten first claim, now.").replace(f"[a]({A})", "")
    assert edit(run, tmp_path, text)[0] == 0
