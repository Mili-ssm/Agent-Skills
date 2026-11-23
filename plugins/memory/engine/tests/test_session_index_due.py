import datetime
from pathlib import Path

import check
import mem
import records

TODAY = datetime.date(2026, 11, 23)
HELD = "History: 1 changed note held back from the last commit: run mem check."
REREAD = "Re-read due: 1 note is past its review date: mem review."


def web_note(store: Path, name: str, added: datetime.date) -> None:
    src = store / "literature" / "computing" / "2017-vaswani-attention.md"
    text = src.read_text(encoding="utf-8").replace("added: 2026-11-07", f"added: {added}")
    text = text.replace("kind: paper", "kind: web")
    (store / "literature" / "computing" / name).write_text(text, encoding="utf-8")


def index(store: Path, today=TODAY) -> str:
    return mem.session_index(store, None, None, today)


def hold(store: Path, *paths: str) -> None:
    (store / ".git").mkdir(exist_ok=True)
    (store / ".git" / "mem-held-back").write_text("\n".join(paths) + "\n", encoding="utf-8")


def test_index_reports_held_back(hub_root):
    hold(hub_root, "knowledge/a.md")
    assert HELD in index(hub_root).splitlines()
    hold(hub_root, "knowledge/a.md", "knowledge/b.md")
    assert "History: 2 changed notes held back from the last commit: run mem check." in index(hub_root)


def test_index_reports_due_rereads(hub_root):
    web_note(hub_root, "2026-old-page.md", TODAY - datetime.timedelta(days=200))
    assert REREAD in index(hub_root).splitlines()
    web_note(hub_root, "2026-older-page.md", TODAY - datetime.timedelta(days=300))
    next_day = TODAY + datetime.timedelta(days=1)  # today's count is cached
    assert "Re-read due: 2 notes are past their review date: mem review." in index(hub_root, next_day)


def test_index_silent_when_nothing_due(hub_root):
    web_note(hub_root, "2026-fresh-page.md", TODAY - datetime.timedelta(days=10))
    text = index(hub_root)
    assert "History:" not in text and "Re-read due:" not in text


def test_index_without_git_has_no_history_line(hub_root):
    assert not (hub_root / ".git").exists()
    assert "History:" not in index(hub_root)


def test_index_with_both_lines_stays_in_the_budget(hub_root, tmp_path):
    hold(hub_root, "knowledge/a.md")
    web_note(hub_root, "2026-old-page.md", TODAY - datetime.timedelta(days=200))
    project = tmp_path / "proj" / ".memory"
    for i in range(60):  # enough rows that the limit trims them
        records.write_memory(project, "project", kind="lesson", claim=f"Project memory {i} " + "word " * 25,
                             body="", today=TODAY)
    text = mem.session_index(hub_root, project, None, TODAY, limit=50)
    assert "  m:" in text and "more: mem search" in text
    assert HELD in text and REREAD in text
    assert len(text) <= mem._INDEX_LIMIT


def test_due_counts_are_cached_per_day_and_store(hub_root, tmp_path):
    cache = tmp_path / "state"
    web_note(hub_root, "2026-old-page.md", TODAY - datetime.timedelta(days=200))
    assert check.due_counts(hub_root, TODAY, cache) == (0, 1)
    web_note(hub_root, "2026-older-page.md", TODAY - datetime.timedelta(days=300))
    assert check.due_counts(hub_root, TODAY, cache) == (0, 1)  # same day: the stored count
    assert check.due_counts(hub_root, TODAY + datetime.timedelta(days=1), cache) == (0, 2)  # the date changed
    assert check.due_counts(hub_root, TODAY + datetime.timedelta(days=1), None) == (0, 2)


def test_due_counts_agree_with_the_line_lists(hub_root):
    web_note(hub_root, "2026-old-page.md", TODAY - datetime.timedelta(days=200))
    assert check.due_counts(hub_root, TODAY) == (len(check.due_retests(hub_root, TODAY)),
                                                 len(check.due_rereads(hub_root, TODAY)))


def test_a_broken_cache_is_recomputed(hub_root, tmp_path):
    cache = tmp_path / "state"
    cache.mkdir()
    (cache / check.DUE_CACHE_NAME).write_text("not json", encoding="utf-8")
    web_note(hub_root, "2026-old-page.md", TODAY - datetime.timedelta(days=200))
    assert check.due_counts(hub_root, TODAY, cache) == (0, 1)
