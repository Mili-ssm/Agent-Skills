import datetime

import pytest

import records

D1, D2 = datetime.date(2026, 11, 20), datetime.date(2026, 11, 25)
KEY = "0123456789ab"


def transcript(tmp_path, session="session s1", project=KEY, today=D1):
    return records.write_memory(tmp_path / ".memory", "project", kind="lesson", claim="Run the linter before the tests.",
                                body="", today=today, origin="transcript",
                                sources=[records.sighting_entry(session, project)])


def reload(m):
    [loaded] = records.load_memories(m.path.parent, m.scope)
    return loaded


def test_case_round_trip():
    entry = records.case_entry(D1, "session abc", "failed")
    assert entry == "2026-11-20 session abc failed"
    assert records.case(entry) == records.Case(D1, "session abc", "failed")


def test_what_is_not_a_case():
    for text in ("2026-13-40 session abc failed", "2026-11-20 session abc", "2026-11-20 session abc broken",
                 "session abc failed", "2026-11-20 a book failed", ""):
        assert records.case(text) is None


def test_add_sighting_records_the_case_of_a_new_session(tmp_path, monkeypatch):
    m = transcript(tmp_path)
    writes = []
    real = records.update
    monkeypatch.setattr(records, "update", lambda *a, **k: writes.append(1) or real(*a, **k))
    got, new = records.add_sighting(m, f"session s2 project {KEY}", D2, outcome="failed")
    assert new and len(writes) == 1
    assert got.sources == [f"session s1 project {KEY}", f"session s2 project {KEY}"]
    assert got.log == ["2026-11-25 session s2 failed"]


def test_the_day_of_the_session_wins_over_today(tmp_path):
    m = transcript(tmp_path)
    got, _ = records.add_sighting(m, "session s2", D2, outcome="worked", on=D1)
    assert got.log == ["2026-11-20 session s2 worked"] and got.last_observed == D2


def test_a_counted_session_still_gets_its_case(tmp_path):
    m = transcript(tmp_path)
    m, _ = records.add_sighting(m, "session s2", D1, outcome="failed")
    before = (m.observed, list(m.sources))
    got, new = records.add_sighting(m, "session s2", D2, outcome="worked")
    assert not new and (got.observed, got.sources) == before
    assert got.log == ["2026-11-20 session s2 failed", "2026-11-25 session s2 worked"]


def test_one_session_gives_one_case_per_outcome(tmp_path):
    m = transcript(tmp_path)
    m, _ = records.add_sighting(m, "session s2", D1, outcome="failed")
    m, _ = records.add_sighting(m, "session s2", D2, outcome="failed")
    assert m.log == ["2026-11-20 session s2 failed"]
    m, _ = records.add_sighting(m, "session s2", D2, outcome="seen")
    assert m.log == ["2026-11-20 session s2 failed"]
    m, _ = records.add_sighting(m, "session s3", D1, outcome="seen")
    m, _ = records.add_sighting(m, "session s3", D2, outcome="failed")
    assert m.log[1:] == ["2026-11-20 session s3 seen", "2026-11-25 session s3 failed"]


def test_add_case_refuses_what_is_not_a_case(tmp_path):
    m = transcript(tmp_path)
    with pytest.raises(ValueError):
        records.add_case(m, "a book", D1, "failed", D2)
    with pytest.raises(ValueError):
        records.add_case(m, "session s1", D1, "broken", D2)


def test_cases_are_sorted_by_date_keeping_file_order(tmp_path):
    m = transcript(tmp_path)
    for s, d in (("s2", D2), ("s3", D1), ("s4", D1)):
        m, _ = records.add_case(m, s if s.startswith("session") else f"session {s}", d, "failed", D2)
    assert [c.session for c in records.cases(m)] == ["session s3", "session s4", "session s2"]


def test_a_new_transcript_record_starts_its_log(tmp_path):
    m = records.write_memory(tmp_path / ".memory", "project", kind="lesson", claim="One.", body="", today=D1,
                             origin="transcript", sources=[f"session s1 project {KEY}"], outcome="failed")
    assert m.log == ["2026-11-20 session s1 failed"] and reload(m).log == m.log
    n = records.write_memory(tmp_path / ".memory", "project", kind="lesson", claim="Two.", body="", today=D1,
                             origin="transcript", sources=[f"session s1 project {KEY}"])
    assert "log" not in n.path.read_text()


def test_a_wrong_log_value_reads_as_absent(tmp_path):
    for i, value in enumerate(("yes", '["2026-11-20 session a failed", "nonsense", 7]')):
        (tmp_path / f"m{i}.md").write_text(f"---\nkind: lesson\nclaim: Raw {i}.\nlog: {value}\n---\nbody\n")
    first, second = records.load_memories(tmp_path, "project")
    assert first.error is None and first.log == []
    assert second.error is None and second.log == ["2026-11-20 session a failed"]


def test_an_old_file_is_not_rewritten_by_a_read(tmp_path):
    m = transcript(tmp_path)
    text = m.path.read_text()
    assert "log" not in text
    [loaded] = records.load_memories(m.path.parent, "project")
    assert m.path.read_text() == text and records.cases(loaded) == []


def test_sources_and_standing_ignore_the_log(tmp_path):
    m = transcript(tmp_path)
    a = records.replace(m, log=[])
    b = records.replace(m, log=["2026-11-20 session s1 failed"])
    assert (records.sessions(a), records.projects(a), records.standing(a)) == \
        (records.sessions(b), records.projects(b), records.standing(b))
