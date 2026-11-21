import handoff
from pathlib import Path

BLOCK = "Earlier text\nnot yet recorded: the cache key ignores the locale\nHANDOFF\ntask: add the retry\nstate: tests written\nnext: implement backoff\nverified: unit tests pass\nunverified: staging\nplan: docs/plans/p.md\n"

def test_parse_reads_the_six_fields():
    assert handoff.parse(BLOCK) == {"task": "add the retry", "state": "tests written", "next": "implement backoff",
                                    "verified": "unit tests pass", "unverified": "staging", "plan": "docs/plans/p.md"}

def test_parse_tolerates_markdown_around_the_marker_and_takes_the_last_block():
    assert handoff.parse("HANDOFF\ntask: old\n\n## **HANDOFF**:\ntask: new\n") == {"task": "new"}

def test_parse_tolerates_markdown_fields():
    text = "## Handoff\n```\n- **Task:** add the retry\n* state: tests written\n> Next: implement backoff\n**Plan**: `docs/p.md`\n```\n"
    assert handoff.parse(text) == {"task": "add the retry", "state": "tests written", "next": "implement backoff", "plan": "`docs/p.md`"}

def test_has_marker():
    assert handoff.has_marker("the Handoff follows") and not handoff.has_marker("nothing here")

def test_parse_without_a_block_is_empty():
    assert handoff.parse("a summary that mentions handoff in prose") == {}
    assert handoff.parse("") == {}

def test_unrecorded_counts_lines():
    assert handoff.unrecorded(BLOCK) == 1
    assert handoff.unrecorded("Not Yet Recorded: a\nx\n- not yet recorded: b") == 2

def test_unrecorded_counts_a_list_under_a_header():
    assert handoff.unrecorded("not yet recorded:\n- a\n- b\n* c\n\nHANDOFF\ntask: t\n- not an item\n") == 3
    assert handoff.unrecorded("nothing was not yet recorded here") == 0

def test_no_block_gives_one_line(tmp_path):
    assert handoff.mismatches({}, tmp_path) == [
        "The summary has no handoff block: state the task, its state and the next step before you continue."]

def test_a_plan_that_exists_with_open_tasks_gives_nothing(tmp_path):
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "p.md").write_text("- [x] a\n- [ ] b\n")
    assert handoff.mismatches({"plan": "`docs/p.md`", "next": "b"}, tmp_path) == []

def test_a_missing_plan_is_named(tmp_path):
    lines = handoff.mismatches({"plan": "docs/gone.md", "next": "b"}, tmp_path)
    assert len(lines) == 1 and "does not exist: docs/gone.md" in lines[0]

def test_no_plan_gives_nothing(tmp_path):
    for value in ("no plan", "None", '"no plan"', "", "the plan we agreed on"):
        assert handoff.mismatches({"plan": value, "next": "b"}, tmp_path) == []

def test_a_path_inside_prose_is_found_from_a_subdirectory_of_the_project(tmp_path):
    (tmp_path / ".git").mkdir(); (tmp_path / "docs").mkdir(); (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "p.md").write_text("- [x] a\n")
    assert handoff.mismatches({"plan": "docs/p.md (Task 3 of 5)"}, tmp_path / "src") == []
    lines = handoff.mismatches({"plan": "see docs/gone.md, Task 3"}, tmp_path / "src")
    assert len(lines) == 1 and "does not exist: docs/gone.md" in lines[0]

def test_a_plan_outside_the_project_is_never_read(tmp_path):
    assert handoff.mismatches({"plan": "../../etc/passwd", "next": "b"}, tmp_path) == []
    assert handoff.mismatches({"plan": "/etc/hostname", "next": "b"}, tmp_path) == []

def test_lines_are_short(tmp_path):
    lines = handoff.mismatches({"plan": "x" * 500 + ".md", "next": "b"}, tmp_path)
    assert all(len(line) < 150 for line in lines)
