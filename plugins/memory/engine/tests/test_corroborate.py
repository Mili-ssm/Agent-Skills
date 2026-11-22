"""`corroborate`: what the pass reads and what it does with the groups a model returns."""
import dataclasses
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
    raw = {"groups": [{"ids": [ids["a"], ids["c"]], "claim": "good", "context": "ctx"},
           "not an object",
           {"ids": [ids["a"]], "claim": "dup"},
           {"ids": ["p9:nope"], "claim": "unknown"},
           {"ids": [ids["b"], ids["g"]], "claim": "  "},
           {"ids": [ids["b"]], "claim": "single local"},
           {"ids": [ids["g"]], "claim": "single global"},
           {"ids": "p1:x", "claim": "bad ids"},
           {"ids": [ids["c"], ids["c"]], "claim": "repeated"},
           {"ids": [ids["a"], ids["c"]], "claim": "ok", "context": 5}]}
    groups, reasons = corroborate.validate_groups(raw, got)
    assert [g.claim for g in groups] == ["good"] and len(reasons) == 9
    assert any("group 9" in r and "more than once" in r for r in reasons)
    for bad in ([{"ids": [ids["a"]], "claim": "alone"}], {"a": 1}, {"groups": "x"}, None, "text"):
        groups, reasons = corroborate.validate_groups(bad, got)
        assert groups == [] and len(reasons) == 1
    one = {"groups": [{"ids": [ids["a"]], "claim": "alone"}]}
    assert [g.claim for g in corroborate.validate_groups(one, got)[0]] == ["alone"]


def test_validate_groups_caps(tmp_path, monkeypatch):
    p = project(tmp_path, "one")
    for n in range(3):
        put(records.project_dir(p), "project", f"claim {n}", sources=(f"session s{n}",))
    got = lessons_of([p])
    monkeypatch.setattr(corroborate, "MAX_GROUPS", 2)
    raw = {"groups": [{"ids": [x.id], "claim": "c"} for x in got]}
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
    acts = corroborate.actions(group, by_id(got))
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
    acts = corroborate.actions(corroborate.Group([got[0].id], "c", ""), by_id(got))
    assert kinds(acts) == ["write_global", "link"] and acts[1].member == got[0].id


def test_global_member_gets_sightings_and_links(tmp_path):
    p = project(tmp_path, "one")
    glob = tmp_path / "global"
    glob.mkdir()
    g = put(glob, "global", "shared", sources=("session a",))
    put(records.project_dir(p), "project", "local", sources=("session a", "session b"))
    got = lessons_of([p], glob)
    acts = corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got))
    assert kinds(acts) == ["sighting", "sighting", "link"]
    assert all(a.target == g.handle for a in acts)
    assert {a.entry for a in acts[:2]} == {records.sighting_entry(s, records.project_key(p)) for s in ("session a", "session b")}


def test_a_global_record_that_only_shares_a_session_is_not_the_target(tmp_path):
    p = project(tmp_path, "one")
    glob = tmp_path / "global"
    glob.mkdir()
    put(glob, "global", "another lesson of that session", sources=("session a",))
    put(records.project_dir(p), "project", "local", sources=("session a",))
    got = [x for x in lessons_of([p]) if x.scope == "project"]
    acts = corroborate.actions(corroborate.Group([got[0].id], "c", ""), by_id(got))
    assert kinds(acts) == ["write_global", "link"] and acts[1].target is None


def test_a_verdict_that_cannot_be_placed_keeps_nothing():
    groups = [corroborate.Group(["p1:a", "p1:b"], "c", ""), corroborate.Group(["p2:c"], "d", "")]
    ok = {"reason": "r", "same": True, "faithful": True, "general": True}
    for bad in ("1", True, 1.0, 0, 3, None):
        raw = {"verdicts": [{"group": 1, **ok}, {"group": bad, **ok, "same": False}, {"group": 2, **ok}]}
        kept, reasons = corroborate.validate_verdicts(raw, groups)
        assert kept == [] and len(reasons) == 1


def test_two_records_of_one_project_merge_into_the_oldest(tmp_path):
    p = project(tmp_path, "one")
    f = records.project_dir(p)
    put(f, "project", "newer", sources=("session b",), created=TODAY)
    put(f, "project", "older", sources=("session a",), created=TODAY - datetime.timedelta(days=4))
    got = lessons_of([p])
    older = next(x for x in got if x.memory.claim == "older")
    newer = next(x for x in got if x.memory.claim == "newer")
    acts = corroborate.actions(corroborate.Group([newer.id, older.id], "c", ""), by_id(got))
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
    acts = corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got))
    assert kinds(acts) == ["merge_global"] and acts[0].keep == older.id


def test_project_reach_records_of_two_projects_do_nothing(tmp_path):
    p1, p2 = project(tmp_path, "one"), project(tmp_path, "two")
    put(records.project_dir(p1), "project", "x", reach="project")
    put(records.project_dir(p2), "project", "y", reach="project")
    got = lessons_of([p1, p2])
    assert corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got)) == []


def test_fingerprint_covers_what_the_model_sees(tmp_path):
    p = project(tmp_path, "one")
    a = put(records.project_dir(p), "project", "claim a", context="ctx")
    base = corroborate.fingerprint(lessons_of([p]))
    for change in ({"claim": "claim a2"}, {"context": "ctx2"}, {"reach": "project"}):
        a = records.update(a, TODAY, **change)
        now = corroborate.fingerprint(lessons_of([p]))
        assert now != base
        base = now


def test_fingerprint_does_not_collide_on_a_newline_in_a_source(tmp_path):
    p = project(tmp_path, "one")
    m = put(records.project_dir(p), "project", "claim a")
    one = corroborate.Lesson("p1:x", "project", p, dataclasses.replace(m, sources=["session a\nsession b"]))
    two = corroborate.Lesson("p1:x", "project", p, dataclasses.replace(m, sources=["session a", "session b"]))
    assert corroborate.lesson_fingerprint(one) != corroborate.lesson_fingerprint(two)
    assert corroborate.fingerprint([one]) != corroborate.fingerprint([two])


def test_lines_hold_no_project_name_or_path(tmp_path):
    names = ["zebra-quartz-ledger", "ochre-falcon-vault"]
    projects = [project(tmp_path, n) for n in names]
    glob = tmp_path / "global"
    glob.mkdir()
    for p in projects:
        put(records.project_dir(p), "project", "ordinary claim", context="ordinary context")
    put(records.project_dir(projects[0]), "project", "tab\there\nand a newline", context="c\td")
    put(glob, "global", "global claim")
    got = lessons_of(projects, glob)
    groups = [corroborate.Group([x.id for x in got], "proposed", "ctx")]
    lines = corroborate.lesson_lines(got) + corroborate.verification_lines(groups, by_id(got))
    text = "\n".join(lines)
    parts = {str(tmp_path), *names, *(q for p in projects for q in p.parts if q not in tmp_path.parts)}
    assert all(part not in text for part in parts)
    weird = [x for x in corroborate.lesson_lines(got) if "tab here and a newline" in x]
    assert len(weird) == 1 and len(weird[0].split("\t")) == 4
    member_lines = [x for x in corroborate.verification_lines(groups, by_id(got)) if "tab here" in x]
    assert len(member_lines) == 1 and len(member_lines[0].split("\t")) == 3


def test_verification_lines(tmp_path):
    p = project(tmp_path, "one")
    put(records.project_dir(p), "project", "first", context="why")
    put(records.project_dir(p), "project", "second")
    got = lessons_of([p])
    groups = [corroborate.Group([x.id for x in got], "the claim", "the ctx"), corroborate.Group([got[0].id], "solo", "")]
    lines = corroborate.verification_lines(groups, by_id(got))
    assert lines[0] == "group 1" and lines[1].split("\t")[0] == got[0].id
    assert lines[3] == "proposed\tthe claim\tthe ctx" and lines[4] == "group 2" and len(lines) == 7
    assert lines[-1] == "proposed\tsolo\t"


def verdict(n, same=True, faithful=True, general=True, reason="ok"):
    return {"group": n, "reason": reason, "same": same, "faithful": faithful, "general": general}


def two_groups(tmp_path):
    p = project(tmp_path, "one")
    for n in range(3):
        put(records.project_dir(p), "project", f"claim {n}", sources=(f"session s{n}",))
    got = lessons_of([p])
    return [corroborate.Group([got[0].id, got[1].id], "a", ""), corroborate.Group([got[2].id], "b", "")]


def test_verdicts_all_true_are_kept(tmp_path):
    groups = two_groups(tmp_path)
    kept, reasons = corroborate.validate_verdicts({"verdicts": [verdict(1), verdict(2)]}, groups)
    assert kept == groups and reasons == []


@pytest.mark.parametrize("answer", ["same", "faithful", "general"])
def test_verdicts_each_false_refuses(tmp_path, answer):
    groups = two_groups(tmp_path)
    kept, reasons = corroborate.validate_verdicts({"verdicts": [verdict(1, **{answer: False}), verdict(2)]}, groups)
    assert kept == [groups[1]] and len(reasons) == 1 and "group 1" in reasons[0] and answer in reasons[0]


def test_verdicts_duplicate_missing_unknown_and_empty_reason(tmp_path):
    groups = two_groups(tmp_path)
    kept, reasons = corroborate.validate_verdicts({"verdicts": [verdict(1), verdict(1)]}, groups)
    assert kept == [] and any("group 1" in r for r in reasons) and any("group 2" in r for r in reasons)
    kept, reasons = corroborate.validate_verdicts({"verdicts": [verdict(1), verdict(2), verdict(3)]}, groups)
    assert kept == [] and len(reasons) == 1  # a verdict for a group that does not exist: nothing is kept
    kept, reasons = corroborate.validate_verdicts({"verdicts": [verdict(1, reason=" "), verdict(2)]}, groups)
    assert kept == [groups[1]] and "group 1" in reasons[0]


@pytest.mark.parametrize("bad", ["true", 1, None])
def test_verdicts_only_exact_true_counts(tmp_path, bad):
    groups = two_groups(tmp_path)
    kept, reasons = corroborate.validate_verdicts({"verdicts": [verdict(1, faithful=bad), verdict(2)]}, groups)
    assert kept == [groups[1]] and len(reasons) == 1


def test_verdict_of_a_group_of_one_needs_no_same(tmp_path):
    groups = two_groups(tmp_path)
    v = verdict(2)
    del v["same"]
    kept, reasons = corroborate.validate_verdicts({"verdicts": [verdict(1), v]}, groups)
    assert kept == groups and reasons == []
    v1 = verdict(1)
    del v1["same"]
    assert corroborate.validate_verdicts({"verdicts": [v1, verdict(2)]}, groups)[0] == [groups[1]]


@pytest.mark.parametrize("raw", [None, "x", [], {}, {"verdicts": "x"}, {"verdicts": [1, "a", None]},
                                 {"verdicts": [{"group": "1", "reason": "r", "same": True, "faithful": True,
                                                "general": True}]},
                                 {"verdicts": [{"group": True, "reason": "r", "same": True, "faithful": True,
                                                "general": True}]}])
def test_verdicts_garbage_keeps_nothing(tmp_path, raw):
    groups = two_groups(tmp_path)
    kept, reasons = corroborate.validate_verdicts(raw, groups)
    assert kept == [] and reasons


def test_a_member_with_no_session_makes_no_action(tmp_path):
    p = project(tmp_path, "one")
    put(records.project_dir(p), "project", "no evidence", sources=())
    got = lessons_of([p])
    assert corroborate.actions(corroborate.Group([got[0].id], "c", ""), by_id(got)) == []


def test_a_member_with_no_session_is_not_linked(tmp_path):
    p1, p2 = project(tmp_path, "one"), project(tmp_path, "two")
    put(records.project_dir(p1), "project", "no evidence", sources=())
    put(records.project_dir(p2), "project", "with evidence", sources=("session a",))
    got = lessons_of([p1, p2])
    acts = corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got))
    assert kinds(acts) == ["write_global", "link"] and acts[1].project == p2


def test_write_global_holds_each_session_once(tmp_path):
    p1, p2 = project(tmp_path, "one"), project(tmp_path, "two")
    put(records.project_dir(p1), "project", "x one", sources=("session a",))
    put(records.project_dir(p2), "project", "x two", sources=("session a", "session b"))
    got = lessons_of([p1, p2])
    acts = corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got))
    assert acts[0].entries == [records.sighting_entry("session a", records.project_key(p1)),
                               records.sighting_entry("session b", records.project_key(p2))]


def test_sightings_of_a_project_member_go_to_the_oldest_global(tmp_path):
    p = project(tmp_path, "one")
    glob = tmp_path / "global"
    glob.mkdir()
    put(glob, "global", "newer", created=TODAY)
    old = put(glob, "global", "older", created=TODAY - datetime.timedelta(days=4))
    put(records.project_dir(p), "project", "local", sources=("session z",))
    got = lessons_of([p], glob)
    acts = corroborate.actions(corroborate.Group([x.id for x in got], "c", ""), by_id(got))
    assert kinds(acts) == ["merge_global", "sighting", "link"]
    assert acts[1].target == old.handle and acts[2].target == old.handle


def test_a_group_with_a_global_member_needs_no_faithful(tmp_path):
    groups = [corroborate.Group(["g:kept", "p1:a"], "unused wording", ""), corroborate.Group(["p1:b", "p2:c"], "c", "")]
    raw = {"verdicts": [verdict(1, faithful=False), verdict(2, faithful=False)]}
    kept, reasons = corroborate.validate_verdicts(raw, groups)
    assert kept == [groups[0]] and len(reasons) == 1 and "group 2" in reasons[0]
    kept, _ = corroborate.validate_verdicts({"verdicts": [verdict(1, same=False), verdict(2)]}, groups)
    assert kept == [groups[1]]


# ---- fill: the lessons that lack a short form --------------------------------------------------------------------

K1, K2 = "0123456789ab", "ba9876543210"
TWO = (f"session a project {K1}", f"session b project {K2}")
SHORT = "Brief a subagent with the acceptance check first, as it may help it tell when it is done."


def fill_world(tmp_path):
    p1, p2 = project(tmp_path, "one"), project(tmp_path, "two")
    glob = tmp_path / "global"
    glob.mkdir()
    return p1, p2, glob


def fill_ids(found):
    return [i for i, _m in found]


def test_fill_candidates_leave_out_what_cannot_load(tmp_path):
    p1, p2, glob = fill_world(tmp_path)
    f1 = records.project_dir(p1)
    put(f1, "project", "project lesson seen twice", sources=("session a", "session b"), weight="medium")
    put(f1, "project", "project lesson seen once", weight="medium", sources=("session a",))  # not established
    put(f1, "project", "confirmed once", sources=("session a",), weight="medium", owner_confirmed=TODAY)
    put(f1, "project", "turned off", weight="light", load="no")
    put(f1, "project", "hand written", weight="light", origin="web")
    put(f1, "project", "has both", weight="light", short=SHORT, topic="process")
    put(f1, "project", "has no topic", weight="light", sources=("session a", "session b"), short=SHORT)
    put(glob, "global", "established global", sources=TWO, triage=None)
    put(glob, "global", "quarantined global", sources=(TWO[0],))
    put(glob, "global", "awaiting triage", sources=(*TWO, f"session c project {K1}"), weight="strong")  # only a strong one waits
    got = corroborate.fill_candidates([p1, p2], glob, TODAY)
    claims = {m.claim for _i, m in got}
    assert claims == {"project lesson seen twice", "confirmed once", "has no topic", "established global"}, claims
    assert {i.split(":")[0] for i in fill_ids(got)} == {"p1", "g"}


def test_fill_candidates_order_and_cap(tmp_path):
    p1, p2, glob = fill_world(tmp_path)
    f1 = records.project_dir(p1)
    put(f1, "project", "twice", sources=("session a", "session b"), weight="light")
    put(f1, "project", "four times", sources=tuple(f"session {c}" for c in "abcd"), weight="light")
    put(f1, "project", "confirmed", sources=("session a",), weight="light", owner_confirmed=TODAY)
    got = corroborate.fill_candidates([p1, p2], glob, TODAY)
    assert [m.claim for _i, m in got] == ["confirmed", "four times", "twice"]
    assert [m.claim for _i, m in corroborate.fill_candidates([p1, p2], glob, TODAY, cap=2)] == ["confirmed", "four times"]


def test_fill_lines_hold_id_claim_and_context(tmp_path):
    p1, p2, glob = fill_world(tmp_path)
    put(records.project_dir(p1), "project", "A claim.", sources=("session a", "session b"), weight="light", context="when testing")
    put(glob, "global", "Another claim.", sources=TWO, triage=None)
    text = corroborate.fill_lines(corroborate.fill_candidates([p1], glob, TODAY))
    blocks = text.strip().split("\n\n")
    assert len(blocks) == 2
    assert any(b.splitlines()[1:] == ["claim: A claim.", "context: when testing"] and b.startswith("id: p1:") for b in blocks)
    assert any(b.splitlines()[1:] == ["claim: Another claim."] and b.startswith("id: g:") for b in blocks)


def test_validate_fill_keeps_the_good_items_marks_the_invalid_ones_and_drops_the_rest():
    ids = ["g:a", "g:b", "p1:c", "p1:d", "p1:e", "p1:f", "p1:g"]
    raw = {"items": [
        {"id": "g:a", "short": SHORT, "topic": "process"},
        {"id": "g:zzz", "short": SHORT, "topic": "process"},          # unknown id: dropped
        {"id": "g:a", "short": SHORT, "topic": "docs"},               # repeated id: dropped
        {"id": "g:b", "short": "x" * 421, "topic": "docs"},           # too long: kept with a problem, cut to 300
        {"id": "p1:c", "short": SHORT, "topic": "Testing"},           # a capital
        {"id": "p1:d", "short": "two\nlines", "topic": "docs"},
        {"id": ["p1:e"], "short": SHORT, "topic": "docs"},            # no usable id: dropped
        "nonsense",                                                   # dropped
        {"id": "p1:e", "short": "y" * 120, "topic": "shell tools"},
        {"id": "p1:f", "short": 7},                                   # not strings: empty
    ]}
    kept, reasons = corroborate.validate_fill(raw, ids)
    assert kept["g:a"] == {"short": SHORT, "topic": "process"}
    assert kept["p1:e"] == {"short": "y" * 120, "topic": "shell tools"}
    assert kept["g:b"] == {"short": "x" * 300, "topic": "docs", "problem": "short has 421 characters, at most 120"}
    assert kept["p1:c"] == {"short": SHORT, "topic": "Testing", "problem": "topic must be one or two lowercase words"}
    assert kept["p1:d"]["problem"] == "short must be one line"
    assert kept["p1:f"] == {"short": "", "topic": "", "problem": "short is empty; topic must be one or two lowercase words"}
    assert "p1:g" not in kept
    assert len(reasons) == 4
    assert any("unknown id g:zzz" in r for r in reasons) and any("repeats g:a" in r for r in reasons)


@pytest.mark.parametrize("raw", [None, [], "x", {}, {"items": "x"}, {"groups": []}])
def test_validate_fill_garbage_keeps_nothing(raw):
    kept, reasons = corroborate.validate_fill(raw, ["g:a"])
    assert kept == {} and len(reasons) == 1


def test_validate_fill_the_first_item_of_a_known_id_decides_even_with_a_problem():
    raw = {"items": [{"id": "g:a", "short": "x" * 121, "topic": "docs"},
                     {"id": "g:a", "short": SHORT, "topic": "docs"}]}
    kept, reasons = corroborate.validate_fill(raw, ["g:a"])
    assert list(kept) == ["g:a"] and "problem" in kept["g:a"]
    assert len(reasons) == 1 and "repeats g:a" in reasons[0]


def test_fill_candidates_still_propose_for_an_index_only_lesson(tmp_path):
    p1, p2, glob = fill_world(tmp_path)
    f1 = records.project_dir(p1)
    put(f1, "project", "index only no topic", weight="light", sources=("session a", "session b"), short=SHORT, load="index")
    put(f1, "project", "index only no short", weight="light", sources=("session a", "session b"), topic="process", load="index")
    put(f1, "project", "index only complete", weight="light", sources=("session a", "session b"), short=SHORT, topic="process", load="index")
    got = corroborate.fill_candidates([p1, p2], glob, TODAY)
    assert {m.claim for _i, m in got} == {"index only no topic", "index only no short"}
