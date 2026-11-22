import datetime
import json
from pathlib import Path

import pytest

import mem
import records

TODAY = datetime.date.today()
CLAIM = "Zebra caches expire silently under load."
KEYS = ("0123456789ab", "ba9876543210")


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = type("W", (), {})()
    w.gmem = tmp_path / "gmem"
    w.data = tmp_path / "data"
    w.pa, w.pb = tmp_path / "alpha-p-a", tmp_path / "beta-p-b"
    for p in (w.pa, w.pb):
        records.project_dir(p).mkdir(parents=True)
    w.data.mkdir(parents=True)
    (w.data / "projects.json").write_text(json.dumps(
        {p.name: {"path": str(p), "seen": TODAY.isoformat()} for p in (w.pa, w.pb)}))
    monkeypatch.setenv("MEM_DATA", str(w.data))
    monkeypatch.setenv("MEM_MEMORIES", str(w.gmem))
    monkeypatch.setenv("MEM_COUNT_TEMP_PROJECTS", "1")
    monkeypatch.setenv("MEM_PROJECT", str(w.pa))
    return w


def remember(*sources, claim=CLAIM):
    args = ["remember", "--global", "--origin", "transcript", "--reach", "general", "--weight", "light",
            "--kind", "lesson", "--claim", claim]
    for s in sources:
        args += ["--source", s]
    return mem.main(args)


def released(capsys, claim=CLAIM):
    assert remember(f"session a project {KEYS[0]}", f"session b project {KEYS[1]}", claim=claim) == 0
    capsys.readouterr()
    found = [m for m in records.load_memories(Path(mem.os.environ["MEM_MEMORIES"]), "global") if m.claim == claim]
    assert found[0].triage == "pending"
    return found[0]


def link(world, handle, project, claim="Zebra caches expire quietly when loaded."):
    m = records.write_memory(records.project_dir(project), "project", kind="lesson", claim=claim, body="b\n",
                             today=TODAY, sources=["session a"], origin="transcript", reach="general")
    records.update(m, TODAY, promote="done", general=handle)
    return m.handle


def project_record(project, handle):
    return {m.handle: m for m in records.load_memories(records.project_dir(project), "project")}[handle]


def test_curate_global_lists_the_record_awaiting_triage(world, capsys):
    m = released(capsys)
    assert mem.main(["curate", "--global"]) == 0
    out = capsys.readouterr().out
    assert ("general lesson, out of quarantine, awaiting triage (decide: mem triage accept <h>, mem triage reject <h>, "
            "or reword it with mem edit and then accept)") in out
    assert f"m:{m.handle}  2 sessions, 2 projects  {CLAIM}" in out
    assert "from a transcript, not confirmed yet" not in out
    assert "in quarantine" not in out


def test_curate_global_counts_the_quarantine_and_does_not_list_it_as_unconfirmed(world, capsys):
    assert remember("session a", claim="Walrus queues drain slowly during deploys.") == 0
    capsys.readouterr()
    assert mem.main(["curate", "--global"]) == 0
    out = capsys.readouterr().out
    assert ("in quarantine: 1 general lessons, not shown to a reader until corroborated "
            "(mem memories --global --quarantine)") in out
    assert "from a transcript, not confirmed yet" not in out
    assert "awaiting triage" not in out


def test_accept_clears_the_field_and_the_start_line(world, capsys):
    m = released(capsys)
    line = "Triage: 1 general lessons await triage (mem curate --global)."
    assert line in mem.session_index(None, None, world.gmem, TODAY)
    assert mem.main(["triage", "accept", m.handle]) == 0
    capsys.readouterr()
    after = records.load_memories(world.gmem, "global")[0]
    assert after.triage is None and after.status == "active"
    assert "Triage:" not in mem.session_index(None, None, world.gmem, TODAY)
    assert (world.gmem / records.CURATION_LOG).exists()


def test_reject_retires_the_record_and_marks_linked_project_records(world, capsys):
    m = released(capsys)
    on_a = link(world, m.handle, world.pa)
    on_b = link(world, m.handle, world.pb, "Zebra caches lapse quietly when loaded.")
    other = link(world, "ffffffffffff", world.pb, "Walrus queues drain slowly during deploys.")
    assert mem.main(["triage", "reject", m.handle]) == 0
    capsys.readouterr()
    after = records.load_memories(world.gmem, "global")[0]
    assert after.status == "forgotten" and after.triage is None
    for project, handle in ((world.pa, on_a), (world.pb, on_b)):
        linked = project_record(project, handle)
        assert linked.promote == "no" and not linked.general
    untouched = project_record(world.pb, other)
    assert untouched.promote == "done" and untouched.general == "ffffffffffff"


@pytest.mark.parametrize("verb", ["accept", "reject"])
def test_a_record_that_awaits_no_triage_exits_2(world, capsys, verb):
    assert remember("session a") == 0
    capsys.readouterr()
    handle = records.load_memories(world.gmem, "global")[0].handle
    assert mem.main(["triage", verb, handle]) == 2
    assert records.load_memories(world.gmem, "global")[0].status == "active"


def test_session_start_shows_the_failure_of_the_pass_until_ack(world, capsys):
    cdir = world.data / "corroborate"
    cdir.mkdir()
    (cdir / "status.json").write_text(json.dumps(
        {"state": "failed", "failure": {"at": 1.0, "reason": "the model answered nothing", "log": ""}}))
    assert mem.main(["session-index"]) == 0
    assert ("memory: the last corroboration pass failed (the model answered nothing): see mem-corroborate status, "
            "then mem-corroborate ack.") in capsys.readouterr().out
    (cdir / "status.json").write_text(json.dumps({"state": "idle"}))
    assert mem.main(["session-index"]) == 0
    assert "corroboration pass failed" not in capsys.readouterr().out
