import pytest

import mem
from test_check import edit, has, know, lit


def block(root, folder):
    text = (root / folder / "README.md").read_text(encoding="utf-8")
    return text.split(mem.INDEX_START)[1].split(mem.INDEX_END)[0]


def test_index_empty_folder(hub_root):
    lit(hub_root).unlink()
    mem.apply_index(hub_root)
    assert block(hub_root, "literature") == "\n_No entries yet._\n"


def test_index_literature_row(hub_root):
    mem.apply_index(hub_root)
    row = "| 2017 | [Attention Is All You Need](2017-vaswani-attention.md) | paper | advanced | llm |"
    assert row in domain_block(hub_root, "literature", "computing")


def test_index_research_links_readme(hub_root):
    mem.apply_index(hub_root)
    assert "2026-11-llm-eval-methods/README.md" in block(hub_root, "research")


def test_index_keeps_text_outside_block(hub_root):
    readme = hub_root / "literature" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nFooter\n", encoding="utf-8")
    mem.apply_index(hub_root)
    assert "Footer" in readme.read_text(encoding="utf-8")


def test_index_appends_missing_markers(hub_root):
    readme = hub_root / "knowledge" / "README.md"
    readme.write_text("# Knowledge\n", encoding="utf-8")
    assert "knowledge/README.md" in mem.apply_index(hub_root)
    text = readme.read_text(encoding="utf-8")
    assert mem.INDEX_START in text and mem.INDEX_END in text
    assert mem.apply_index(hub_root) == []


def test_stale_index_detected(hub_root):
    mem.apply_index(hub_root)
    assert mem.check(hub_root) == []
    new = hub_root / "literature" / "computing" / "2018-devlin-bert.md"
    new.write_text(lit(hub_root).read_text(encoding="utf-8"), encoding="utf-8")
    assert has(mem.check(hub_root), "literature/README.md", "index stale")


def test_broken_relative_link(hub_root):
    path = know(hub_root)
    path.write_text(path.read_text(encoding="utf-8") + "\n[x](../../literature/missing.md)\n", encoding="utf-8")
    line = path.read_text(encoding="utf-8").split("\n").index("[x](../../literature/missing.md)") + 1
    problems = mem.check(hub_root)
    assert any(p.path == "knowledge/computing/attention-replaces-recurrence.md" and p.line == line
               and "broken link" in p.message for p in problems)


def test_link_anchor_and_external_ok(hub_root):
    path = know(hub_root)
    path.write_text(path.read_text(encoding="utf-8")
                    + "\n[a](../../literature/computing/2017-vaswani-attention.md#tl-dr)\n[b](https://x.org)\n",
                    encoding="utf-8")
    assert not any("broken link" in p.message for p in mem.check(hub_root))


def test_links_in_code_are_ignored(hub_root):
    path = know(hub_root)
    path.write_text(path.read_text(encoding="utf-8")
                    + "\n`[t](nope.md)` and ``a ` [t](nope.md)``\n\n```\n[t](nope.md)\n```\n",
                    encoding="utf-8")
    assert not any("broken link" in p.message for p in mem.check(hub_root))


def test_links_ignored_under_code_and_fixtures(hub_root):
    for sub in ("research/2026-11-llm-eval-methods/code", "tools/tests/fixtures/x", ".hidden"):
        folder = hub_root / sub
        folder.mkdir(parents=True)
        (folder / "README.md").write_text("[t](nope.md)\n", encoding="utf-8")
    assert not any("broken link" in p.message for p in mem.check(hub_root))


def add_to_knowledge(root, text):
    path = know(root)
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")
    return path


def broken(root):
    return [p for p in mem.check(root) if "broken link" in p.message]


def test_titled_link_to_missing_file(hub_root):
    add_to_knowledge(hub_root, '\n[a](missing.md "title")\n')
    assert len(broken(hub_root)) == 1


def test_angle_bracket_targets(hub_root):
    (hub_root / "knowledge" / "computing" / "d e.md").write_text("x\n", encoding="utf-8")
    add_to_knowledge(hub_root, "\n[c](<d e.md>)\n")
    assert broken(hub_root) == []
    add_to_knowledge(hub_root, "\n[c](<no such.md>)\n")
    assert len(broken(hub_root)) == 1


def test_parenthesized_filename(hub_root):
    (hub_root / "knowledge" / "computing" / "g(1).md").write_text("x\n", encoding="utf-8")
    add_to_knowledge(hub_root, "\n[f](g(1).md)\n")
    assert broken(hub_root) == []


def test_stray_backticks_do_not_hide_links(hub_root):
    add_to_knowledge(hub_root, "\nstray ` here\n\n[bad](nope.md)\n\nanother ` there\n")
    assert len(broken(hub_root)) == 1


def test_line_number_after_multiline_fence(hub_root):
    path = add_to_knowledge(hub_root, "\n```\na\nb\nc\n```\n\n[bad](nope.md)\n")
    line = path.read_text(encoding="utf-8").split("\n").index("[bad](nope.md)") + 1
    assert [p.line for p in broken(hub_root)] == [line]


def test_index_unusable_topics_returns_1(hub_root):
    (hub_root / "topics.yaml").unlink()
    assert mem.main(["--root", str(hub_root), "index"]) == 1


def _row_titles(root, folder):
    text = block(root, folder) if folder == "research" else domain_block(root, folder, "computing")
    lines = [ln for ln in text.split("\n") if "](" in ln]
    return [ln.split(" | ")[1] if folder != "knowledge" else ln.split(" | ")[0] for ln in lines]


def test_index_sort_orders(hub_root):
    base = lit(hub_root).read_text(encoding="utf-8")
    for name, year in (("2019-adams-b.md", 2019), ("2019-adams-a.md", 2019), ("2021-zed-c.md", 2021)):
        (hub_root / "literature" / "computing" / name).write_text(base.replace("year: 2017", f"year: {year}"), encoding="utf-8")
    kbase = know(hub_root).read_text(encoding="utf-8")
    (hub_root / "knowledge" / "computing" / "aaa-first.md").write_text(kbase, encoding="utf-8")
    rbase = (hub_root / "research" / "2026-11-llm-eval-methods" / "README.md").read_text(encoding="utf-8")
    for folder, month in (("2026-12-b", "2026-12"), ("2026-12-a", "2026-12"), ("2026-01-old", "2026-01")):
        (hub_root / "research" / folder).mkdir()
        (hub_root / "research" / folder / "README.md").write_text(
            rbase.replace('started: "2026-11"', f'started: "{month}"'), encoding="utf-8")
    mem.apply_index(hub_root)
    assert [r.split("](")[1].split(")")[0] for r in _row_titles(hub_root, "literature")] == [
        "2021-zed-c.md", "2019-adams-a.md", "2019-adams-b.md", "2017-vaswani-attention.md"]
    assert [r.split("](")[1].split(")")[0] for r in _row_titles(hub_root, "knowledge")] == [
        "aaa-first.md", "attention-replaces-recurrence.md"]
    assert [r.split("](")[1].split("/")[0] for r in _row_titles(hub_root, "research")] == [
        "2026-12-a", "2026-12-b", "2026-11-llm-eval-methods", "2026-01-old"]


def test_index_shows_only_leaf_topics(hub_root):
    mem.apply_index(hub_root)
    row = [ln for ln in domain_block(hub_root, "knowledge", "computing").split("\n") if "attention-replaces" in ln][0]
    assert row.endswith("| llm |")


@pytest.mark.parametrize("text", [
    "x\n<!-- hub:index:start -->\nhand-written\n",
    "x\nhand-written\n<!-- hub:index:end -->\n",
    "<!-- hub:index:end -->\nhand\n<!-- hub:index:start -->\n",
    "<!-- hub:index:start -->\na\n<!-- hub:index:end -->\nhand\n<!-- hub:index:start -->\nb\n<!-- hub:index:end -->\n",
])
def test_bad_index_markers_are_refused_not_overwritten(hub_root, text):
    readme = hub_root / "knowledge" / "README.md"
    readme.write_text(text, encoding="utf-8")
    assert has(mem.check(hub_root), "knowledge/README.md", "index markers")
    assert mem.main(["--root", str(hub_root), "index"]) == 1
    assert readme.read_text(encoding="utf-8") == text


def test_unreadable_index_readme(hub_root, capsys):
    readme = hub_root / "research" / "README.md"
    readme.write_bytes(b"\xff\xfe\n")
    assert has(mem.check(hub_root), "research/README.md", "unreadable index README")
    assert mem.main(["--root", str(hub_root), "index"]) == 1
    assert "UTF-8" in capsys.readouterr().err


def test_new_with_unreadable_index_reports_instead_of_traceback(hub_root, capsys):
    (hub_root / "knowledge" / "README.md").write_bytes(b"\xff\xfe\n")
    argv = ["--root", str(hub_root), "new", "knowledge", "--slug", "x-y", "--claim", "C",
            "--topics", "llm", "--confidence", "low", "--level", "beginner", "--origin", "experience"]
    assert mem.main(argv) == 1
    assert "index was not updated" in capsys.readouterr().err


def domain_block(root, kind, domain):
    text = (root / kind / domain / "README.md").read_text(encoding="utf-8")
    return text.split(mem.INDEX_START)[1].split(mem.INDEX_END)[0]


def test_top_level_index_lists_domains_with_counts(hub_root):
    (hub_root / "knowledge" / "biology").mkdir()
    (hub_root / "knowledge" / "biology" / "cells.md").write_text(
        know(hub_root).read_text(encoding="utf-8").replace(
            "topics: [llm, deep-learning, ml, computing]", "topics: [biology]"), encoding="utf-8")
    (hub_root / "knowledge" / "physics").mkdir()  # no notes: not listed
    mem.apply_index(hub_root)
    assert block(hub_root, "knowledge").strip().split("\n") == [
        "| Domain | Notes |", "| --- | --- |",
        "| [biology](biology/README.md) | 1 |", "| [computing](computing/README.md) | 1 |"]
    assert block(hub_root, "literature").strip().split("\n")[2] == "| [computing](computing/README.md) | 1 |"


def test_domain_readme_created_with_title_and_markers(hub_root):
    (hub_root / "knowledge" / "computing" / "README.md").unlink()
    (hub_root / "literature" / "computing" / "README.md").unlink()
    changed = mem.apply_index(hub_root)
    assert "knowledge/computing/README.md" in changed and "literature/computing/README.md" in changed
    text = (hub_root / "knowledge" / "computing" / "README.md").read_text(encoding="utf-8")
    assert text.startswith("# Knowledge: computing\n")
    assert mem.INDEX_START in text and mem.INDEX_END in text
    assert mem.check(hub_root) == []
    assert mem.apply_index(hub_root) == []


def test_missing_domain_readme_is_reported(hub_root):
    mem.apply_index(hub_root)
    (hub_root / "knowledge" / "computing" / "README.md").unlink()
    assert has(mem.check(hub_root), "knowledge/computing/README.md", "run mem index")


def test_domain_index_groups_by_subtopic_with_general_last(hub_root):
    kbase = know(hub_root).read_text(encoding="utf-8")
    folder = hub_root / "knowledge" / "computing"
    for name, topics in (("a-general.md", "[computing]"), ("b-algo.md", "[algorithms, computing]"),
                         ("c-mixed.md", "[biology, llm, deep-learning, ml, computing]")):
        (folder / name).write_text(kbase.replace("topics: [llm, deep-learning, ml, computing]",
                                                 f"topics: {topics}"), encoding="utf-8")
    mem.apply_index(hub_root)
    lines = domain_block(hub_root, "knowledge", "computing").strip().split("\n")
    assert [ln for ln in lines if ln.startswith("###")] == ["### algorithms", "### llm", "### general"]
    text = "\n".join(lines)
    assert text.index("### algorithms") < text.index("b-algo.md") < text.index("### llm")
    assert text.index("### llm") < text.index("attention-replaces-recurrence.md") < text.index("c-mixed.md")
    assert text.index("c-mixed.md") < text.index("### general") < text.index("a-general.md")
    assert "| Claim | Confidence | Level | Topics |" in text
    assert "[Self-attention can replace recurrence for sequence transduction](attention-replaces-recurrence.md)" in text


def test_note_listed_under_each_most_specific_topic_in_any_order(hub_root):
    kbase = know(hub_root).read_text(encoding="utf-8")
    folder = hub_root / "knowledge" / "computing"
    old = "topics: [llm, deep-learning, ml, computing]"
    (folder / "multi.md").write_text(kbase.replace(old, "topics: [computing, algorithms, llm, ml, deep-learning]"),
                                     encoding="utf-8")
    mem.apply_index(hub_root)
    first = domain_block(hub_root, "knowledge", "computing")
    assert first.count("(multi.md)") == 2
    assert [ln for ln in first.split("\n") if ln.startswith("###")] == ["### algorithms", "### llm"]
    (folder / "multi.md").write_text(kbase.replace(old, "topics: [llm, algorithms, deep-learning, computing, ml]"),
                                     encoding="utf-8")
    mem.apply_index(hub_root)
    assert domain_block(hub_root, "knowledge", "computing") == first


def test_existing_domain_readme_is_emptied_after_last_note_removed(hub_root):
    mem.apply_index(hub_root)
    know(hub_root).unlink()
    assert has(mem.check(hub_root), "knowledge/computing/README.md", "index stale")
    assert "knowledge/computing/README.md" in mem.apply_index(hub_root)
    assert domain_block(hub_root, "knowledge", "computing") == "\n_No entries yet._\n"
    assert mem.check(hub_root) == []
    assert "computing" not in block(hub_root, "knowledge")


def test_parent_key_with_non_string_value_is_not_a_domain(hub_root):
    with (hub_root / "topics.yaml").open("a", encoding="utf-8") as f:
        f.write("odd: {parent: 5}\n")
    assert "odd" not in mem.root_topics(mem.load_topics(hub_root))
