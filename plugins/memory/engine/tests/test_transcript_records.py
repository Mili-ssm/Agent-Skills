"""Memories captured from a transcript: reach, weight and standing (distinct sessions, never `observed`)."""
import datetime
import subprocess
from dataclasses import replace

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
    assert not added and replace(same, log=[]) == m  # only its case is new
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
    assert mem.main(["confirm", f"m:{handle}", "--until", until]) == 2  # only a new session confirms it
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


# Fix round 1: nothing but a new session establishes a record or extends its life.

TODAY = datetime.date.today()


def remember_t(*extra, claim="Pagination cursors must be opaque.", weight="medium", source="session a", kind="lesson"):
    return mem.main(["remember", "--kind", kind, f"--claim={claim}", "--origin", "transcript", "--reach", "general",
                     "--weight", weight, "--source", source, *extra])


def state_of(project, handle):
    m = next(x for x in records.load_memories(project, "project") if x.handle == handle)
    return m.sources, m.valid_until, records.standing(m)


HANDLE = "pagination-cursors-must-be-opaque"


def test_confirm_source_must_be_a_session(project):
    assert remember_t() == 0
    before = state_of(project, HANDLE)
    text = (project / f"{HANDLE}.md").read_text()
    assert mem.main(["confirm", f"m:{HANDLE}", "--source", "https://example.org/x"]) == 2
    assert state_of(project, HANDLE) == before and (project / f"{HANDLE}.md").read_text() == text
    m = reload(next(x for x in records.load_memories(project, "project")))
    with pytest.raises(ValueError):
        records.add_sighting(m, "https://example.org/x", days(1))


def test_session_spelling_counts_once(project):
    m = reload(make(project, sources=["session a"]))
    assert records.session_key("  Session   A ") == "session a"
    assert records.session_key("session ") is None and records.session_key("https://x") is None
    same, added = records.add_sighting(m, "session  a", days(5))
    assert not added and replace(same, log=[]) == m  # only its case is new
    same, added = records.add_sighting(m, "Session A", days(5))
    assert not added
    m2, added = records.add_sighting(m, "Session   B", days(5))
    assert added and m2.sources == ["session a", "session b"]
    w = make(project, claim="Written twice with odd spelling.", sources=["Session  A", "session a", "https://x"])
    assert w.sources == ["session a", "https://x"] and records.sessions(w) == ["session a"]
    assert records.standing(w) == "unconfirmed"


def test_confirm_with_a_respelled_session_changes_nothing(project):
    assert remember_t() == 0
    before = state_of(project, HANDLE)
    assert mem.main(["confirm", f"m:{HANDLE}", "--source", "SESSION  A"]) == 3
    assert state_of(project, HANDLE) == before


def test_until_does_not_extend_an_unconfirmed_one(project, capsys):
    assert remember_t() == 0
    before = state_of(project, HANDLE)
    capsys.readouterr()
    assert mem.main(["confirm", f"m:{HANDLE}", "--until", "2099-01-01"]) == 2
    err = capsys.readouterr().err
    assert len([ln for ln in err.splitlines() if ln.strip()]) == 1 and "another session" in err
    assert state_of(project, HANDLE) == before
    # an established one, and any other memory, still take --until
    assert remember_t(claim="Settled by a light weight.", weight="light") == 0
    assert mem.main(["confirm", "m:settled-by-a-light-weight", "--until", "2099-01-01"]) == 0
    assert state_of(project, "settled-by-a-light-weight")[1] == datetime.date(2099, 1, 1)
    assert mem.main(["remember", "--kind", "lesson", "--claim", "A plain session memory."]) == 0
    assert mem.main(["confirm", "m:a-plain-session-memory", "--until", "2099-01-01"]) == 0


def test_established_state_has_no_end_date_unless_asked(project):
    assert remember_t(claim="State shown by a session.", kind="state", weight="light") == 0
    sources, until, standing = state_of(project, "state-shown-by-a-session")
    assert (sources, until, standing) == (["session a"], None, "established")
    assert remember_t(claim="State shown by one session only.", kind="state", weight="medium") == 0
    assert state_of(project, "state-shown-by-one-session-only")[1] == TODAY + datetime.timedelta(days=30)
    assert remember_t("--valid-until", "2099-02-02", claim="State with its own end.", kind="state",
                      weight="light") == 0
    assert state_of(project, "state-with-its-own-end")[1] == datetime.date(2099, 2, 2)


def test_a_merge_keeps_the_session_of_a_transcript_record(project):
    keep = records.write_memory(project, "project", kind="lesson", claim="Retries need jitter on the client.",
                                body="", today=D, sources=["session a"])
    drop = make(project, claim="Retries need jitter on the client side.", sources=["session b"])
    assert mem.main(["merge", f"m:{keep.handle}", f"m:{drop.handle}"]) == 0
    kept = reload(keep)
    assert kept.sources == ["session a", "session b"] and kept.origin is None
    assert kept.valid_until is None and records.standing(kept) is None
    # kept transcript record: a new session from the dropped one follows the validity rule
    k2 = make(project, claim="Locks must be released in finally.", weight="strong", sources=["session a"])
    d2 = make(project, claim="Locks must be released in finally blocks.", weight="strong", sources=["session b"])
    assert mem.main(["merge", f"m:{k2.handle}", f"m:{d2.handle}"]) == 0
    kept2 = reload(k2)
    assert kept2.sources == ["session a", "session b"] and records.standing(kept2) == "unconfirmed"
    assert kept2.valid_until == TODAY + datetime.timedelta(days=30)


def test_remember_of_an_identical_claim_adds_the_session(project, capsys):
    assert remember_t() == 0
    capsys.readouterr()
    assert remember_t(source="session b") == 3
    cap = capsys.readouterr()
    assert cap.out == f"m:{HANDLE}\tsighting\n" and "added" in cap.err
    sources, until, standing = state_of(project, HANDLE)
    assert (sources, until, standing) == (["session a", "session b"], None, "established")
    assert len(list(project.glob("*.md"))) == 1
    assert remember_t(source="session  B") == 3
    cap = capsys.readouterr()
    assert cap.out == f"m:{HANDLE}\talready counted\n" and "already counted" in cap.err
    assert state_of(project, HANDLE)[0] == ["session a", "session b"]
    # any other case exits 3 as before: nothing on stdout, nothing added
    assert mem.main(["remember", "--kind", "lesson", f"--claim=Pagination cursors must be opaque."]) == 3
    assert capsys.readouterr().out == ""
    assert state_of(project, HANDLE)[0] == ["session a", "session b"]


def test_a_repeated_session_writes_no_undo_entry(project):
    assert remember_t() == 0
    names = lambda: sorted(p.name for p in project.parent.rglob("*") if "log" in p.name.lower() and p.is_file())
    before = names(), [p.read_bytes() for p in project.parent.rglob("*") if "log" in p.name.lower() and p.is_file()]
    assert mem.main(["confirm", f"m:{HANDLE}", "--source", "session a"]) == 3
    after = names(), [p.read_bytes() for p in project.parent.rglob("*") if "log" in p.name.lower() and p.is_file()]
    assert after == before


# Fix round 2.

def test_an_explicit_end_date_needs_an_established_record(project, capsys):
    capsys.readouterr()
    assert remember_t("--valid-until", "2099-01-01") == 2
    err = capsys.readouterr().err
    assert len([ln for ln in err.splitlines() if ln.strip()]) == 1 and "30 days" in err
    assert not list(project.glob("*.md"))
    assert remember_t("--valid-until", "2099-01-01", claim="Settled by a light weight.", weight="light") == 0
    assert state_of(project, "settled-by-a-light-weight")[1] == datetime.date(2099, 1, 1)
    assert mem.main(["remember", "--kind", "lesson", "--claim", "Not from a transcript.", "--valid-until",
                     "2099-01-01"]) == 0


def test_a_new_session_revives_a_lapsed_record_and_writes_no_second_file(project):
    old = make(project, weight="strong")
    path = old.path
    raw = path.read_text().replace(f"valid_until: {days(30).isoformat()}", "valid_until: 2020-01-01")
    path.write_text(raw)
    assert not records.is_live(reload(old), TODAY)
    assert remember_t(claim=old.claim, source="session b") == 3
    assert len(list(project.glob("*.md"))) == 1
    got = reload(old)
    assert records.sessions(got) == ["session a", "session b"] and records.is_live(got, TODAY)
    assert got.valid_until == TODAY + datetime.timedelta(days=30)


def test_refuted_and_forgotten_records_are_not_revived(project):
    for status, claim in (("refuted", "Refuted lessons stay refuted."), ("forgotten", "Forgotten lessons stay gone.")):
        old = make(project, claim=claim, weight="strong")
        old.path.write_text(old.path.read_text().replace("status: active", f"status: {status}"))
        assert remember_t(claim=claim, source="session b") == 0
        assert len(list(project.glob(f"{old.handle}*.md"))) == 2
        assert records.sessions(reload(old)) == ["session a"]


def test_confirm_source_is_free_for_a_memory_that_is_not_from_a_transcript(project, capsys):
    assert mem.main(["remember", "--kind", "lesson", "--claim", "A plain session memory."]) == 0
    h = "a-plain-session-memory"
    assert mem.main(["confirm", f"m:{h}", "--source", "https://example.org/x", "--note", "seen there"]) == 0
    m = next(x for x in records.load_memories(project, "project") if x.handle == h)
    assert m.sources == ["https://example.org/x"] and m.observed == 2
    assert mem.main(["confirm", f"m:{h}", "--source", "https://example.org/y"]) == 0   # another source still counts
    m = next(x for x in records.load_memories(project, "project") if x.handle == h)
    assert m.sources == ["https://example.org/x", "https://example.org/y"] and m.observed == 3


def test_a_session_id_has_a_length_cap():
    assert records.session_key("session " + "a" * 200) is not None
    assert records.session_key("session " + "a" * 201) is None
    assert records.session_key("session " + "a" * 201 + "   ") is None


def test_a_source_counts_once_on_any_record(project, capsys):
    plain = records.write_memory(project, "project", kind="lesson", claim="A plain lesson about retries.", body="", today=D)
    web = records.write_memory(project, "project", kind="finding", claim="A web finding about retries.", body="",
                               today=D, origin="web", sources=["https://example.org/a"])
    for m, source in ((plain, "session abc123"), (web, "https://example.org/a"), (web, "  Session  ABC123 ")):
        assert mem.main(["confirm", f"m:{m.handle}", f"--source={source}", "--note=x"]) in (0, 3)
        capsys.readouterr()
        before = (m.path.read_text(), reload(m).observed, reload(m).sources)
        again = mem.main(["confirm", f"m:{m.handle}", f"--source={source}", "--note=x"])
        out = capsys.readouterr().out
        assert again == 3 and "already a source" in out
        assert (m.path.read_text(), reload(m).observed, reload(m).sources) == before


def test_a_retired_record_gets_no_sighting(project, capsys):
    for verb in ("refute", "forget"):
        m = records.write_memory(project, "project", kind="lesson", claim=f"A lesson to {verb} about caches.", body="",
                                 today=D)
        assert mem.main([verb, f"m:{m.handle}"]) == 0
        capsys.readouterr()
        before = (m.path.read_text(), reload(m).observed)
        assert mem.main(["confirm", f"m:{m.handle}", "--source=session z"]) == 2
        assert (m.path.read_text(), reload(m).observed) == before
        assert reload(m).status in capsys.readouterr().err


def test_a_repeated_source_still_lets_until_through_on_an_ordinary_memory(project, capsys):
    assert mem.main(["remember", "--kind", "lesson", "--claim", "An ordinary memory with a date."]) == 0
    h = "an-ordinary-memory-with-a-date"
    assert mem.main(["confirm", f"m:{h}", "--source", "https://example.org/x"]) == 0
    assert mem.main(["confirm", f"m:{h}", "--source", "https://example.org/x", "--until", "2030-01-01"]) == 3
    m = next(x for x in records.load_memories(project, "project") if x.handle == h)
    assert m.valid_until == datetime.date(2030, 1, 1) and m.observed == 2 and m.sources == ["https://example.org/x"]
