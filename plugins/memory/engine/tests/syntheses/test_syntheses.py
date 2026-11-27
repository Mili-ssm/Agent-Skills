import datetime
import re
import time
from pathlib import Path

import mem
import pytest
from syntheses import document

NOTE = "../knowledge/computing/attention-replaces-recurrence.md"
SRC = f"Sources: [attention]({NOTE})"
EXIT_READ_ONLY = 2  # nothing to restore, or the store is read-only
EXIT_SECRET = 4
LONG_LINES = 6000
BIG_PARTS = 60
BIG_OUTLINE_LINES = 62
LINES_PER_BIG_PART = 100
BIG_PART_TEXT_LINES = 500
OUTLINE_BUDGET_SECONDS = 5
INIT_PATH_LINES = 2


@pytest.fixture
def run(hub_root, capsys):
    def go(*argv, stdin=None):
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
    summary = body(tmp_path, "How attention works.\n", "summary.md")
    assert (
        run(
            "synthesis",
            "new",
            "--title",
            "Attention",
            "--topics",
            "computing,ml",
            "--slug",
            "attention",
            "--summary-file",
            summary,
        )[0]
        == 0
    )
    return hub_root / "syntheses" / "attention.md"


def add(run, tmp_path, section, text=None, name="part.md"):
    return run(
        "synthesis",
        "add",
        "s:attention",
        "--section",
        section,
        "--body-file",
        body(tmp_path, text if text is not None else f"Text of {section}.\n\n{SRC}\n", name),
    )


def test_new_prints_handle_and_path_and_writes_template(made, run):
    text = made.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: Attention\ntopics: [computing, ml]\n")
    assert "\n## Summary\n\nHow attention works.\n" in text
    code, out, _ = run("check")
    assert (code, out) == (0, "")


def test_new_output_line(run, tmp_path):
    code, out, _ = run("synthesis", "new", "--title", "T", "--topics", "ml", "--slug", "t-one")
    assert (code, out) == (0, "s:t-one\tsyntheses/t-one.md\n")


def test_new_refuses_existing_unknown_topic_and_bad_slug(run, made):
    assert run("synthesis", "new", "--title", "T", "--topics", "ml", "--slug", "attention")[0] == 1
    assert run("synthesis", "new", "--title", "T", "--topics", "nope", "--slug", "x")[0] == 1
    assert run("synthesis", "new", "--title", "T", "--topics", "ml", "--slug", "Bad Slug")[0] == 1


def test_add_appends_a_section_and_prints_handle(run, made, tmp_path):
    before = made.read_text(encoding="utf-8")
    code, out, _ = add(run, tmp_path, "Why It Works")
    assert (code, out) == (0, "s:attention#why-it-works\tadded\n")
    after = made.read_text(encoding="utf-8")
    assert (
        after.split("\nupdated:")[1].split("\n", 1)[1]
        == before.split("\nupdated:")[1].split("\n", 1)[1]
        + f"\n## Why It Works\n\nText of Why It Works.\n\n{SRC}\n"
    )


def test_add_then_restore_is_byte_identical(run, made, tmp_path):
    before = made.read_bytes()
    add(run, tmp_path, "One")
    add(run, tmp_path, "Two")
    assert run("restore", "s:attention")[0] == 0
    assert run("restore", "s:attention")[0] == 0
    assert made.read_bytes() == before
    code, _, err = run("restore", "s:attention")
    assert code == EXIT_READ_ONLY and "nothing to restore" in err
    assert (made.parent / ".curation-log").is_file()


def test_edit_changes_one_section_and_nothing_else(run, made, tmp_path):
    add(run, tmp_path, "One", f"First.\n\n{SRC}\n", "a.md")
    add(run, tmp_path, "Two", f"Second.\n\n{SRC}\n", "b.md")
    add(run, tmp_path, "Three", f"Third.\n\n{SRC}\n", "c.md")
    before = made.read_text(encoding="utf-8")
    new = body(tmp_path, f"Second, rewritten.\nWith two lines.\n\n{SRC}\n", "n.md")
    code, out, _ = run("synthesis", "edit", "s:attention#two", "--body-file", new)
    assert (code, out) == (0, "s:attention#two\tedited\n")
    after = made.read_text(encoding="utf-8")
    old_part = f"## Two\n\nSecond.\n\n{SRC}\n\n"
    new_part = f"## Two\n\nSecond, rewritten.\nWith two lines.\n\n{SRC}\n\n"
    assert after.replace(new_part, old_part) == before  # `updated` already holds today's date
    run("restore", "s:attention")
    assert made.read_text(encoding="utf-8") == before


def test_edit_the_summary_needs_no_sources_and_last_section_works(run, made, tmp_path):
    assert (
        run(
            "synthesis",
            "edit",
            "s:attention#summary",
            "--body-file",
            body(tmp_path, "New summary.\n"),
            "--shrink",
        )[0]
        == 0
    )
    add(run, tmp_path, "Last")
    assert (
        run(
            "synthesis",
            "edit",
            "s:attention#last",
            "--body-file",
            body(tmp_path, f"Changed.\n\n{SRC}\n", "e.md"),
            "--shrink",
        )[0]
        == 0
    )
    text = made.read_text(encoding="utf-8")
    assert (
        text.endswith(f"## Last\n\nChanged.\n\n{SRC}\n")
        and "## Summary\n\nNew summary.\n\n## Last" in text
    )


def test_repeated_or_case_different_heading_is_refused(run, made, tmp_path):
    assert add(run, tmp_path, "Same")[0] == 0
    code, _, err = add(run, tmp_path, "same")
    assert code == 1 and "already exists" in err
    assert add(run, tmp_path, "Summary")[0] == 1


@pytest.mark.parametrize(
    "text",
    [
        "No sources here.\n",
        "Text.\n\nSources: nothing linked\n",
        "Text.\n\nSources: [x](../knowledge/computing/missing.md)\n",
        "Text.\n\nSources: [x](../../outside.md)\n",
        f"Text.\n\n{SRC}\n\nTrailing paragraph.\n",
    ],
)
def test_a_part_without_valid_sources_is_refused_and_file_unchanged(run, made, tmp_path, text):
    before = made.read_bytes()
    code, _, err = add(run, tmp_path, "Bad", text)
    assert code == 1 and err.startswith("mem:")
    assert made.read_bytes() == before
    assert (
        run(
            "synthesis",
            "edit",
            "s:attention#summary",
            "--body-file",
            body(tmp_path, "ok.\n", "s.md"),
            "--shrink",
        )[0]
        == 0
    )
    assert document.validate_section(text, made.parent.parent)


def test_a_section_body_may_not_hold_a_heading(run, made, tmp_path):
    code, _, err = add(run, tmp_path, "Odd", f"Text.\n\n## Sneaky\n\nMore.\n\n{SRC}\n")
    assert code == 1 and "heading" in err


def test_validate_section_accepts_a_note_link(hub_root):
    assert document.validate_section(f"x\n\n{SRC}\n", hub_root) == []
    assert document.section_handle("Why  it's: Ünicode!") == "why-it-s-unicode"


def test_list_and_stats(run, made, tmp_path):
    add(run, tmp_path, "One")
    add(run, tmp_path, "Two", name="p2.md")
    today = datetime.date.today().isoformat()
    assert run("synthesis", "list")[1] == f"s:attention\t2 parts, updated {today}\tAttention\n"
    assert run("synthesis", "list", "--topic", "computing")[1].startswith("s:attention")
    assert not run("synthesis", "list", "--topic", "biology")[1]
    assert "syntheses: 1 (2 parts)\n" in run("stats")[1]


def test_stats_has_no_line_without_syntheses(run):
    assert "syntheses" not in run("stats")[1]


def test_show_whole_outline_section_and_part(run, made, tmp_path):
    add(run, tmp_path, "One")
    add(run, tmp_path, "Two", name="p2.md")
    code, out, _ = run("show", "s:attention")
    assert code == 0 and "## One" in out and "## Two" in out
    code, out, _ = run("show", "s:attention", "--outline", "--ranges")
    lines = out.splitlines()
    assert lines[1].endswith("\t## Summary") and lines[2].endswith("\t## One")
    start, _ = lines[2].split("\t")[0].split("-")
    file_lines = made.read_text(encoding="utf-8").split("\n")
    assert file_lines[int(start) - 1] == "## One"
    code, out, _ = run("show", "s:attention", "--section", "Two")
    assert "## Two" in out and "## One" not in out
    code, out, _ = run("show", "s:attention#one")
    assert (
        out.splitlines()[0] == "== s:attention#one"
        and "Text of One." in out
        and "Text of Two." not in out
    )
    assert run("show", "s:attention#nope")[0] == 1
    assert run("show", "s:nope")[0] == 1


def test_a_synthesis_of_thousands_of_lines_has_a_cheap_outline(run, made, tmp_path):
    for i in range(BIG_PARTS):
        add(
            run,
            tmp_path,
            f"Part {i}",
            f"{'line of text ' * 5}\n" * LINES_PER_BIG_PART + f"\n{SRC}\n",
            f"p{i}.md",
        )
    assert len(made.read_text(encoding="utf-8").split("\n")) > LONG_LINES
    start = time.perf_counter()
    code, out, _ = run("show", "s:attention", "--outline", "--ranges")
    assert code == 0 and len(out.splitlines()) == BIG_OUTLINE_LINES
    code, out, _ = run("show", "s:attention#part-59")
    assert (
        out.count("line of text") == BIG_PART_TEXT_LINES
        and time.perf_counter() - start < OUTLINE_BUDGET_SECONDS
    )


SEARCH = ["search", "attention recurrence", "--deep"]


def test_search_without_syntheses_is_unchanged_and_with_one_the_notes_come_first(
    run, made, tmp_path
):
    made.unlink()
    plain = run(*SEARCH)
    assert plain[0] == 0 and "attention-replaces-recurrence" in plain[1]
    (made.parent).mkdir(exist_ok=True)
    assert run(*SEARCH) == plain  # an empty folder changes nothing
    code, _, _ = run(
        "synthesis", "new", "--title", "Attention", "--topics", "ml", "--slug", "attention"
    )
    add(
        run, tmp_path, "Recurrence in depth", f"Why recurrence is replaced by attention.\n\n{SRC}\n"
    )
    code, out, err = run(*SEARCH)
    assert code == 0 and err == plain[2]
    assert out.startswith(plain[1])
    assert out[len(plain[1]) :] == (
        "-- syntheses (extended versions) --\n"
        "s:attention#recurrence-in-depth\tAttention: Recurrence in depth\n"
    )


def test_default_search_prints_no_synthesis_and_hints_at_deep(run, made, tmp_path):
    add(run, tmp_path, "Recurrence", f"attention recurrence.\n\n{SRC}\n")
    code, out, _ = run("search", "attention recurrence")
    assert code == 0 and "-- syntheses" not in out
    assert "-- syntheses" in run(*SEARCH)[1]


def test_search_prints_at_most_two_syntheses_lines_ordered_by_heading_terms(run, made, tmp_path):
    add(run, tmp_path, "Other", f"attention recurrence and more.\n\n{SRC}\n")
    add(run, tmp_path, "Attention recurrence", f"x.\n\n{SRC}\n", "b.md")
    add(run, tmp_path, "Third", f"attention recurrence again.\n\n{SRC}\n", "c.md")
    lines = run(*SEARCH)[1].split("-- syntheses (extended versions) --\n")[1].splitlines()
    assert [ln.split("\t")[0] for ln in lines] == [
        "s:attention#attention-recurrence",
        "s:attention#other",
    ]


def test_search_prints_no_synthesis_with_offset_filter_paths_or_scope(run, made, tmp_path):
    add(run, tmp_path, "Recurrence", f"attention recurrence.\n\n{SRC}\n")
    assert "-- syntheses" in run(*SEARCH)[1]
    for extra in (
        ["--offset", "0", "--type", "knowledge"],
        ["--detail", "paths"],
        ["--scope", "notes"],
        ["--scope", "memories"],
    ):
        assert "-- syntheses" not in run(*SEARCH, *extra)[1], extra
    assert "-- syntheses" not in run(*SEARCH, "--offset", "1")[1]


def test_check_reports_each_problem(run, made, hub_root, tmp_path):
    add(run, tmp_path, "One")
    text = made.read_text(encoding="utf-8")
    made.write_text(
        text.replace("topics: [computing, ml]", "topics: [computing, nope]")
        + f"\n## One\n\nAgain.\n\n{SRC}\n\n## Bare\n\nNo sources.\n",
        encoding="utf-8",
    )
    (made.parent / "broken.md").write_text("no frontmatter\n", encoding="utf-8")
    code, out, _ = run("check")
    assert code == 1
    assert "syntheses/attention.md:1: unknown topic 'nope'" in out
    assert 'repeated section handle "one"' in out
    assert 'section "Bare": the part must end with a `Sources:` line' in out
    assert "syntheses/broken.md:1: synthesis cannot be parsed" in out
    assert "not allowed here" not in out


def test_check_reports_a_broken_source_link(run, made, tmp_path):
    add(run, tmp_path, "One")
    (made.parent.parent / "knowledge/computing/attention-replaces-recurrence.md").rename(
        made.parent.parent / "knowledge/computing/moved.md"
    )
    out = run("check")[1]
    assert (
        'section "One": source ../knowledge/computing/attention-replaces-recurrence.md is not an existing note'
        in out
    )


def test_commands_need_the_marker_and_list_show_search_do_not(hub_root, tmp_path, capsys):
    made = hub_root / "syntheses"
    made.mkdir()
    (hub_root / "mem-store.yaml").unlink()
    root = ["--root", str(hub_root)]
    for argv in (
        ["synthesis", "new", "--title", "T", "--topics", "ml", "--slug", "t"],
        ["synthesis", "add", "s:t", "--section", "H", "--body-file", body(tmp_path, "x\n")],
        ["synthesis", "edit", "s:t#h", "--body-file", body(tmp_path, "x\n")],
        ["restore", "s:t"],
    ):
        assert mem.main([*root, *argv]) == EXIT_READ_ONLY
        assert "writes to the store, which is read-only" in capsys.readouterr().err
    assert not any(made.iterdir())
    assert mem.main([*root, "synthesis", "list"]) == 0
    assert mem.main([*root, "search", "attention"]) == 0


def test_init_creates_the_folder_and_accepts_it_again(tmp_path, capsys):
    store = tmp_path / "s"
    assert mem.main(["init", str(store)]) == 0
    assert (store / "syntheses").is_dir()
    assert mem.main(["init", str(store)]) == 0
    assert mem.main(["--root", str(store), "check"]) == 0
    assert (
        capsys.readouterr().out.count("\n") == INIT_PATH_LINES
    )  # the two init paths; check printed nothing


def test_syntheses_and_records_import_nothing_from_mem():
    for folder, name in (
        ("syntheses", "document.py"),
        ("syntheses", "units.py"),
        ("syntheses", "edit.py"),
        ("memories", "records.py"),
    ):
        src = (Path(__file__).resolve().parent.parent.parent / folder / name).read_text(
            encoding="utf-8"
        )
        assert not re.search(r"^\s*(import|from) mem\b", src, re.MULTILINE)


def test_load_never_raises(tmp_path):
    folder = tmp_path / "syn"
    folder.mkdir()
    (folder / "a.md").write_bytes(b"\xff\xfe")
    (folder / "b.md").write_text(
        "---\ntitle: T\ntopics: x\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n",
        encoding="utf-8",
    )
    assert [s.error is not None for s in document.load(folder)] == [True, True]
    assert document.load(tmp_path / "none") == []


def test_a_secret_in_a_section_or_the_summary_is_refused(run, made, tmp_path):
    secret = "ghp_" + "a1b2c3d4e5f6g7h8i9j0k1l2"  # fake parts, never a real token
    before = made.read_bytes()
    code, _, err = add(run, tmp_path, "Keys", f"Use {secret}.\n\n{SRC}\n")
    assert code == EXIT_SECRET and "GitHub token" in err and made.read_bytes() == before
    assert (
        run(
            "synthesis",
            "new",
            "--title",
            "T",
            "--topics",
            "biology",
            "--slug",
            "t-two",
            "--summary-file",
            body(tmp_path, f"{secret}\n", "s.md"),
        )[0]
        == EXIT_SECRET
    )
    assert not (made.parent / "t-two.md").exists()
    assert (
        run(
            "synthesis",
            "edit",
            "s:attention#summary",
            "--body-file",
            body(tmp_path, f"{secret}\n", "e.md"),
        )[0]
        == EXIT_SECRET
    )
    assert made.read_bytes() == before


OLD_PARAGRAPH = "Attention lets every token read every other token in one step."


def _section_with(run, tmp_path, text):
    assert add(run, tmp_path, "Mechanism", f"{text}\n\n{SRC}\n")[0] == 0


def test_edit_refuses_a_paragraph_swapped_for_other_text_of_the_same_length(run, made, tmp_path):
    _section_with(run, tmp_path, OLD_PARAGRAPH)
    before = made.read_bytes()
    swapped = "Recurrent layers pass one hidden state along a very long chain!"
    assert len(swapped.split()) == len(OLD_PARAGRAPH.split())
    code, _, err = run(
        "synthesis",
        "edit",
        "s:attention#mechanism",
        "--body-file",
        body(tmp_path, f"{swapped}\n\n{SRC}\n", "e.md"),
    )
    assert code == 1 and "drops 1 sentences; use --shrink if that is meant." in err
    assert made.read_bytes() == before


def test_edit_that_only_adds_text_passes_without_shrink(run, made, tmp_path):
    _section_with(run, tmp_path, OLD_PARAGRAPH)
    longer = f"{OLD_PARAGRAPH}\nIt also costs memory that grows with the square of the length."
    assert (
        run(
            "synthesis",
            "edit",
            "s:attention#mechanism",
            "--body-file",
            body(tmp_path, f"{longer}\n\n{SRC}\n", "e.md"),
        )[0]
        == 0
    )


def test_fixing_a_typo_inside_a_sentence_needs_shrink_by_design(run, made, tmp_path):
    # Accepted behavior: any rewritten sentence counts as dropped; small fixes need --shrink.
    _section_with(run, tmp_path, OLD_PARAGRAPH.replace("every", "evry", 1))
    fixed = body(tmp_path, f"{OLD_PARAGRAPH}\n\n{SRC}\n", "e.md")
    assert run("synthesis", "edit", "s:attention#mechanism", "--body-file", fixed)[0] == 1
    assert (
        run("synthesis", "edit", "s:attention#mechanism", "--body-file", fixed, "--shrink")[0] == 0
    )
