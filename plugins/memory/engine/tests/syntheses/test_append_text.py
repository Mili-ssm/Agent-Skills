import datetime

import pytest
from syntheses.edit import append_section, append_text

OLD = "First sentence. [a](../knowledge/d/a.md)\n\nSources: [a](../knowledge/d/a.md)"
NEW = "Second. [b](../knowledge/d/b.md)\n\nSources: [b](../knowledge/d/b.md)"


def test_append_text_matches_append_section(tmp_path):
    path = tmp_path / "alpha.md"
    path.write_text(
        "---\ntitle: Alpha\ntopics: [x]\ncreated: '2026-01-01'\nupdated: '2026-01-01'\n---\n\n"
        f"## Summary\n\nSummary text here.\n\n## Basics\n\n{OLD}\n",
        encoding="utf-8",
    )
    append_section(path, "basics", NEW, datetime.date(2026, 2, 2))
    body = (
        path.read_text(encoding="utf-8").split("## Basics\n\n", 1)[1].strip()
    )  # Basics is the last section
    assert body == append_text(OLD, NEW)


def test_append_text_merges_sources_line():
    new = append_text(OLD, NEW)
    assert new.endswith("Sources: [a](../knowledge/d/a.md), [b](../knowledge/d/b.md)")
    assert "Second." in new


def test_append_text_refuses_empty():
    with pytest.raises(ValueError, match="empty"):
        append_text(OLD, "\n")
