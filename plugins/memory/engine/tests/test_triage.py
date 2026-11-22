import datetime
import json
import os
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
            "or reword it with mem memory edit <h> --global and then accept)") in out
    assert f"m:{m.handle}  2 sessions, 2 projects  {CLAIM}" in out
    assert "from a transcript, not confirmed yet" not in out
    assert "in quarantine" not in out


def test_curate_global_counts_the_quarantine_and_does_not_list_it_as_unconfirmed(world, capsys):
    assert remember("session a", claim="Walrus queues drain slowly during deploys.") == 0
    capsys.readouterr()
    assert mem.main(["curate", "--global"]) == 0
    out = capsys.readouterr().out
    assert ("in quarantine: 1 general lesson, not shown to a reader until corroborated "
            "(mem memories --global --quarantine)") in out
    assert "from a transcript, not confirmed yet" not in out
    assert "awaiting triage" not in out


def test_accept_clears_the_field_and_the_start_line(world, capsys):
    m = released(capsys)
    line = "Triage: 1 general lesson awaits triage (mem curate --global)."
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
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"m:{m.handle}\trejected"
    assert out[1] == "unlinked 2 project records"
    assert sorted(out[2:]) == sorted(f"m:{h}\tunlinked" for h in (on_a, on_b))
    assert str(world.pa) not in "\n".join(out) and world.pb.name not in "\n".join(out)
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


def reject_state(world, m, linked):
    """What a refused or failed reject must leave alone: the global record and the linked project records."""
    g = records.load_memories(world.gmem, "global")[0]
    return g.status, g.triage, [(project_record(p, h).promote, project_record(p, h).general) for p, h in linked]


def test_reject_with_no_registry_file_retires_the_record(world, capsys):
    m = released(capsys)
    (world.data / "projects.json").unlink()
    assert mem.main(["triage", "reject", m.handle]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [f"m:{m.handle}\trejected", "unlinked 0 project records"]
    assert records.load_memories(world.gmem, "global")[0].status == "forgotten"


def test_reject_with_no_linked_record_says_zero(world, capsys):
    m = released(capsys)
    assert mem.main(["triage", "reject", m.handle]) == 0
    assert capsys.readouterr().out.splitlines() == [f"m:{m.handle}\trejected", "unlinked 0 project records"]


def test_reject_refuses_before_any_change_when_a_linked_file_cannot_be_parsed(world, capsys):
    m = released(capsys)
    ok = link(world, m.handle, world.pa)
    bad = records.project_dir(world.pb) / "broken.md"
    bad.write_text(f"---\nkind: nonsense\nclaim: x\ngeneral: {m.handle}\n---\nb\n", encoding="utf-8")
    assert mem.main(["triage", "reject", m.handle]) == 2
    err = capsys.readouterr().err
    assert "no change was made" in err and "broken" in err
    assert reject_state(world, m, [(world.pa, ok)]) == ("active", "pending", [("done", m.handle)])


def test_reject_ignores_a_broken_file_that_does_not_name_the_handle(world, capsys):
    m = released(capsys)
    (records.project_dir(world.pb) / "broken.md").write_text("---\nkind: nonsense\n---\nb\n", encoding="utf-8")
    assert mem.main(["triage", "reject", m.handle]) == 0


def test_reject_refuses_on_a_corrupt_registry_without_changing_anything(world, capsys):
    m = released(capsys)
    (world.data / "projects.json").write_text("{not json", encoding="utf-8")
    assert mem.main(["triage", "reject", m.handle]) == 2
    assert "no change was made" in capsys.readouterr().err
    assert records.load_memories(world.gmem, "global")[0].status == "active"


def test_reject_failing_on_a_project_record_says_what_changed_and_keeps_the_global_record(world, capsys, monkeypatch):
    m = released(capsys)
    on_a = link(world, m.handle, world.pa)
    on_b = link(world, m.handle, world.pb, "Zebra caches lapse quietly when loaded.")
    real = records.update
    calls = []

    def update(memory, today, **changes):
        if "promote" in changes:
            calls.append(memory.handle)
            if len(calls) == 2:
                raise OSError("disk full")
        return real(memory, today, **changes)
    monkeypatch.setattr(records, "update", update)
    assert mem.main(["triage", "reject", m.handle]) == 2
    err = capsys.readouterr().err
    assert "disk full" in err and f"m:{calls[0]}" in err and "global record is still active" in err
    monkeypatch.undo()
    assert records.load_memories(world.gmem, "global")[0].status == "active"
    assert {project_record(p, h).promote for p, h in ((world.pa, on_a), (world.pb, on_b))} == {"no", "done"}


def test_reject_failing_to_retire_the_global_record_says_the_projects_were_unlinked(world, capsys, monkeypatch):
    m = released(capsys)
    on_a = link(world, m.handle, world.pa)
    real = records.update

    def update(memory, today, **changes):
        if changes.get("status") == "forgotten":
            raise OSError("read-only")
        return real(memory, today, **changes)
    monkeypatch.setattr(records, "update", update)
    assert mem.main(["triage", "reject", m.handle]) == 2
    err = capsys.readouterr().err
    assert "read-only" in err and f"m:{on_a}" in err and "unlinked" in err
    monkeypatch.undo()
    assert project_record(world.pa, on_a).promote == "no"
    assert records.load_memories(world.gmem, "global")[0].status == "active"


def test_reject_then_restore_brings_the_global_record_back(world, capsys):
    m = released(capsys)
    before = (world.gmem / f"{m.handle}.md").read_text(encoding="utf-8")
    assert mem.main(["triage", "reject", m.handle]) == 0
    capsys.readouterr()
    assert mem.main(["restore", m.handle, "--global"]) == 0
    capsys.readouterr()
    assert (world.gmem / f"{m.handle}.md").read_text(encoding="utf-8") == before


def test_accept_twice_exits_2_the_second_time(world, capsys):
    m = released(capsys)
    assert mem.main(["triage", "accept", m.handle]) == 0
    capsys.readouterr()
    assert mem.main(["triage", "accept", m.handle]) == 2
    assert "already accepted or never awaited triage" in capsys.readouterr().err


@pytest.mark.parametrize("verb", ["accept", "reject"])
@pytest.mark.parametrize("how", ["forget", "refute"])
def test_a_record_that_is_not_active_exits_2(world, capsys, verb, how):
    m = released(capsys)
    assert mem.main([how, m.handle, "--global", "--because", "invented reason"]) == 0
    capsys.readouterr()
    assert mem.main(["triage", verb, m.handle]) == 2
    assert f"is {'forgotten' if how == 'forget' else 'refuted'}" in capsys.readouterr().err


def test_forget_removes_the_pending_field(world, capsys):
    m = released(capsys)
    assert mem.main(["forget", m.handle, "--global", "--because", "invented reason"]) == 0
    after = records.load_memories(world.gmem, "global")[0]
    assert after.status == "forgotten" and after.triage is None


@pytest.mark.parametrize("verb", ["accept", "reject"])
def test_a_record_in_quarantine_says_how_it_leaves(world, capsys, verb):
    assert remember("session a") == 0
    capsys.readouterr()
    handle = records.load_memories(world.gmem, "global")[0].handle
    assert mem.main(["triage", verb, handle]) == 2
    err = capsys.readouterr().err
    assert "still in quarantine" in err and "second project" in err and "mem confirm --by-owner" in err


def test_a_record_that_never_awaited_triage_is_told_so(world, capsys):
    assert mem.main(["remember", "--global", "--claim", "Walrus queues drain slowly during deploys.", "--kind",
                     "lesson"]) == 0
    capsys.readouterr()
    handle = records.load_memories(world.gmem, "global")[0].handle
    assert mem.main(["triage", "reject", handle]) == 2
    assert "already accepted or never awaited triage" in capsys.readouterr().err


def test_an_unknown_handle_keeps_the_no_memory_message(world, capsys):
    assert mem.main(["triage", "accept", "ffffffffffff"]) == 2
    assert "no memory named" in capsys.readouterr().err


def test_the_quarantine_count_includes_a_lapsed_record_and_skips_a_forgotten_one(world, capsys):
    assert remember("session a", claim="Walrus queues drain slowly during deploys.") == 0
    assert remember("session b", claim="Otter pools refill late after restarts.") == 0
    assert remember("session c", claim="Heron locks release early on timeouts.") == 0
    capsys.readouterr()
    by_claim = {m.claim: m for m in records.load_memories(world.gmem, "global")}
    past = (TODAY - datetime.timedelta(days=3)).isoformat()
    lapsed = by_claim["Walrus queues drain slowly during deploys."]
    lapsed.path.write_text(lapsed.path.read_text().replace(
        f"valid_until: '{lapsed.valid_until}'", f"valid_until: '{past}'").replace(
        f"valid_until: {lapsed.valid_until}", f"valid_until: {past}"), encoding="utf-8")
    reloaded = next(m for m in records.load_memories(world.gmem, "global") if m.handle == lapsed.handle)
    assert reloaded.valid_until is not None and reloaded.valid_until < TODAY and not records.is_live(reloaded, TODAY)
    assert mem.main(["forget", by_claim["Heron locks release early on timeouts."].handle, "--global",
                     "--because", "invented reason"]) == 0
    capsys.readouterr()
    assert mem.main(["curate", "--global"]) == 0
    assert "in quarantine: 2 general lessons," in capsys.readouterr().out
    assert mem.main(["memories", "--global", "--quarantine"]) == 0  # the listing the count points to shows both
    listed = capsys.readouterr().out
    assert lapsed.handle in listed and by_claim["Otter pools refill late after restarts."].handle in listed
    assert by_claim["Heron locks release early on timeouts."].handle not in listed


def test_reject_refuses_when_a_project_folder_has_no_read_permission(world, capsys):
    if os.geteuid() == 0:
        pytest.skip("root reads any folder")
    m = released(capsys)
    ok = link(world, m.handle, world.pa)
    folder = records.project_dir(world.pb)
    before = {p: p.read_bytes() for d in (world.gmem, records.project_dir(world.pa)) for p in sorted(d.glob("*.md"))}
    folder.chmod(0o000)
    try:
        capsys.readouterr()
        assert mem.main(["triage", "reject", m.handle]) == 2
        assert "cannot be read" in capsys.readouterr().err
    finally:
        folder.chmod(0o700)
    assert {p: p.read_bytes() for p in before} == before and ok is not None


def test_curate_project_prints_neither_the_triage_category_nor_the_quarantine_line(world, capsys):
    released(capsys)
    assert remember("session a", claim="Walrus queues drain slowly during deploys.") == 0
    capsys.readouterr()
    assert mem.main(["curate", "--project"]) == 0
    out = capsys.readouterr().out
    assert "awaiting triage" not in out and "in quarantine" not in out


def test_an_unconfirmed_project_record_is_still_listed_as_not_confirmed(world, capsys):
    records.write_memory(records.project_dir(world.pa), "project", kind="lesson",
                         claim="Walrus queues drain slowly during deploys.", body="b\n", today=TODAY,
                         sources=["session a"], origin="transcript", reach="project", weight="medium")
    assert mem.main(["curate", "--project"]) == 0
    out = capsys.readouterr().out
    assert "from a transcript, not confirmed yet" in out and "Walrus queues drain" in out


def test_session_start_prints_normally_with_a_corrupt_corroboration_status(world, capsys):
    released(capsys)
    cdir = world.data / "corroborate"
    cdir.mkdir()
    (cdir / "status.json").write_text("{not json", encoding="utf-8")
    assert mem.main(["session-index"]) == 0
    out = capsys.readouterr().out
    assert "Triage: 1 general lesson awaits triage" in out and "corroboration pass failed" not in out


def test_the_triage_help_explains_triage_without_the_docs(capsys):
    for argv, needle in ((["triage", "--help"], "deciding what a corroborated general lesson becomes"),
                         (["triage", "accept", "--help"], "awaits triage stays a general lesson"),
                         (["triage", "reject", "--help"], "is retired (mem restore brings it back)")):
        with pytest.raises(SystemExit):
            mem.main(argv)
        out = " ".join(capsys.readouterr().out.split())
        assert needle in out and "as mem forget does" not in out


def active_global(world, claim="Zebra caches may expire under load; consider a retry."):
    m = records.write_memory(world.gmem, "global", kind="lesson", claim=claim, body="b\n", today=TODAY)
    return m.handle


def global_record(handle):
    return {m.handle: m for m in records.load_memories(Path(mem.os.environ["MEM_MEMORIES"]), "global")}[handle]


def test_hold_sets_pending_with_its_reason_and_accept_clears_both(world, capsys):
    h = active_global(world)
    assert mem.main(["triage", "hold", f"m:{h}", "--because", "the user wants to reword it"]) == 0
    assert capsys.readouterr().out.strip() == f"m:{h}\theld"
    m = global_record(h)
    assert (m.triage, m.triage_reason) == ("pending", "the user wants to reword it")
    assert mem.main(["show", f"m:{h}"]) == 0
    assert "the user wants to reword it" in capsys.readouterr().out
    assert mem.main(["triage", "accept", f"m:{h}"]) == 0
    m = global_record(h)
    assert (m.triage, m.triage_reason) == (None, None)
    assert "triage_reason" not in m.path.read_text()
    assert records.CURATION_LOG and (world.gmem / records.CURATION_LOG).read_text().count('"action": "triage"') == 2
    assert mem.main(["triage", "hold", f"m:{h}", "--because", "again"]) == 0
    assert mem.main(["triage", "reject", f"m:{h}"]) == 0
    assert global_record(h).triage_reason is None


def test_hold_refuses_a_lesson_in_quarantine_and_a_missing_reason(world, capsys):
    h = active_global(world)
    before = global_record(h).path.read_bytes()
    for extra in ([], ["--because", ""], ["--because", "x" * 201]):
        assert mem.main(["triage", "hold", f"m:{h}", *extra]) == 2
    assert global_record(h).path.read_bytes() == before
    assert remember("session a project " + KEYS[0]) == 0
    (q,) = [m for m in records.load_memories(world.gmem, "global") if m.claim == CLAIM]
    assert records.quarantined(q)
    capsys.readouterr()
    assert mem.main(["triage", "hold", f"m:{q.handle}", "--because", "wait"]) == 2
    assert "quarantine" in capsys.readouterr().err
    assert global_record(q.handle).triage is None


def test_a_held_lesson_does_not_load_and_curate_prints_its_reason(world, capsys):
    h = released(capsys).handle
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--short", "Consider a retry; zebra caches may expire.",
                     "--user-read"]) == 0
    assert mem.main(["triage", "accept", f"m:{h}"]) == 0
    capsys.readouterr()
    assert mem.main(["rules"]) == 0
    assert "Consider a retry" in capsys.readouterr().out
    assert mem.main(["triage", "hold", f"m:{h}", "--because", "the wording is doubtful"]) == 0
    capsys.readouterr()
    assert mem.main(["rules"]) == 0
    assert "Consider a retry" not in capsys.readouterr().out
    assert mem.main(["curate", "--global"]) == 0
    out = capsys.readouterr().out
    assert f"m:{h}" in out and "the wording is doubtful" in out
