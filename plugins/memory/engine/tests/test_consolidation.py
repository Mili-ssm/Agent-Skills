"""Stage 5b task 2: unified notes (`mem unify`), superseded notes, `distinct` for notes and the two curation blocks."""
import pytest

import mem

TODAY = "2026-11-17"


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


def note_body(claim, evidence="Observed."):
    return (f"## Claim\n\n{claim}\n\n## Evidence\n\n{evidence}\n\n## Applies when\n\nAlways.\n\n"
            "## Does not apply when\n\nNever.\n")


@pytest.fixture
def make(run, tmp_path):
    def go(slug, claim, topics="llm", confidence="medium", evidence="Observed."):
        code, _, err = run("new", "knowledge", "--slug", slug, "--claim", claim, "--topics", topics,
                           "--confidence", confidence, "--level", "intermediate", "--origin", "experience",
                           "--body-file", text_file(tmp_path, note_body(claim, evidence), f"{slug}.txt"))
        assert code == 0, err
    return go


def path_of(hub_root, slug):
    return next((hub_root / "knowledge").glob(f"*/{slug}.md"))


def meta_of(hub_root, slug):
    meta, _, _ = mem.split_frontmatter(path_of(hub_root, slug).read_text(encoding="utf-8"))
    return meta


def snapshot(hub_root):
    return {p: p.read_bytes() for p in hub_root.rglob("*.md")}


KEEP, B, C = "quartz-widgets-shrink-under-load", "amber-gadgets-expand-under-heat", "cobalt-sprockets-bend-under-stress"


@pytest.fixture
def three(make, tmp_path, run, hub_root):
    """Three notes, C in another topic folder; each is linked from another note."""
    make(KEEP, "Quartz widgets shrink under load", "llm")
    make(B, "Amber gadgets expand under heat", "ml")
    make(C, "Cobalt sprockets bend under stress", "biology")
    make("linker-of-keep", "Zinc hinges rust slowly", "llm", evidence=f"See [k]({KEEP}.md).")
    make("linker-of-amber", "Brass levers snap suddenly", "llm", evidence=f"See [a]({B}.md).")
    make("linker-of-cobalt", "Tin gears wobble", "biology", evidence=f"See [c]({C}.md).")
    make("cross-linker", "Lead pipes corrode", "llm", evidence=f"See [c](../biology/{C}.md).")
    return text_file(tmp_path, note_body("Widgets, gadgets and sprockets change shape under physical stress"), "u.md")


def test_unify_three_notes_leaves_one_findable_and_no_broken_link(run, three, hub_root):
    code, out, err = run("unify", KEEP, B, C, "--body-file", three)
    assert (code, err) == (0, ""), err
    assert out == f"{KEEP}\tunified from 3 notes, 3 links rewritten\n"
    for words in ("amber gadgets expand heat", "cobalt sprockets bend stress", "quartz widgets shrink load"):
        _, found, _ = run("search", words, "--scope", "notes")
        listed = [ln.split("\t")[0] for ln in found.splitlines() if ln.startswith("knowledge/")]
        assert f"knowledge/computing/{KEEP}.md" in listed
        assert not any(B in ln or C in ln for ln in listed)
    assert run("check")[:2] == (0, "")
    assert f"(../computing/{KEEP}.md)" in path_of(hub_root, "linker-of-cobalt").read_text(encoding="utf-8")
    assert f"({KEEP}.md)" in path_of(hub_root, "cross-linker").read_text(encoding="utf-8")
    assert f"({KEEP}.md)" in path_of(hub_root, "linker-of-amber").read_text(encoding="utf-8")
    assert meta_of(hub_root, B)["superseded_by"] == KEEP
    assert meta_of(hub_root, C)["superseded_by"] == KEEP


def test_unify_takes_union_of_topics_and_lowest_confidence(run, make, three, hub_root):
    make("high-note", "Ruby panels glow", "biology", confidence="high")
    make("low-note", "Opal panels glow", "llm", confidence="low")
    assert run("unify", "high-note", "low-note", "--body-file", three)[0] == 0
    meta = meta_of(hub_root, "high-note")
    assert meta["confidence"] == "low"
    assert set(meta["topics"]) == {"biology", "llm", "deep-learning", "ml", "computing"}
    assert run("check")[:2] == (0, "")


def test_source_links_survive_unify(run, make, tmp_path, hub_root):
    src = "../../literature/computing/2017-vaswani-attention.md"
    assert run("new", "literature", "--title", "Bert", "--author", "Devlin", "--year", "2018", "--kind", "paper",
               "--level", "intermediate", "--url", "https://example.org/bert", "--topics", "ml", "--slug", "bert-pretraining",
               "--body-file", text_file(tmp_path, "## TL;DR\n\nx\n\n## What the source says\n\nx\n\n"
                                        "## Our interpretation\n\nx\n\n## Relevance\n\nx\n", "lit.md"))[0] == 0
    bert = "../../literature/computing/2018-devlin-bert-pretraining.md"
    for slug, claim in (("first-fact", "Jade rods hum"), ("second-fact", "Onyx rods hum loudly"), ("third-fact", "Agate beads ring")):
        make(slug, claim, evidence=f"[v]({src})")
    make("pair-a", "Pearl lamps flicker", evidence=f"[v]({src}) and [b]({bert})")
    make("pair-b", "Coral lamps dim", evidence=f"[v]({src})")
    vaswani = "literature/computing/2017-vaswani-attention.md"

    def linked_from():
        code, out, _ = run("related", vaswani)
        assert code == 0
        return sorted(ln.split("\t")[1] for ln in out.splitlines() if ln.startswith("linked-from"))
    three_notes = ["first-fact", "second-fact", "third-fact"]
    # the fixture note also links the source
    before = linked_from()
    assert all(any(s in ln for ln in before) for s in three_notes)
    unified = text_file(tmp_path, note_body("Lamps flicker and dim", f"[v]({src}) and [b]({bert})"), "u.md")
    assert run("unify", "pair-a", "pair-b", "--body-file", unified)[0] == 0
    after = linked_from()
    assert all(any(s in ln for ln in after) for s in three_notes)
    assert not any("pair-b" in ln for ln in after) and any("pair-a" in ln for ln in after)
    text = path_of(hub_root, "pair-a").read_text(encoding="utf-8")
    assert src in text and bert in text
    assert run("check")[:2] == (0, "")


def test_unified_body_that_drops_a_link_is_refused_unless_drop(run, make, tmp_path, hub_root):
    src = "../../literature/computing/2017-vaswani-attention.md"
    make("with-link", "Mica sheets flex", evidence=f"[v]({src})")
    make("without-link", "Mica sheets bend")
    unified = text_file(tmp_path, note_body("Mica sheets flex and bend"), "u.md")
    before = snapshot(hub_root)
    code, out, err = run("unify", "with-link", "without-link", "--body-file", unified)
    assert code == 1 and out == ""
    assert "the unified text drops the links literature/computing/2017-vaswani-attention.md; use --drop if that is meant." in err
    assert snapshot(hub_root) == before
    code, out, err = run("unify", "with-link", "without-link", "--body-file", unified, "--drop")
    assert code == 0, err
    assert run("check")[:2] == (0, "")


def test_restore_gives_every_file_back_byte_for_byte(run, three, hub_root):
    before = snapshot(hub_root)
    assert run("unify", KEEP, B, C, "--body-file", three)[0] == 0
    assert snapshot(hub_root) != before
    code, out, err = run("restore", KEEP)
    assert code == 0, err
    assert snapshot(hub_root) == before
    assert run("check")[:2] == (0, "")


def test_restore_refuses_when_one_file_changed_since(run, three, hub_root):
    assert run("unify", KEEP, B, C, "--body-file", three)[0] == 0
    after = snapshot(hub_root)
    other = path_of(hub_root, B)
    other.write_text(other.read_text(encoding="utf-8") + "\nEdited later.\n", encoding="utf-8")
    edited = snapshot(hub_root)
    code, _, err = run("restore", KEEP)
    assert code == 2 and B in err
    assert snapshot(hub_root) == edited != after


def test_refusals(run, make, tmp_path, hub_root):
    make("one-note", "Basalt slabs crack")
    make("two-note", "Granite slabs crack")
    make("third-note", "Slate slabs crack")
    body = text_file(tmp_path, note_body("Slabs crack"), "u.md")
    before = snapshot(hub_root)
    assert run("unify", "one-note", "one-note", "--body-file", body)[0] == 1
    assert run("unify", "one-note", "two-note", "two-note", "--body-file", body)[0] == 1
    code, _, err = run("unify", "one-note", "2017-vaswani-attention", "--body-file", body)
    assert code == 1 and "different types" in err
    assert run("unify", "one-note", "no-such-note", "--body-file", body)[0] == 1
    assert snapshot(hub_root) == before
    assert run("unify", "one-note", "two-note", "--body-file", body)[0] == 0
    code, _, err = run("unify", "third-note", "two-note", "--body-file", body)
    assert code == 1 and "already superseded" in err
    code, _, err = run("unify", "two-note", "third-note", "--body-file", body)
    assert code == 1 and "already superseded" in err
    code, _, err = run("unify", "third-note", "one-note", "--body-file", body)
    assert code == 1 and "already superseded" in err


def test_a_note_other_notes_are_superseded_by_cannot_be_unified_into_another(run, make, tmp_path, hub_root):
    for slug, claim in (("basalt-note", "Basalt slabs crack"), ("granite-note", "Granite slabs crack"),
                        ("slate-note", "Slate slabs crack")):
        make(slug, claim)
    body = text_file(tmp_path, note_body("Slabs crack"), "u.md")
    assert run("unify", "basalt-note", "granite-note", "--body-file", body)[0] == 0
    code, _, err = run("unify", "slate-note", "basalt-note", "--body-file", body)
    assert code == 1 and "superseded by basalt-note" in err
    assert run("check")[:2] == (0, "")


def test_unify_is_refused_when_check_fails_and_nothing_changes(run, make, tmp_path, hub_root):
    make("good-a", "Basalt slabs crack")
    make("good-b", "Granite slabs crack")
    before = snapshot(hub_root)
    code, out, err = run("unify", "good-a", "good-b", "--body-file", text_file(tmp_path, "No headings here.\n"))
    assert code == 1 and "problems" in err
    assert snapshot(hub_root) == before


def test_superseded_note_is_hidden_marked_and_not_counted(run, make, tmp_path, hub_root):
    make("basalt-note", "Basalt slabs crack")
    make("granite-note", "Granite slabs crack")
    counted = mem._count_notes(hub_root)
    assert run("unify", "basalt-note", "granite-note", "--body-file", text_file(tmp_path, note_body("Slabs crack"), "u.md"))[0] == 0
    for cmd in (("search", "granite slabs"), ("find", "--type", "knowledge"), ("related", "basalt-note")):
        _, plain, _ = run(*cmd)
        _, with_flag, _ = run(*cmd, "--superseded")
        assert "granite-note" not in plain
    assert "granite-note" in run("search", "granite slabs", "--superseded")[1]
    assert "granite-note" in run("find", "--type", "knowledge", "--superseded")[1]
    code, out, _ = run("show", "granite-note")
    assert out.splitlines()[1] == "superseded by: basalt-note"
    readme = (hub_root / "knowledge" / "computing" / "README.md").read_text(encoding="utf-8")
    assert "(granite-note.md)" in readme and "granite-note.md) (superseded)" in readme
    assert "basalt-note.md) (superseded)" not in readme
    assert mem._count_notes(hub_root) == counted - 1
    assert f"Store: {counted - 1} notes." in mem.session_index(hub_root, None, None, mem._today(TODAY))


def test_outputs_are_the_same_with_or_without_the_flag_when_nothing_is_superseded(run, make, hub_root):
    make("basalt-note", "Basalt slabs crack")
    make("granite-note", "Granite slabs crack")
    for cmd in (("search", "slabs"), ("search", "slabs", "--links"), ("find",), ("related", "basalt-note")):
        assert run(*cmd) == run(*cmd, "--superseded")


def test_check_verifies_the_target_of_superseded_by(run, make, hub_root):
    make("basalt-note", "Basalt slabs crack")
    path = path_of(hub_root, "basalt-note")
    path.write_text(path.read_text(encoding="utf-8").replace("updated:", "superseded_by: nowhere\nupdated:"), encoding="utf-8")
    code, out, _ = run("check")
    assert code == 1 and "superseded_by names nowhere" in out


def test_rename_rewrites_superseded_by(run, make, tmp_path, hub_root):
    make("basalt-note", "Basalt slabs crack")
    make("granite-note", "Granite slabs crack")
    assert run("unify", "basalt-note", "granite-note", "--body-file", text_file(tmp_path, note_body("Slabs crack"), "u.md"))[0] == 0
    assert run("rename", "basalt-note", "slabs-crack")[0] == 0
    assert meta_of(hub_root, "granite-note")["superseded_by"] == "slabs-crack"
    assert run("check")[:2] == (0, "")


PAIR_HEAD = ("notes that say the same or the opposite? (decide: mem unify <keep> <other> --body-file …, "
             "mem distinct <a> <b>, or leave)")


def test_distinct_notes_leave_the_pair_queue(run, make, hub_root):
    make("note-a", "Quartz widgets shrink under heavy load")
    make("note-b", "Quartz widgets never shrink under heavy load")
    code, out, _ = run("curate", "--notes")
    day = meta_of(hub_root, "note-a")["updated"]
    assert out == (f"{PAIR_HEAD}\n  note-a  [medium, {day}]  Quartz widgets shrink under heavy load\n"
                   f"  note-b  [medium, {day}]  Quartz widgets never shrink under heavy load\n  differ in: never\n")
    code, out, err = run("distinct", "note-a", "note-b")
    assert (code, out) == (0, "note-a\tkept apart from note-b\n"), err
    assert meta_of(hub_root, "note-a")["distinct_from"] == ["note-b"]
    assert run("curate", "--notes") == (0, "", "")
    assert run("check")[:2] == (0, "")
    assert run("restore", "note-a")[0] == 0  # one undo for both notes
    assert "distinct_from" not in meta_of(hub_root, "note-b")
    assert run("curate", "--notes")[1].startswith(PAIR_HEAD)


def test_pairs_skip_superseded_notes_and_other_topics(run, make, tmp_path, hub_root):
    make("note-a", "Quartz widgets shrink under heavy load", "llm")
    make("note-b", "Quartz widgets shrink under heavy load too", "biology")
    assert run("curate", "--notes") == (0, "", "")


def test_crowded_topics_without_a_synthesis_are_listed(run, make, tmp_path):
    words = "alpha beta gamma delta epsilon zeta eta theta iota kappa".split()
    for i in range(8):
        make(f"crowd-{i}", f"{words[i]} {words[i + 1]}x{i} unique{i} thing{i}s", "algorithms")
    assert run("curate", "--notes") == (0, "topics with 8 notes or more and no synthesis (mem synthesis new)\n"
                                        "  algorithms  8 notes\n", "")
    assert run("synthesis", "new", "--title", "Algorithms", "--topics", "algorithms", "--slug", "algos",
               "--summary-file", text_file(tmp_path, "All about them.\n", "s.md"))[0] == 0
    assert "topics with" not in run("curate", "--notes")[1]


def test_curate_notes_prints_nothing_for_an_empty_queue(run):
    assert run("curate", "--notes") == (0, "", "")


def test_unify_refuses_a_secret_in_the_body_and_writes_nothing(run, make, tmp_path, hub_root):
    make("one-note", "Mica sheets flex")
    make("two-note", "Mica sheets bend")
    unified = text_file(tmp_path, note_body("Mica flexes " + "ghp_" + "a" * 36), "u.md")
    before = snapshot(hub_root)
    code, out, err = run("unify", "one-note", "two-note", "--body-file", unified)
    assert code == 4 and "secret" in err
    assert snapshot(hub_root) == before


def test_a_reference_definition_in_another_note_is_repointed_by_unify(run, make, tmp_path, hub_root):
    make("ref-keep", "Mica sheets flex")
    make("ref-other", "Mica sheets bend")
    make("ref-reader", "Zinc hinges rust", evidence="See [o][r].\n\n[r]: ref-other.md \"title\"")
    unified = text_file(tmp_path, note_body("Mica sheets flex and bend"), "u.md")
    assert run("unify", "ref-keep", "ref-other", "--body-file", unified)[0] == 0
    text = path_of(hub_root, "ref-reader").read_text(encoding="utf-8")
    assert "[r]: ref-keep.md \"title\"" in text and "ref-other.md" not in text
    assert run("check")[:2] == (0, "")


def test_a_unified_body_that_loses_a_reference_style_link_is_refused_unless_drop(run, make, tmp_path, hub_root):
    make("lit-target", "Quartz widgets shrink")
    make("ref-a", "Mica sheets flex", evidence="See [t][r].\n\n[r]: lit-target.md")
    make("ref-b", "Mica sheets bend")
    unified = text_file(tmp_path, note_body("Mica sheets flex and bend"), "u.md")
    before = snapshot(hub_root)
    code, _, err = run("unify", "ref-a", "ref-b", "--body-file", unified)
    assert code == 1 and "drops the links knowledge/" in err and "lit-target.md" in err
    assert snapshot(hub_root) == before
    assert run("unify", "ref-a", "ref-b", "--body-file", unified, "--drop")[0] == 0


def test_restore_gives_back_a_listing_that_was_already_stale_byte_for_byte(run, three, hub_root):
    listing = hub_root / "knowledge" / "README.md"
    text = listing.read_text(encoding="utf-8")
    stale = text.replace("(computing/README.md) | ", "(computing/README.md) | 9", 1)
    assert stale != text
    listing.write_text(stale, encoding="utf-8")
    before = snapshot(hub_root)
    assert run("unify", KEEP, B, C, "--body-file", three)[0] == 0
    assert listing.read_bytes() != stale.encode()
    assert run("restore", KEEP)[0] == 0
    assert snapshot(hub_root) == before


def test_problems_older_than_the_unify_do_not_block_it(run, make, three, hub_root):
    # an imported store: one untouched note and one note the unify rewrites both link a document left behind
    make("old-problem", "Mica sheets peel", "llm", evidence="See [gone](../../docs/left-behind.md).")
    make("linker-with-old-problem", "Slate tiles chip", "llm",
         evidence=f"See [gone](../../docs/left-behind.md).\n\nSee [a]({B}.md).")
    assert run("check")[0] == 1
    code, _, err = run("unify", KEEP, B, C, "--body-file", three)
    assert (code, err) == (0, ""), err
    assert f"({KEEP}.md)" in path_of(hub_root, "linker-with-old-problem").read_text(encoding="utf-8")


def test_a_second_copy_of_an_old_problem_is_a_new_problem(run, make, tmp_path, hub_root):
    gone = "See [gone](../../docs/left-behind.md)."
    make("slabs-a", "Basalt slabs crack", evidence=gone)
    make("slabs-b", "Granite slabs crack")
    before = snapshot(hub_root)
    twice = text_file(tmp_path, note_body("Slabs crack", f"{gone}\n\n{gone}"), "twice.md")
    code, _, err = run("unify", "slabs-a", "slabs-b", "--body-file", twice)
    assert code == 1 and "left-behind.md" in err
    assert snapshot(hub_root) == before
    once = text_file(tmp_path, note_body("Slabs crack", gone), "once.md")
    assert run("unify", "slabs-a", "slabs-b", "--body-file", once)[0] == 0
