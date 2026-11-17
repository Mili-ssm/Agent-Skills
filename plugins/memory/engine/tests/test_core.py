import pytest
import yaml

import mem
from test_check import edit, know


def test_loader_keeps_dates_and_booleans_as_strings():
    assert mem.load_yaml("d: 2026-11-07\nt: [on, no]") == {"d": "2026-11-07", "t": ["on", "no"]}


def test_frontmatter_crlf_and_bom():
    data, body, line = mem.split_frontmatter("\ufeff---\r\ntitle: x\r\n---\r\n## A\r\n")
    assert data == {"title": "x"} and body.startswith("## A") and line == 4


def test_frontmatter_missing_raises():
    with pytest.raises(mem.FrontmatterError):
        mem.split_frontmatter("# no frontmatter\n")


def test_discover_notes_types(hub_root):
    notes = {n.rel: n.type for n in mem.discover_notes(hub_root)}
    assert notes == {
        "knowledge/computing/attention-replaces-recurrence.md": "knowledge",
        "literature/computing/2017-vaswani-attention.md": "literature",
        "research/2026-11-llm-eval-methods/README.md": "research",
    }


def test_topic_hierarchy(hub_root):
    t = mem.load_topics(hub_root)
    assert mem.ancestors(t, "llm") == ["deep-learning", "ml", "computing"]
    assert mem.descendants(t, "ml") == {"ml", "deep-learning", "llm"}
    assert mem.leaf_topics(t, ["llm", "deep-learning", "ml", "computing"]) == ["llm"]


def test_slugify():
    assert mem.slugify("García") == "garcia" and mem.slugify("van der Waals") == "vanderwaals"


def test_non_string_parent_does_not_crash(hub_root):
    topics = {"a": {"parent": ["x"]}, "b": {"parent": "a"}, "c": {"parent": "nope"}}
    assert mem.ancestors(topics, "a") == []
    assert mem.ancestors(topics, "b") == ["a"]
    assert mem.ancestors(topics, "c") == []
    assert mem.descendants(topics, "a") == {"a", "b"}


def test_invalid_utf8_is_reported_not_raised(hub_root):
    (hub_root / "literature" / "computing" / "2018-bad-utf8.md").write_bytes(b"---\n\xff\xfe\n---\n")
    (hub_root / "topics.yaml").write_bytes(b"\xff\xfe")
    notes = {n.rel: n for n in mem.discover_notes(hub_root)}
    assert "UTF-8" in notes["literature/computing/2018-bad-utf8.md"].error
    with pytest.raises(mem.FrontmatterError, match="UTF-8"):
        mem.load_topics(hub_root)


def test_load_topics_strips_bom(hub_root):
    path = hub_root / "topics.yaml"
    path.write_text("\ufeff" + path.read_text(encoding="utf-8"), encoding="utf-8")
    assert "llm" in mem.load_topics(hub_root)


def test_duplicate_keys_rejected():
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        mem.load_yaml("a: 1\na: 2\n")


def test_duplicate_key_in_note_and_topics_reported(hub_root):
    edit(know(hub_root), "confidence: medium\n", "confidence: medium\nconfidence: low\n")
    assert any("duplicate key" in p.message and p.path.startswith("knowledge/") for p in mem.check(hub_root))
    (hub_root / "topics.yaml").write_text("a: {}\na: {}\n", encoding="utf-8")
    assert any(p.path == "topics.yaml" and p.line == 2 and "duplicate key" in p.message
               for p in mem.check(hub_root))


def test_yaml_error_is_one_line_with_file_line(hub_root):
    edit(know(hub_root), "origin:", "bad: [unclosed\norigin:")
    problem = next(p for p in mem.check(hub_root) if "invalid frontmatter" in p.message)
    assert "\n" not in str(problem) and problem.line > 1
