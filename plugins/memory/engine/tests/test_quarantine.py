import datetime
import io

import pytest

import mem
import records
import settle
import settle_state

TODAY = datetime.date.today()
K1, K2 = "0123456789ab", "ba9876543210"
QUARANTINED = "Zebra caches expire silently under load."
ESTABLISHED = "Walrus queues drain slowly during deploys."


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


def write_quarantined(claim=QUARANTINED, *extra):
    return mem.main(["remember", "--global", "--origin", "transcript", "--reach", "general", "--weight", "light",
                     "--kind", "lesson", "--claim", claim, "--source", "session a", *extra])


def write_established(claim=ESTABLISHED):
    return mem.main(["remember", "--global", "--kind", "lesson", "--claim", claim])


@pytest.fixture
def both(gfolder, capsys):
    assert write_established() == 0
    assert write_quarantined() == 0
    capsys.readouterr()
    loaded = {m.claim: m for m in records.load_memories(gfolder, "global")}
    assert records.quarantined(loaded[QUARANTINED]) and not records.quarantined(loaded[ESTABLISHED])
    return loaded[QUARANTINED], loaded[ESTABLISHED]


def test_search_does_not_show_a_quarantined_record(both, capsys):
    q, e = both
    assert mem.main(["search", "--scope", "memories", "zebra caches expire"]) == 0
    out = capsys.readouterr()
    assert q.handle not in out.out
    assert mem.main(["search", "--scope", "memories", "walrus queues drain"]) == 0
    assert e.handle in capsys.readouterr().out


def test_session_index_counts_only_readable(both, gfolder):
    assert "Global memories: 1." in mem.session_index(None, None, gfolder, TODAY)


def test_memories_listing_hides_it_and_the_flag_shows_it(both, capsys):
    q, e = both
    assert mem.main(["memories", "--global"]) == 0
    out = capsys.readouterr().out
    assert e.handle in out and q.handle not in out
    assert mem.main(["memories", "--global", "--quarantine"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and q.handle in lines[0] and "quarantine" in lines[0]


def test_remember_hint_does_not_show_it(both, capsys):
    q, e = both
    assert mem.main(["remember", "--global", "--kind", "lesson", "--claim", "Zebra caches expire quietly under heavy load."]) == 0
    err = capsys.readouterr().err
    assert q.handle not in err


def test_identical_claim_is_still_refused(both, capsys):
    assert mem.main(["remember", "--global", "--kind", "lesson", "--claim", QUARANTINED]) == 3


def test_handle_still_resolves(both, capsys):
    q, _ = both
    assert mem.main(["show", f"m:{q.handle}"]) == 0
    assert QUARANTINED in capsys.readouterr().out
    assert mem.main(["confirm", "--global", q.handle, "--by-owner"]) == 0
    assert mem.main(["forget", "--global", q.handle]) == 0


def test_project_scope_is_unchanged(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("MEM_PROJECT", str(root))
    assert mem.main(["remember", "--origin", "transcript", "--kind", "lesson", "--claim", QUARANTINED,
                     "--source", "session a"]) == 0
    capsys.readouterr()
    assert mem.main(["memories"]) == 0
    assert "unconfirmed" in capsys.readouterr().out
    assert "This project: 1 memories." in mem.session_index(None, records.project_dir(root), None, TODAY)


def test_settle_leaves_quarantine_alone(gfolder, monkeypatch):
    started = []
    monkeypatch.setattr(settle_state, "maybe_start", lambda *a, **k: started.append(a) or False)
    assert write_quarantined() == 0
    assert started == []
    assert write_established() == 0
    assert len(started) == 1
    assert write_established(ESTABLISHED.replace("Walrus", "Walruses")) == 0
    loaded = records.load_memories(gfolder, "global")
    state = settle.load_state(gfolder)
    state["judged"] = []
    found = settle.pending(loaded, state, TODAY, tokenize=mem.tokenize)
    held = {m.handle for m in loaded if records.quarantined(m)}
    assert held and found
    assert all(not ({p["a"], p["b"]} & held) for p in found)


def test_signal_does_not_name_a_quarantined_record(gfolder, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"Please look at this: {QUARANTINED}"))
    assert write_quarantined() == 0
    q = records.load_memories(gfolder, "global")[0]
    capsys.readouterr()
    assert mem.main(["signal"]) == 0
    out = capsys.readouterr().out
    assert q.handle not in out and out.strip() == ""


def test_signal_names_an_established_twin(gfolder, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"Please look at this: {QUARANTINED}"))
    assert write_established(QUARANTINED) == 0
    e = records.load_memories(gfolder, "global")[0]
    capsys.readouterr()
    assert mem.main(["signal"]) == 0
    assert e.handle in capsys.readouterr().out


def test_settle_state_ignores_quarantine_until_release(gfolder, capsys):
    assert write_established() == 0
    state = settle.load_state(gfolder)  # first use: the established record is judged
    assert write_quarantined() == 0
    assert write_established("Otter pools freeze quickly in winter.") == 0
    q = next(m for m in records.load_memories(gfolder, "global") if m.claim == QUARANTINED)
    assert settle.unjudged_count(gfolder, state, TODAY) == 1  # only the otter record
    assert mem.main(["settle", "pending"]) == 0
    assert q.handle not in settle.load_state(gfolder)["judged"]
    assert mem.main(["confirm", "--global", q.handle, "--source", f"session a project {K1}"]) == 0
    assert mem.main(["confirm", "--global", q.handle, "--source", f"session b project {K2}"]) == 0
    capsys.readouterr()
    q = next(m for m in records.load_memories(gfolder, "global") if m.claim == QUARANTINED)
    assert not records.quarantined(q)
    assert settle.unjudged_count(gfolder, settle.load_state(gfolder), TODAY) == 1


def test_quarantine_listing_hides_a_forgotten_record(both, capsys):
    q, _ = both
    assert mem.main(["forget", "--global", q.handle]) == 0
    capsys.readouterr()
    assert mem.main(["memories", "--global", "--quarantine"]) == 0
    assert capsys.readouterr().out.strip() == ""
    assert mem.main(["memories", "--global", "--quarantine", "--dead"]) == 0
    assert q.handle in capsys.readouterr().out
