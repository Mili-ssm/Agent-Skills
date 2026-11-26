"""`mem synthesis refs`: references are added or removed by unit number and source target, never by text."""

import string
from pathlib import Path

import mem
import pytest
from syntheses import document, edit, units

USAGE_EXIT = 2
GAMMA_UNITS = 2
DELTA_UNITS = 7
REFUSED_TWICE = 2

A = "../knowledge/computing/attention-replaces-recurrence.md"
A_SPELLED = "../knowledge/computing/./attention-replaces-recurrence.md"
B = "../literature/computing/2017-vaswani-attention.md"
SYN = "syntheses/attention.md"
ALPHA = (
    f"First plain sentence here. Second one has a reference.[a]({A}) Third one is plain too.\n\n"
    f"Fourth has [an inline one]({A}) in it.\n\n| col | val |\n|---|---|\n| row | x |\n\n"
    f"Sources: [attention]({A_SPELLED}), [vaswani]({B})"
)
BETA = f"Beta says something plain.\n\nSources: [vaswani]({B})"
# units of Alpha: 1 First, 2 Second (a), 3 Third, 4 Fourth (inline), 5 header row, 6 data row


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
    return (
        f"## Claim\n\n{claim}\n\n## Evidence\n\nObserved.\n\n## Applies when\n\nAlways.\n\n"
        "## Does not apply when\n\nNever.\n"
    )


@pytest.fixture
def made(run, tmp_path, hub_root):
    """A synthesis `attention` with the parts Alpha and Beta; one-note and two-note are part of Alpha."""
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
            text_file(tmp_path, "How attention works here.\n", "s.md"),
        )[0]
        == 0
    )
    for name, text in (("Alpha", ALPHA), ("Beta", BETA)):
        assert (
            run(
                "synthesis",
                "add",
                "s:attention",
                "--section",
                name,
                "--body-file",
                text_file(tmp_path, text + "\n", "p.md"),
            )[0]
            == 0
        )
    for slug in ("one-note", "two-note"):
        assert (
            run(
                "new",
                "knowledge",
                "--slug",
                slug,
                "--claim",
                f"Claim of {slug}",
                "--topics",
                "ml",
                "--confidence",
                "low",
                "--level",
                "basic",
                "--origin",
                "experience",
                "--body-file",
                text_file(tmp_path, note_body(f"Claim of {slug}"), f"{slug}.md"),
            )[0]
            == 0
        )
        assert run("synthesis", "attach", slug, "s:attention#alpha")[0] == 0
    assert run("check")[0] == 0
    return hub_root


def refs(run, tmp_path, *lines):
    return run(
        "synthesis",
        "refs",
        "s:attention",
        "--file",
        text_file(tmp_path, "\n".join(lines) + "\n", "refs.txt"),
    )


def files(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.startswith(".curation-log")
    }


def part(root, name):
    syn = document.load_one(root / SYN)
    return next(s.text for s in syn.sections if s.handle == name)


def note(root, slug):
    return next((root / "knowledge").glob(f"*/{slug}.md"))


def stamp(root, slug):
    return mem.split_frontmatter(note(root, slug).read_text(encoding="utf-8"))[0]["part_of_hash"]


def test_add_after_a_plain_sentence_copies_label_and_target_from_the_sources_line(
    run, made, tmp_path
):
    old = part(made, "alpha")
    code, out, err = refs(run, tmp_path, f"alpha | 1 | add {A}")
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "s:attention#alpha: added 1, removed 0, refused 0",
        "s:attention: added 1, removed 0, refused 0",
    ]
    new = part(made, "alpha")
    assert (
        f"First plain sentence here. [attention]({A_SPELLED}) Second" in new
    )  # the Sources line's own spelling
    assert units.without_references(new) == units.without_references(old)
    assert run("check")[:2] == (0, "")
    assert "updated: '" in (made / SYN).read_text(encoding="utf-8")


def test_add_after_a_sentence_that_already_has_a_reference_goes_after_it(run, made, tmp_path):
    assert refs(run, tmp_path, f"alpha | 2 | add {B}")[0] == 0
    assert f"reference.[a]({A}) [vaswani]({B}) Third" in part(made, "alpha")
    assert run("check")[:2] == (0, "")


def test_two_parts_in_one_file_and_comments_and_blank_lines(run, made, tmp_path):
    code, out, err = refs(
        run, tmp_path, "# proposals", "", f"alpha | 3 | add {B}", f"beta | 1 | add {B}"
    )
    assert (code, err) == (0, "")
    assert out.splitlines()[:2] == [
        "s:attention#alpha: added 1, removed 0, refused 0",
        "s:attention#beta: added 1, removed 0, refused 0",
    ]
    assert out.splitlines()[-1] == "s:attention: added 2, removed 0, refused 0"
    assert f"plain.[vaswani]({B})" not in part(made, "beta") and f"plain. [vaswani]({B})" in part(
        made, "beta"
    )
    assert f"too. [vaswani]({B})" in part(made, "alpha")


def test_each_refusal_has_its_reason_and_never_stops_the_others(run, made, tmp_path):
    other = "../knowledge/computing/one-note.md"
    lines = [
        "summary | 1 | add " + A,
        "nope | 1 | add " + A,
        "alpha | 9 | add " + A,
        f"alpha | 3 | add {other}",
        f"alpha | 2 | add {A}",
        "alpha | 6 | add " + A,
        f"alpha | 1 | remove {A}",
        f"alpha | 4 | remove {A}",
        "alpha | x | add " + A,
        f"alpha | 3 | add {B}",
    ]
    code, out, err = refs(run, tmp_path, *lines)
    assert (code, err) == (0, "")
    got = out.splitlines()
    assert got[0] == "s:attention#alpha: added 1, removed 0, refused 6"
    assert got[-1] == "s:attention: added 1, removed 0, refused 9"
    reasons = {
        ln.split(": ", 2)[1]: ln.split(": ", 2)[2] for ln in got if ln.startswith("refused: ")
    }
    assert "Summary takes no references" in reasons["summary | 1 | add " + A]
    assert "no section 'nope'" in reasons["nope | 1 | add " + A]
    assert "no unit 9" in reasons["alpha | 9 | add " + A]
    assert "not on the part's Sources line" in reasons[f"alpha | 3 | add {other}"]
    assert "already carries" in reasons[f"alpha | 2 | add {A}"]
    assert "table row" in reasons["alpha | 6 | add " + A]
    assert "does not carry" in reasons[f"alpha | 1 | remove {A}"]
    assert "inside the sentence" in reasons[f"alpha | 4 | remove {A}"]
    assert "not `<section>" in reasons["alpha | x | add " + A]
    assert f"too. [vaswani]({B})" in part(made, "alpha")


def test_remove_takes_the_reference_and_the_space_before_it(run, made, tmp_path):
    assert refs(run, tmp_path, f"alpha | 1 | add {B}")[0] == 0
    assert refs(run, tmp_path, f"alpha | 1 | remove {B}", f"alpha | 2 | remove {A_SPELLED}")[0] == 0
    new = part(made, "alpha")
    assert new.startswith("First plain sentence here. Second one has a reference. Third")
    assert f"[an inline one]({A})" in new
    assert run("check")[:2] == (0, "")


def test_a_second_run_of_the_same_file_changes_nothing(run, made, tmp_path):
    lines = [f"alpha | 1 | add {A}", f"beta | 1 | add {B}"]
    assert refs(run, tmp_path, *lines)[0] == 0
    after = files(made)
    code, out, _ = refs(run, tmp_path, *lines)
    assert (
        code == 0
        and "already carries" in out
        and out.splitlines()[-1] == "s:attention: added 0, removed 0, refused 2"
    )
    assert files(made) == after


def test_an_empty_file_or_a_missing_file_or_synthesis_exits_1(run, made, tmp_path):
    assert refs(run, tmp_path, "# nothing")[0] == 1
    assert run("synthesis", "refs", "s:attention", "--file", str(tmp_path / "missing.txt"))[0] == 1
    assert (
        run("synthesis", "refs", "s:nothing", "--file", text_file(tmp_path, "alpha | 1 | add x\n"))[
            0
        ]
        == 1
    )
    assert (
        run(
            "synthesis",
            "refs",
            "s:attention#alpha",
            "--file",
            text_file(tmp_path, "alpha | 1 | add x\n"),
        )[0]
        == USAGE_EXIT
    )


def test_when_every_line_is_refused_nothing_is_written_or_logged(run, made, tmp_path):
    before, log = (
        files(made),
        (made / ".curation-log").read_bytes() if (made / ".curation-log").exists() else None,
    )
    code, out, _ = refs(run, tmp_path, f"alpha | 2 | add {A}")
    assert code == 0 and "refused: " in out
    assert files(made) == before
    assert (
        (made / ".curation-log").read_bytes() if (made / ".curation-log").exists() else None
    ) == log


def test_one_restore_puts_back_the_synthesis_and_a_restamped_note(run, made, tmp_path):
    section = part(made, "alpha")
    legacy = units.fingerprint_legacy(section)
    new_fp = units.fingerprint(section)
    path = note(made, "one-note")
    path.write_text(path.read_text(encoding="utf-8").replace(new_fp, legacy), encoding="utf-8")
    before = files(made)
    assert refs(run, tmp_path, f"alpha | 3 | add {B}")[0] == 0
    assert stamp(made, "one-note") == units.fingerprint(part(made, "alpha")) != legacy
    assert (
        stamp(made, "two-note") == new_fp
    )  # already current by the new definition and unchanged by it
    assert files(made) != before
    assert "s:attention#alpha" not in run("curate", "--notes")[1]
    code, out, err = run("restore", "s:attention")
    assert code == 0, err
    assert out.startswith("s:attention\trestored to before refs of ") and "(2 files)" in out
    assert files(made) == before
    assert (
        run("restore", "s:attention")[0] == 0
    )  # the next restore undoes the earlier step, as after a rename
    assert files(made) != before


def test_a_note_that_was_behind_stays_behind(run, made, tmp_path):
    path = note(made, "one-note")
    path.write_text(
        path.read_text(encoding="utf-8").replace(stamp(made, "one-note"), string.digits),
        encoding="utf-8",
    )
    assert refs(run, tmp_path, f"alpha | 3 | add {B}")[0] == 0
    assert stamp(made, "one-note") == string.digits
    assert "one-note  s:attention#alpha" in run("curate", "--notes")[1]


def test_restore_after_a_later_edit_of_a_restamped_note_is_refused_as_for_other_groups(
    run, made, tmp_path
):
    section = part(made, "alpha")
    path = note(made, "one-note")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            units.fingerprint(section), units.fingerprint_legacy(section)
        ),
        encoding="utf-8",
    )
    assert refs(run, tmp_path, f"alpha | 3 | add {B}")[0] == 0
    path.write_text(path.read_text(encoding="utf-8") + "\nAn extra line.\n", encoding="utf-8")
    after = files(made)
    code, _, err = run("restore", "s:attention")
    assert code == USAGE_EXIT and "changed since refs" in err
    assert files(made) == after


@pytest.mark.parametrize(
    "gone, left", [(("a",), ("b",)), (("b",), ("a",)), (("a", "b"), ()), (("b", "a"), ())]
)
def test_remove_from_a_pair_separated_by_a_comma_leaves_no_comma(gone, left):
    targets = {"a": "../knowledge/computing/one.md", "b": "../knowledge/computing/two.md"}
    pair = f" [a]({targets['a']}), [b]({targets['b']})"
    text = f"Alpha one.{pair} Alpha two.\n\nSources: [a]({targets['a']}), [b]({targets['b']})\n"
    base = Path("/store/syntheses")
    new, reasons = edit.change_references(text, base, [(1, "remove", targets[g]) for g in gone])
    assert reasons == [None] * len(gone)
    kept = "".join(f" [{k}]({targets[k]})" for k in left)
    assert new == text.replace(pair, kept, 1)
    assert units.without_references(new) == units.without_references(text)


GAMMA = (
    f"Retrieval hurt some answers (Mo et al., Ab et al. on PopQA); self-selected retrieval did better in Yu et al.\n\n"
    f"- Chunking helped in Cy et al.\n\nSources: [attention]({A}), [vaswani]({B})"
)


def test_a_reference_can_follow_a_unit_that_ends_in_an_abbreviation(run, made, tmp_path):
    assert (
        run(
            "synthesis",
            "add",
            "s:attention",
            "--section",
            "Gamma",
            "--body-file",
            text_file(tmp_path, GAMMA + "\n", "g.md"),
        )[0]
        == 0
    )
    old = part(made, "gamma")
    before = files(made)
    shape = [(u.n, u.plain) for u in units.units(old)[0]]
    assert len(shape) == GAMMA_UNITS
    code, out, err = refs(run, tmp_path, f"gamma | 1 | add {A}", f"gamma | 2 | add {B}")
    assert (code, err) == (0, "")
    assert out.splitlines()[0] == "s:attention#gamma: added 2, removed 0, refused 0"
    new = part(made, "gamma")
    assert f"in Yu et al. [attention]({A})\n" in new and f"Cy et al. [vaswani]({B})\n" in new
    assert [(u.n, u.plain) for u in units.units(new)[0]] == shape
    assert units.fingerprint(new) == units.fingerprint(old)
    assert run("check")[:2] == (0, "")
    after = files(made)
    code, out, err = refs(run, tmp_path, f"gamma | 1 | add {A}", f"gamma | 2 | add {B}")
    assert (
        (code, err) == (0, "")
        and "refused 2" in out
        and out.count("already carries") == REFUSED_TWICE
    )
    assert files(made) == after
    assert run("restore", "s:attention")[0] == 0
    assert files(made) == before


DELTA = (
    "Alpha holds in general. Beta results, per setting, were:\n\n| c | m |\n|---|---|\n| x | y |\n\n"
    "Gamma differs as follows:\n- item one\n- item two\n\n"
    f"Sources: [attention]({A}), [vaswani]({B})"
)


def test_a_reference_can_follow_a_unit_that_ends_in_a_colon_before_a_table_or_list(
    run, made, tmp_path
):
    assert (
        run(
            "synthesis",
            "add",
            "s:attention",
            "--section",
            "Delta",
            "--body-file",
            text_file(tmp_path, DELTA + "\n", "d.md"),
        )[0]
        == 0
    )
    old = part(made, "delta")
    before = files(made)
    shape = [(u.n, u.plain) for u in units.units(old)[0]]
    assert (
        len(shape) == DELTA_UNITS
        and shape[1][1].endswith("were:")
        and shape[4][1] == "Gamma differs as follows:"
    )
    code, out, err = refs(run, tmp_path, f"delta | 2 | add {A}", f"delta | 5 | add {B}")
    assert (code, err) == (0, "")
    assert out.splitlines()[0] == "s:attention#delta: added 2, removed 0, refused 0"
    new = part(made, "delta")
    assert f"were: [attention]({A})\n" in new and f"as follows: [vaswani]({B})\n- item one" in new
    assert [(u.n, u.plain) for u in units.units(new)[0]] == shape
    assert units.fingerprint(new) == units.fingerprint(old)
    assert run("check")[:2] == (0, "")
    after = files(made)
    code, out, err = refs(run, tmp_path, f"delta | 2 | add {A}", f"delta | 5 | add {B}")
    assert (
        (code, err) == (0, "")
        and "refused 2" in out
        and out.count("already carries") == REFUSED_TWICE
    )
    assert files(made) == after
    assert run("restore", "s:attention")[0] == 0
    assert files(made) == before


def test_one_line_that_breaks_the_part_is_refused_alone(run, made, tmp_path, monkeypatch):
    real = document.validate_section
    monkeypatch.setattr(
        document,
        "validate_section",
        lambda text, root: ["broken"] if f"too. [vaswani]({B})" in text else real(text, root),
    )
    code, out, err = refs(
        run, tmp_path, f"alpha | 1 | add {A}", f"alpha | 3 | add {B}", f"alpha | 4 | add {B}"
    )
    assert (code, err) == (0, "")
    got = out.splitlines()
    assert got[0] == "s:attention#alpha: added 2, removed 0, refused 1"
    assert got[-1] == "s:attention: added 2, removed 0, refused 1"
    assert f"refused: alpha | 3 | add {B}: the part would fail its checks: broken" in got
    new = part(made, "alpha")
    assert f"here. [attention]({A_SPELLED}) Second" in new and f"in it. [vaswani]({B})" in new
    assert "too. [vaswani]" not in new


@pytest.mark.parametrize("after", ["# A heading", "> A quote", "A plain paragraph."])
def test_a_colon_line_before_anything_but_a_table_or_list_keeps_its_reference_inline(after):
    text = f"Alpha holds: [x](../knowledge/x/a.md)\n\n{after}\n"
    (unit, *_), _ = units.units(text)
    assert unit.plain.startswith("Alpha holds: x"), unit.plain


def test_an_indented_list_after_a_colon_line_takes_a_trailing_reference():
    text = "Alpha holds: [x](../knowledge/x/a.md)\n  - an item\n"
    (unit, *_), _ = units.units(text)
    assert unit.plain == "Alpha holds:", unit.plain
