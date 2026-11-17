"""`mem synthesis rename | remove | detach | topics`: a synthesis's structure changes only through mem, with undo."""
import pytest

import mem

SRC = "Sources: [attention](../knowledge/computing/attention-replaces-recurrence.md)"
SYN = "syntheses/attention.md"
NOTES = ("one-note", "two-note")


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


@pytest.fixture
def made(run, tmp_path, hub_root):
    """A synthesis `attention` with the parts Alpha and Beta; one-note and two-note are part of Alpha."""
    assert run("synthesis", "new", "--title", "Attention", "--topics", "ml", "--slug", "attention",
               "--summary-file", text_file(tmp_path, "How attention works here.\n", "s.md"))[0] == 0
    for name in ("Alpha", "Beta"):
        assert run("synthesis", "add", "s:attention", "--section", name,
                   "--body-file", text_file(tmp_path, f"Text of {name}.\n\n{SRC}\n", "p.md"))[0] == 0
    for slug in NOTES:
        assert run("new", "knowledge", "--slug", slug, "--claim", f"Claim of {slug}", "--topics", "ml",
                   "--confidence", "low", "--level", "basic", "--origin", "experience", "--body-file",
                   text_file(tmp_path, note_body(f"Claim of {slug}"), f"{slug}.md"))[0] == 0
        assert run("synthesis", "attach", slug, "s:attention#alpha")[0] == 0
    assert run("check")[0] == 0
    return hub_root


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and not p.name.startswith(".curation-log")}


def read(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def note_rel(root, slug):
    return next((root / "knowledge").glob(f"*/{slug}.md")).relative_to(root).as_posix()


def part_of(root, slug):
    meta, _, _ = mem.split_frontmatter(read(root, note_rel(root, slug)))
    return meta.get("part_of"), meta.get("part_of_hash")


# ---- rename ----------------------------------------------------------------------------------------------

def test_rename_changes_the_heading_and_the_notes_part_of_and_keeps_the_hash(run, made):
    hash_before = part_of(made, "one-note")[1]
    code, out, err = run("synthesis", "rename", "s:attention#alpha", "First Part")
    assert (code, err) == (0, "")
    assert out.splitlines() == ["s:attention#first-part\trenamed from alpha",
                                "one-note\tpart of s:attention#first-part",
                                "two-note\tpart of s:attention#first-part"]
    text = read(made, SYN)
    assert "## First Part\n\nText of Alpha." in text and "## Alpha" not in text
    assert "updated: '" in text and "## Beta" in text
    assert part_of(made, "one-note") == ("attention#first-part", hash_before)
    assert part_of(made, "two-note") == ("attention#first-part", hash_before)
    assert run("check")[:2] == (0, "")
    assert "notes older than their section" not in run("curate", "--notes")[1]  # the heading is not in the fingerprint


def test_rename_keeps_a_stale_hash_stale(run, made, tmp_path):
    run("synthesis", "edit", "s:attention#alpha", "--body-file", text_file(tmp_path, f"Changed text of Alpha.\n\n{SRC}\n"),
        "--shrink")
    assert "one-note  s:attention#alpha" in run("curate", "--notes")[1]
    assert run("synthesis", "rename", "s:attention#alpha", "First Part")[0] == 0
    assert "one-note  s:attention#first-part" in run("curate", "--notes")[1]


def test_restore_after_rename_puts_back_every_file_and_keeps_an_earlier_edit(run, made, tmp_path):
    run("synthesis", "edit", "s:attention#alpha", "--body-file", text_file(tmp_path, f"Changed.\n\n{SRC}\n"), "--shrink")
    before = files(made)
    assert run("synthesis", "rename", "s:attention#alpha", "First Part")[0] == 0
    code, out, err = run("restore", "s:attention")
    assert code == 0, err
    assert out.startswith("s:attention\trestored to before rename of ") and "(3 files)" in out
    assert files(made) == before
    assert run("check")[:2] == (0, "")
    assert run("restore", "s:attention")[0] == 0  # the next restore undoes the earlier edit, from the synthesis's log
    assert "Changed." not in read(made, SYN) and "Text of Alpha." in read(made, SYN)


def test_restore_of_a_note_undoes_the_whole_rename(run, made):
    before = files(made)
    assert run("synthesis", "rename", "s:attention#alpha", "First Part")[0] == 0
    assert run("restore", "one-note")[0] == 0
    assert files(made) == before
    assert run("check")[:2] == (0, "")


def test_restore_after_rename_refuses_when_a_member_changed_since(run, made):
    assert run("synthesis", "rename", "s:attention#alpha", "First Part")[0] == 0
    note = made / note_rel(made, "one-note")
    note.write_text(note.read_text(encoding="utf-8") + "\nAn extra line.\n", encoding="utf-8")
    after = files(made)
    code, _, err = run("restore", "s:attention")
    assert code == 2 and "changed since rename" in err
    assert files(made) == after


@pytest.mark.parametrize("heading", ["Beta", "  beta  ", "!!!"])
def test_rename_refuses_a_taken_or_empty_handle(run, made, heading):
    before = files(made)
    assert run("synthesis", "rename", "s:attention#alpha", heading)[0] == 2
    assert files(made) == before


def test_rename_refuses_the_summary_and_a_missing_section(run, made):
    before = files(made)
    assert run("synthesis", "rename", "s:attention#summary", "Overview")[0] == 2
    assert run("synthesis", "rename", "s:attention#nope", "X")[0] == 2
    assert run("synthesis", "rename", "s:attention", "X")[0] == 2
    assert files(made) == before


def test_rename_may_change_only_the_case(run, made):
    assert run("synthesis", "rename", "s:attention#beta", "BETA")[0] == 0
    assert "## BETA" in read(made, SYN)


# ---- remove ----------------------------------------------------------------------------------------------

def test_remove_takes_the_section_out_and_detaches_its_notes(run, made):
    code, out, err = run("synthesis", "remove", "s:attention#alpha")
    assert (code, err) == (0, "")
    assert out.splitlines() == ["s:attention#alpha\tremoved", "one-note\tdetached from s:attention#alpha",
                                "two-note\tdetached from s:attention#alpha"]
    text = read(made, SYN)
    assert "Alpha" not in text and text.endswith(f"## Beta\n\nText of Beta.\n\n{SRC}\n")
    assert part_of(made, "one-note") == (None, None)
    assert run("check")[:2] == (0, "")


def test_remove_the_last_section_leaves_one_final_newline(run, made):
    assert run("synthesis", "remove", "s:attention#beta")[0] == 0
    assert read(made, SYN).endswith(f"{SRC}\n") and not read(made, SYN).endswith("\n\n")
    assert part_of(made, "one-note")[0] == "attention#alpha"


def test_restore_after_remove_puts_back_every_file(run, made):
    before = files(made)
    assert run("synthesis", "remove", "s:attention#alpha")[0] == 0
    code, out, err = run("restore", "s:attention")
    assert code == 0, err
    assert "(3 files)" in out
    assert files(made) == before
    assert run("check")[:2] == (0, "")


def test_remove_refuses_the_summary_and_a_missing_section(run, made):
    before = files(made)
    assert run("synthesis", "remove", "s:attention#summary")[0] == 2
    assert run("synthesis", "remove", "s:attention#nope")[0] == 2
    assert files(made) == before


# ---- detach ----------------------------------------------------------------------------------------------

def test_detach_removes_part_of_and_restore_puts_it_back(run, made):
    before = files(made)
    code, out, err = run("synthesis", "detach", "one-note")
    assert (code, out, err) == (0, "one-note\tdetached from s:attention#alpha\n", "")
    assert part_of(made, "one-note") == (None, None)
    assert part_of(made, "two-note")[0] == "attention#alpha"
    assert run("check")[:2] == (0, "")
    assert run("restore", "one-note")[0] == 0
    assert files(made) == before
    assert run("check")[:2] == (0, "")


def test_detach_refuses_a_note_that_is_not_part_of_anything(run, made):
    assert run("synthesis", "detach", "one-note")[0] == 0
    before = files(made)
    code, _, err = run("synthesis", "detach", "one-note")
    assert code == 2 and "not part of a synthesis" in err
    assert run("synthesis", "detach", "no-such-note")[0] == 2
    assert files(made) == before


# ---- topics ----------------------------------------------------------------------------------------------

def test_topics_replaces_the_list_and_restore_puts_the_file_back(run, made):
    before = files(made)
    code, out, err = run("synthesis", "topics", "s:attention", "ml, algorithms")
    assert (code, out, err) == (0, "s:attention\ttopics ml, algorithms\n", "")
    text = read(made, SYN)
    assert "topics: [ml, algorithms]" in text and "updated: '" in text
    assert text.split("---", 2)[2] == before[SYN].decode().split("---", 2)[2]
    assert run("check")[:2] == (0, "")
    assert run("restore", "s:attention")[0] == 0
    assert files(made) == before


def test_topics_refuses_an_unknown_topic_and_an_empty_list(run, made):
    before = files(made)
    code, _, err = run("synthesis", "topics", "s:attention", "ml,nope")
    assert code == 2 and "unknown topic 'nope'" in err
    assert run("synthesis", "topics", "s:attention", " , ")[0] == 2
    assert run("synthesis", "topics", "s:nope", "ml")[0] == 2
    assert files(made) == before


def test_topics_refuses_a_topic_another_synthesis_lists(run, made, tmp_path):
    assert run("synthesis", "new", "--title", "Other", "--topics", "algorithms", "--slug", "other",
               "--summary-file", text_file(tmp_path, "Other.\n", "o.md"))[0] == 0
    before = files(made)
    code, _, err = run("synthesis", "topics", "s:attention", "ml,algorithms")
    assert code == 2 and "s:other already covers the topic algorithms" in err
    assert files(made) == before


def test_curate_notes_stops_listing_a_topic_once_a_synthesis_names_it(run, made, tmp_path):
    words = "alpha beta gamma delta epsilon zeta eta theta iota kappa".split()
    for i in range(8):
        claim = f"{words[i]} {words[i + 1]}x{i} unique{i} thing{i}s"
        assert run("new", "knowledge", "--slug", f"crowd-{i}", "--claim", claim, "--topics", "algorithms",
                   "--confidence", "low", "--level", "basic", "--origin", "experience", "--body-file",
                   text_file(tmp_path, note_body(claim), f"c{i}.md"))[0] == 0
    assert "  algorithms  8 notes" in run("curate", "--notes")[1]
    assert run("synthesis", "topics", "s:attention", "ml,algorithms")[0] == 0
    assert "topics with" not in run("curate", "--notes")[1]


# ---- guards ----------------------------------------------------------------------------------------------

def test_every_command_needs_a_writable_store(run, made):
    (made / "mem-store.yaml").unlink()
    before = files(made)
    for argv in (("rename", "s:attention#alpha", "X"), ("remove", "s:attention#alpha"), ("detach", "one-note"),
                 ("topics", "s:attention", "ml")):
        code, _, err = run("synthesis", *argv)
        assert code == 2 and "read-only" in err
    assert files(made) == before


def test_rename_refuses_a_secret_in_the_heading(run, made):
    before = files(made)
    assert run("synthesis", "rename", "s:attention#alpha", "ghp_" + "a" * 36)[0] == 4
    assert files(made) == before


@pytest.mark.parametrize("argv", [("rename", "s:attention#alpha", "First Part"), ("remove", "s:attention#alpha"),
                                  ("detach", "one-note"), ("topics", "s:attention", "ml,algorithms")])
def test_a_failed_write_leaves_files_and_log_as_they_were(run, made, monkeypatch, argv):
    before, logs = files(made), {p: p.read_bytes() for p in made.rglob(".curation-log*")}
    real, calls = mem._swap_file, []

    def failing(path, data):
        calls.append(path)
        if len(calls) == 2 or argv[0] in ("detach", "topics"):
            raise OSError("disk full")
        real(path, data)
    monkeypatch.setattr(mem, "_swap_file", failing)
    code, _, err = run("synthesis", *argv)
    assert code == 2 and "disk full" in err
    assert files(made) == before
    assert {p: p.read_bytes() for p in made.rglob(".curation-log*")} == logs


def test_a_file_changed_since_it_was_read_is_refused(run, made, monkeypatch):
    note = made / note_rel(made, "two-note")
    real = mem._write_logged_changes
    original = note.read_bytes()

    def racing(root, changes, *a, **kw):
        note.write_bytes(original + b"\nrace\n")
        return real(root, changes, *a, **kw)
    monkeypatch.setattr(mem, "_write_logged_changes", racing)
    before = files(made)
    code, _, err = run("synthesis", "remove", "s:attention#alpha")
    assert code == 2 and "changed since it was read" in err
    assert {k: v for k, v in files(made).items() if k != note_rel(made, "two-note")} == \
        {k: v for k, v in before.items() if k != note_rel(made, "two-note")}
