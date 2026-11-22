"""`corroborate`: what the pass reads and what it does with the groups a model returns."""
import datetime
from pathlib import Path

import pytest

import corroborate
import records

TODAY = datetime.date(2026, 11, 22)


@pytest.fixture(autouse=True)
def count_temp(monkeypatch):
    monkeypatch.setenv("MEM_COUNT_TEMP_PROJECTS", "1")


def project(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    records.project_dir(path).mkdir(parents=True)
    return path


def put(folder: Path, scope: str, claim: str, *, created=TODAY, sources=("session a",), reach="general",
        weight="medium", origin="transcript", kind="lesson", valid_until=None, **changes) -> records.Memory:
    m = records.write_memory(folder, scope, kind=kind, claim=claim, body="b\n", today=created, sources=sources,
                             origin=origin, reach=reach, weight=weight, valid_until=valid_until)
    return records.update(m, created, **changes) if changes else m


def lessons_of(projects, global_folder=None):
    return corroborate.collect(projects, global_folder, TODAY)


def by_id(lessons):
    return {x.id: x for x in lessons}


def test_counted_projects_skips_missing_unmarked_and_temporary(tmp_path, monkeypatch):
    good = project(tmp_path, "good")
    (tmp_path / "bare").mkdir()
    registry = {"good": {"path": str(good), "seen": "2026-11-01"},
                "missing": {"path": str(tmp_path / "gone"), "seen": "2026-11-01"},
                "bare": {"path": str(tmp_path / "bare"), "seen": "2026-11-01"}}
    assert corroborate.counted_projects(registry) == [good]
    monkeypatch.setenv("MEM_COUNT_TEMP_PROJECTS", "0")
    assert corroborate.counted_projects(registry) == []  # the test folder lives under a temporary root


def test_collect_filters_and_names(tmp_path):
    p1, p2 = project(tmp_path, "one"), project(tmp_path, "two")
    f1 = records.project_dir(p1)
    put(f1, "project", "plain claim")
    put(f1, "project", "linked claim", general="some-global")
    put(f1, "project", "kept local claim", promote="no")
    put(f1, "project", "web claim", origin="web")
    old = put(f1, "project", "old claim")
    records.update(old, TODAY, status="superseded")
    put(records.project_dir(p2), "project", "second project claim")
    glob = tmp_path / "global"
    glob.mkdir()
    put(glob, "global", "global claim")
    got = lessons_of([p1, p2], glob)
    assert sorted(x.id.split(":")[0] for x in got) == ["g", "p1", "p2"]
    assert all(str(tmp_path) not in line and "one" not in line.split("\t")[0] for line in corroborate.lesson_lines(got))
    assert not any("linked" in x.memory.claim or "kept local" in x.memory.claim or "web" in x.memory.claim
                   or "old claim" in x.memory.claim for x in got)


def test_collect_lapsed_and_cut(tmp_path, monkeypatch):
    p = project(tmp_path, "one")
    f = records.project_dir(p)
    put(f, "project", "lapsed recently", valid_until=TODAY - datetime.timedelta(days=60))
    put(f, "project", "lapsed long ago", valid_until=TODAY - datetime.timedelta(days=61))
    put(f, "project", "lapsed but established", sources=("session a", "session b"),
        valid_until=TODAY - datetime.timedelta(days=5))
    assert [x.memory.claim for x in lessons_of([p])] == ["lapsed recently"]
    monkeypatch.setattr(corroborate, "MAX_LESSONS", 2)
    put(f, "project", "newest", created=TODAY + datetime.timedelta(days=1))
    put(f, "project", "older", created=TODAY - datetime.timedelta(days=3))
    got = lessons_of([p])
    assert [x.memory.claim for x in got][0] == "newest" and len(got) == 2


def test_fingerprint(tmp_path):
    p = project(tmp_path, "one")
    f = records.project_dir(p)
    a = put(f, "project", "claim a")
    put(f, "project", "claim b")
    got = lessons_of([p])
    assert corroborate.fingerprint(got) == corroborate.fingerprint(list(reversed(got)))
    records.update(a, TODAY, sources=["session a", "session z"])
    assert corroborate.fingerprint(lessons_of([p])) != corroborate.fingerprint(got)
    assert corroborate.lesson_fingerprint(got[0]) != corroborate.lesson_fingerprint(got[1])


def test_lesson_lines_are_one_line_each(tmp_path):
    p = project(tmp_path, "one")
    glob = tmp_path / "global"
    glob.mkdir()
    put(records.project_dir(p), "project", "local claim", reach="project", context="why\nhere")
    put(glob, "global", "shared claim")
    lines = corroborate.lesson_lines(lessons_of([p], glob))
    assert len(lines) == 2 and all("\n" not in x and len(x.split("\t")) == 4 for x in lines)
    assert {x.split("\t")[1] for x in lines} == {"project", "general"}


def test_validate_groups(tmp_path):
    p = project(tmp_path, "one")
    f = records.project_dir(p)
    put(f, "project", "a", reach="general")
    put(f, "project", "b", reach="project")
    put(f, "project", "c", reach="general")
    glob = tmp_path / "global"
    glob.mkdir()
    put(glob, "global", "g")
    got = lessons_of([p], glob)
    ids = {x.memory.claim: x.id for x in got}
    raw = [{"ids": [ids["a"], ids["c"]], "claim": "good", "context": "ctx"},
           "not an object",
           {"ids": [ids["a"]], "claim": "dup"},
           {"ids": ["p9:nope"], "claim": "unknown"},
           {"ids": [ids["b"], ids["g"]], "claim": "  "},
           {"ids": [ids["b"]], "claim": "single local"},
           {"ids": [ids["g"]], "claim": "single global"},
           {"ids": "p1:x", "claim": "bad ids"}]
    groups, reasons = corroborate.validate_groups(raw, got)
    assert [g.claim for g in groups] == ["good"] and len(reasons) == 7
    assert corroborate.validate_groups({"a": 1}, got)[0] == []
    one = [{"ids": [ids["a"]], "claim": "alone"}]
    assert [g.claim for g in corroborate.validate_groups(one, got)[0]] == ["alone"]


def test_validate_groups_caps(tmp_path, monkeypatch):
    p = project(tmp_path, "one")
    for n in range(3):
        put(records.project_dir(p), "project", f"claim {n}", sources=(f"session s{n}",))
    got = lessons_of([p])
    monkeypatch.setattr(corroborate, "MAX_GROUPS", 2)
    raw = [{"ids": [x.id], "claim": "c"} for x in got]
    assert len(corroborate.validate_groups(raw, got)[0]) == 2


def kinds(acts):
    return [a.kind for a in acts]


def test_two_general_records_of_two_projects(tmp_path):
    p1, p2 = project(tmp_path, "one"), project(tmp_path, "two")
    put(records.project_dir(p1), "project", "x one", sources=("session a",), weight="light", kind="pitfall",
        created=TODAY - datetime.timedelta(days=2))
    put(records.project_dir(p2), "project", "x two", sources=("session b",), weight="strong")
    got = lessons_of([p1, p2])
    group = corroborate.Group([x.id for x in got], "the claim", "the context")
    acts = corroborate.actions(group, by_id(got), [])
    assert kinds(acts) == ["write_global", "link", "link"]
    w = acts[0]
    assert w.record_kind == "pitfall" and w.weight == "strong" and w.claim == "the claim"
    assert w.entries == [records.sighting_entry("session a", records.project_key(p1)),
                         records.sighting_entry("session b", records.project_key(p2))]
    assert {a.target for a in acts[1:]} == {None} and {a.project for a in acts[1:]} == {p1, p2}


def test_one_general_record_alone(tmp_path):
    p = project(tmp_path, "one")
    put(records.project_dir(p), "project", "alone")
    got = lessons_of([p])
    acts = corroborate.actions(corroborate.Group([got[0].id], "c", ""), by_id(got), [])
    assert kinds(acts) == ["write_global", "link"] and acts[1].member == got[0].id


def test_global_member_gets_sightings_and_links(tmp_path):
    p = project(tmp_path, "one")
    glob = tmp_path / "global"
    glob.mkdir()
    g = put(glob, "global", "shared", sources=("session a",))
    put(records.project_dir(p), "project", "local", sources=("session a", "session b"))
    got = lessons_of([p], glob)
    acts = corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got), [g])
    assert kinds(acts) == ["sighting", "sighting", "link"]
    assert all(a.target == g.handle for a in acts)
    assert {a.entry for a in acts[:2]} == {records.sighting_entry(s, records.project_key(p)) for s in ("session a", "session b")}


def test_global_record_holding_a_session_is_the_target(tmp_path):
    p = project(tmp_path, "one")
    glob = tmp_path / "global"
    glob.mkdir()
    g = put(glob, "global", "reworded", sources=("session a",))
    put(records.project_dir(p), "project", "local", sources=("session a",))
    got = [x for x in lessons_of([p]) if x.scope == "project"]
    acts = corroborate.actions(corroborate.Group([got[0].id], "c", ""), by_id(got), [g])
    assert "write_global" not in kinds(acts) and kinds(acts) == ["sighting", "link"]
    assert acts[1].target == g.handle
    key = records.project_key(p)
    done = records.update(g, TODAY, sources=["session a", f"session a project {key}"])
    assert kinds(corroborate.actions(corroborate.Group([got[0].id], "c", ""), by_id(got), [done])) == ["link"]


def test_two_records_of_one_project_merge_into_the_oldest(tmp_path):
    p = project(tmp_path, "one")
    f = records.project_dir(p)
    put(f, "project", "newer", sources=("session b",), created=TODAY)
    put(f, "project", "older", sources=("session a",), created=TODAY - datetime.timedelta(days=4))
    got = lessons_of([p])
    older = next(x for x in got if x.memory.claim == "older")
    newer = next(x for x in got if x.memory.claim == "newer")
    acts = corroborate.actions(corroborate.Group([newer.id, older.id], "c", ""), by_id(got), [])
    assert kinds(acts) == ["merge", "write_global", "link"]
    assert (acts[0].keep, acts[0].drop, acts[0].project) == (older.id, newer.id, p)
    assert len(acts[1].entries) == 2 and acts[1].members == [older.id] and acts[2].member == older.id


def test_two_global_members_merge(tmp_path):
    glob = tmp_path / "global"
    glob.mkdir()
    put(glob, "global", "newer", created=TODAY)
    put(glob, "global", "older", created=TODAY - datetime.timedelta(days=4))
    got = lessons_of([], glob)
    older = next(x for x in got if x.memory.claim == "older")
    acts = corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got), [x.memory for x in got])
    assert kinds(acts) == ["merge_global"] and acts[0].keep == older.id


def test_project_reach_records_of_two_projects_do_nothing(tmp_path):
    p1, p2 = project(tmp_path, "one"), project(tmp_path, "two")
    put(records.project_dir(p1), "project", "x", reach="project")
    put(records.project_dir(p2), "project", "y", reach="project")
    got = lessons_of([p1, p2])
    assert corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got), []) == []
