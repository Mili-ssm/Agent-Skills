"""Per-note staleness stamps (`u:`): a note goes stale only when a sentence that cites it, or a table row of its
part, changes."""
import pytest

import mem
import syntheses

ONE = "../knowledge/computing/one-note.md"
TWO = "../knowledge/computing/two-note.md"
FREE = "../knowledge/computing/free-note.md"
SYN = "syntheses/attention.md"
SOURCES = f"Sources: [one]({ONE}), [two]({TWO}), [free]({FREE})"
BODY = (f"Sentence about one.[o]({ONE}) Sentence about two.[t]({TWO}) A plain sentence.\n\n"
        f"| col | val |\n|---|---|\n| row | x |\n\n{SOURCES}")


def text_in(tmp_path, text, name="body.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def note_body(claim):
    return (f"## Claim\n\n{claim}\n\n## Evidence\n\nObserved.\n\n## Applies when\n\nAlways.\n\n"
            "## Does not apply when\n\nNever.\n")


@pytest.fixture
def run(hub_root, capsys):
    def go(*argv):
        code = mem.main(["--root", str(hub_root), *argv])
        out = capsys.readouterr()
        return code, out.out, out.err
    return go


@pytest.fixture
def made(run, tmp_path, hub_root):
    assert run("synthesis", "new", "--title", "Attention", "--topics", "ml", "--slug", "attention",
               "--summary-file", text_in(tmp_path, "How attention works here.\n", "s.md"))[0] == 0
    for slug in ("one-note", "two-note", "free-note"):
        assert run("new", "knowledge", "--slug", slug, "--claim", f"Claim of {slug}", "--topics", "ml",
                   "--confidence", "low", "--level", "basic", "--origin", "experience", "--body-file",
                   text_in(tmp_path, note_body(f"Claim of {slug}"), f"{slug}.md"))[0] == 0
    assert run("synthesis", "add", "s:attention", "--section", "Alpha", "--body-file", text_in(tmp_path, BODY + "\n", "p.md"))[0] == 0
    for slug in ("one-note", "two-note", "free-note"):
        assert run("synthesis", "attach", slug, "s:attention#alpha")[0] == 0
    return hub_root


def part(root):
    return next(s.text for s in syntheses.load_one(root / SYN).sections if s.handle == "alpha")


def note_path(root, slug):
    return next((root / "knowledge").glob(f"*/{slug}.md"))


def stamp(root, slug):
    return mem.split_frontmatter(note_path(root, slug).read_text(encoding="utf-8"))[0]["part_of_hash"]


def current(root, slug):
    return syntheses.is_current(stamp(root, slug), part(root), f"../knowledge/computing/{slug}.md")


def set_stamp(root, slug, old, new):
    p = note_path(root, slug)
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def edit(run, tmp_path, old, new):
    return run("synthesis", "edit", "s:attention#alpha", "--body-file",
               text_in(tmp_path, BODY.replace(old, new) + "\n", "e.md"))


def test_fingerprint_shape_and_whole_part_fallback():
    assert syntheses.note_fingerprint(BODY, ONE).startswith("u:")
    assert syntheses.note_fingerprint(BODY, "../knowledge/computing/./one-note.md") == syntheses.note_fingerprint(BODY, ONE)
    assert syntheses.note_fingerprint(BODY, "../knowledge/computing/one%2Dnote.md") == syntheses.note_fingerprint(BODY, ONE)
    assert syntheses.note_fingerprint(BODY, "../knowledge/computing/one-note.md#part") == syntheses.note_fingerprint(BODY, ONE)
    assert syntheses.note_fingerprint(BODY, ONE) != syntheses.note_fingerprint(BODY, TWO)
    assert syntheses.note_fingerprint(BODY, FREE) == syntheses.fingerprint(BODY)  # (g)


def test_is_current_by_prefix():
    fp = syntheses.note_fingerprint(BODY, ONE)
    assert syntheses.is_current(fp, BODY, ONE) and not syntheses.is_current(fp, BODY)
    assert syntheses.is_current(syntheses.fingerprint(BODY), BODY)
    assert syntheses.is_current(syntheses.fingerprint_legacy(BODY), BODY, ONE)


def test_attach_stamps_per_note(made):
    assert stamp(made, "one-note") == syntheses.note_fingerprint(part(made), ONE)
    assert stamp(made, "one-note").startswith("u:")
    assert stamp(made, "free-note") == syntheses.fingerprint(part(made))  # (g)
    assert mem.check(made) == []


def test_editing_a_sentence_stales_only_the_notes_it_cites(made, run, tmp_path):  # (a)
    assert edit(run, tmp_path, "Sentence about one.", "Sentence about one, changed.")[0] == 0
    assert not current(made, "one-note")
    assert current(made, "two-note")
    assert not current(made, "free-note")  # whole-part rule, as before


def test_appending_a_sentence_stales_no_per_note_stamp(made, run, tmp_path):  # (b)
    assert run("synthesis", "append", "s:attention#alpha", "--body-file", text_in(tmp_path, "A brand new sentence.\n", "a.md"))[0] == 0
    assert "brand new" in part(made)
    assert current(made, "one-note") and current(made, "two-note")


def test_changing_a_table_row_stales_every_per_note_stamp(made, run, tmp_path):  # (c)
    assert edit(run, tmp_path, "| row | x |", "| row | y |")[0] == 0
    assert not current(made, "one-note") and not current(made, "two-note")


def test_old_whole_part_stamp_keeps_its_meaning(made, run, tmp_path):  # (d)
    old = syntheses.fingerprint(part(made))
    set_stamp(made, "one-note", stamp(made, "one-note"), old)
    assert current(made, "one-note")
    assert run("synthesis", "append", "s:attention#alpha", "--body-file", text_in(tmp_path, "Another sentence.\n", "a.md"))[0] == 0
    assert not current(made, "one-note")
    set_stamp(made, "one-note", old, syntheses.fingerprint_legacy(part(made)))
    assert current(made, "one-note")


def test_a_note_that_was_stale_stays_stale_after_refs(made, run, tmp_path):  # (e)
    set_stamp(made, "one-note", stamp(made, "one-note"), "u:0123456789")
    assert not current(made, "one-note")
    refs = text_in(tmp_path, "alpha | 3 | add " + ONE + "\n", "refs.txt")
    assert run("synthesis", "refs", "s:attention", "--file", refs)[0] == 0
    assert stamp(made, "one-note") == "u:0123456789" and not current(made, "one-note")
    assert current(made, "two-note")
    assert "one-note  s:attention#alpha" in run("curate", "--notes")[1]


def test_refs_restamps_a_current_member_and_restore_returns_it(made, run, tmp_path):  # (f)
    def files():
        return {p.relative_to(made).as_posix(): p.read_bytes() for p in sorted(made.rglob("*"))
                if p.is_file() and not p.name.startswith(".curation-log")}
    before = files()
    refs = text_in(tmp_path, "alpha | 3 | add " + ONE + "\n", "refs.txt")
    assert run("synthesis", "refs", "s:attention", "--file", refs)[0] == 0
    assert stamp(made, "one-note") == syntheses.note_fingerprint(part(made), ONE)
    assert current(made, "one-note") and current(made, "two-note")
    assert files() != before
    assert run("restore", "s:attention")[0] == 0
    assert files() == before
    assert current(made, "one-note")


def test_duplicate_units_count_as_a_multiset(tmp_path):  # (h)
    twice = f"Same words.[o]({ONE}) Same words.[o]({ONE})\n\n{SOURCES}"
    once = f"Same words.[o]({ONE})\n\n{SOURCES}"
    assert syntheses.note_fingerprint(twice, ONE) != syntheses.note_fingerprint(once, ONE)
    assert syntheses.note_fingerprint(twice, ONE) == syntheses.note_fingerprint(twice.replace("Same words.", "Same  words."), ONE)


def test_new_with_part_of_stamps_the_note_fingerprint(made, run, tmp_path):
    assert run("new", "knowledge", "--slug", "late-note", "--claim", "Claim of late", "--topics", "ml",
               "--confidence", "low", "--level", "basic", "--origin", "experience", "--part-of", "s:attention#alpha",
               "--body-file", text_in(tmp_path, note_body("Claim of late"), "l.md"))[0] == 0
    assert stamp(made, "late-note") == syntheses.fingerprint(part(made))
    assert mem.check(made) == []
