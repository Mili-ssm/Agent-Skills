"""Memories captured from a transcript: reach, weight and standing (distinct sessions, never `observed`)."""
import datetime
import subprocess

import pytest

import mem
import records

D = datetime.date(2026, 3, 1)


def days(n):
    return D + datetime.timedelta(days=n)


def make(folder, claim="Cache keys need the schema version.", weight="medium", sources=("session a",), **kw):
    return records.write_memory(folder, "project", kind="lesson", claim=claim, body="", today=D,
                                origin="transcript", reach="general", weight=weight, sources=list(sources), **kw)


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))
    return root / ".memory"


def reload(m):
    return next(x for x in records.load_memories(m.path.parent, m.scope) if x.handle == m.handle)


def test_a_medium_transcript_memory_is_unconfirmed_and_valid_30_days(project):
    m = make(project)
    assert records.standing(m) == "unconfirmed"
    assert m.valid_until == days(30)
    text = m.path.read_text()
    assert "origin: transcript" in text and "reach: general" in text and "weight: medium" in text
    got = reload(m)
    assert (got.origin, got.reach, got.weight) == ("transcript", "general", "medium")


def test_a_light_one_is_established_at_once(project):
    m = make(project, weight="light")
    assert records.standing(m) == "established" and m.valid_until is None


def test_a_second_session_establishes_it_and_the_same_session_does_not(project):
    m = reload(make(project))
    same, added = records.add_sighting(m, "session a", days(5))
    assert not added and same == m
    m2, added = records.add_sighting(m, "session b", days(10), note="seen again")
    assert added and records.sessions(m2) == ["session a", "session b"]
    assert records.standing(m2) == "established" and m2.valid_until is None
    assert m2.body.endswith("seen again\n")
    s = reload(make(project, claim="A strong one.", weight="strong"))
    s, _ = records.add_sighting(s, "session b", days(10))
    assert records.standing(s) == "unconfirmed" and s.valid_until == days(40)
    s, _ = records.add_sighting(s, "session c", days(12))
    assert records.standing(s) == "established" and s.valid_until is None


def test_observed_alone_never_establishes(project):
    m = make(project)
    for i in range(3):
        m = records.observe(m, days(i + 1))
    assert m.observed == 4 and records.standing(m) == "unconfirmed"


def test_a_lapsed_one_is_revived_by_a_new_session(project):
    m = reload(make(project, weight="strong"))
    assert not records.is_live(m, days(45))
    m, _ = records.add_sighting(m, "session b", days(45))
    assert records.is_live(m, days(45)) and m.valid_until == days(75)


def test_other_origins_have_no_standing_and_keep_their_dates(project):
    session = records.write_memory(project, "project", kind="state", claim="Plain state.", body="", today=D)
    web = records.write_memory(project, "project", kind="finding", claim="A web finding.", body="", today=D,
                               origin="web", sources=["https://example.org/a"])
    for m in (session, web):
        assert records.standing(m) is None
        after = records.observe(m, days(1))
        after, _ = records.add_sighting(after, "session z", days(2))
        assert after.valid_until == m.valid_until


def test_unknown_values(project):
    with pytest.raises(ValueError):
        records.write_memory(project, "project", kind="lesson", claim="x y", body="", today=D, reach="everywhere")
    with pytest.raises(ValueError):
        records.write_memory(project, "project", kind="lesson", claim="x y", body="", today=D, weight="heavy")
    m = make(project)
    text = m.path.read_text().replace("reach: general", "reach: everywhere").replace("weight: medium", "weight: 7")
    m.path.write_text(text)
    got = reload(m)
    assert got.reach is None and got.weight is None and got.error is None
    assert records.standing(got) == "unconfirmed"
    got, _ = records.add_sighting(got, "session b", days(1))
    assert records.standing(got) == "established"  # no weight counts as medium


def test_a_merge_unions_the_sessions(project):
    a = make(project, claim="Retries need jitter on the client.", sources=["session a"])
    b = make(project, claim="Retries need jitter on the client side.", sources=["session b"])
    assert mem.main(["merge", f"m:{a.handle}", f"m:{b.handle}"]) == 0
    kept = reload(a)
    assert records.sessions(kept) == ["session a", "session b"]
    assert records.standing(kept) == "established" and kept.valid_until is None
    c = make(project, claim="Locks must be released in finally.", sources=["session a"])
    d = make(project, claim="Locks must be released in finally blocks.", sources=["session a"])
    assert mem.main(["merge", f"m:{c.handle}", f"m:{d.handle}"]) == 0
    assert records.standing(reload(c)) == "unconfirmed"


def line_of(capsys, handle):
    capsys.readouterr()
    assert mem.main(["memories"]) == 0
    return next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(f"m:{handle}\t"))


def test_remember_confirm_and_the_tag(project, capsys):
    claim = "Pagination cursors must be opaque."
    assert mem.main(["remember", "--kind", "lesson", f"--claim={claim}", "--origin", "transcript",
                     "--reach", "general", "--weight", "medium", "--source", "session a"]) == 0
    handle = "pagination-cursors-must-be-opaque"
    assert "from transcript, unconfirmed" in line_of(capsys, handle)
    until = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
    assert mem.main(["confirm", f"m:{handle}"]) == 0
    assert mem.main(["confirm", f"m:{handle}", "--until", until]) == 0
    assert "from transcript, unconfirmed" in line_of(capsys, handle)
    before = (project / f"{handle}.md").read_text()
    assert mem.main(["confirm", f"m:{handle}", "--source", "session a"]) == 3
    assert (project / f"{handle}.md").read_text() == before
    assert mem.main(["confirm", f"m:{handle}", "--source", "session b", "--note", "x"]) == 0
    line = line_of(capsys, handle)
    assert "from transcript" in line and "unconfirmed" not in line
    assert mem.main(["remember", "--kind", "lesson", "--claim", "A plain session memory."]) == 0
    plain = line_of(capsys, "a-plain-session-memory")
    assert "from transcript" not in plain and "unconfirmed" not in plain


def test_curate_lists_unconfirmed_transcript_memories(project, capsys):
    today = datetime.date.today()
    waiting = records.write_memory(project, "project", kind="lesson", claim="Waiting lesson about queues.", body="",
                                   today=today, origin="transcript", reach="general", weight="medium",
                                   sources=["session a"])
    records.write_memory(project, "project", kind="lesson", claim="Settled lesson about indexes.", body="",
                         today=today, origin="transcript", weight="light", sources=["session a"])
    records.write_memory(project, "project", kind="lesson", claim="Plain session lesson on mutexes.", body="",
                         today=today)
    lapsed = records.write_memory(project, "project", kind="lesson", claim="Lapsed lesson about sockets.", body="",
                                  today=today, origin="transcript", weight="medium", sources=["session a"],
                                  valid_until=today - datetime.timedelta(days=3))
    old = (today - datetime.timedelta(days=200)).isoformat()
    aged = records.write_memory(project, "project", kind="lesson", claim="Aged lesson about timers.", body="",
                                today=today, origin="transcript", weight="medium", sources=["session a"])
    records.update(aged, today, created=old)
    capsys.readouterr()
    assert mem.main(["curate", "--project"]) == 0
    out = capsys.readouterr().out
    head = "from a transcript, not confirmed yet"
    assert head in out and "it is confirmed only when another session shows it" in out
    section = out[out.index(head):]
    assert f"m:{waiting.handle}  medium, 1 session  " in section
    assert "indexes" not in out and "mutexes" not in out
    assert "expired" not in out and "not confirmed in 90 days" not in out
    assert lapsed.handle not in section  # lapsed: not live, so not waiting either
    before = records.load_memories(project, "project")
    for n in range(10):
        records.write_memory(project, "project", kind="lesson", claim=f"Extra lesson number {n} here.", body="",
                             today=today, origin="transcript", weight="strong", sources=["session a"])
    after = records.load_memories(project, "project")
    last = today - datetime.timedelta(days=20)
    assert len(after) == len(before) + 10
    assert records.curation_due(after, last, today) == records.curation_due(before, last, today)
