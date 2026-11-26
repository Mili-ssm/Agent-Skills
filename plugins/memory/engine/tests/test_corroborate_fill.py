"""`bin/mem-corroborate`: fill and fill_auto: short forms."""

import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import corroborate
import corroborate_cli
import corroborate_fill
import corroborate_run
import corroborate_state
import jobs
import pytest
import records
from corroborate_world import (
    BRIEF,
    BRIEF2,
    GCLAIM,
    NARROW,
    OPTION,
    TODAY,
    by_claim,
    calls,
    candidate_ids,
    fake_plugin,
    glob,
    globals_,
    group,
    ident,
    lesson,
    lessons,
    log_lines,
    model,
    project_records,
    run,
    snapshot,
    status,
    two_projects,
    w,
)

__all__ = ["w"]  # re-exported: pytest finds the fixture in this module by its name

EXIT_USAGE = 2  # `mem-corroborate` exit status for a bad command line
ITEM_PAIR = 2  # items, written records or log hits that a two-item proposal yields
SESSION_PAIR = 2  # writer and checker sessions of one run; two failed runs
CALLS_TWO_RUNS = 4  # fake-claude calls of two runs (writer and checker each)
CALLS_THREE_FAILS = 3  # fake-claude calls of three failed runs (writer only)
FILL_WORLD_LESSONS = 4  # lessons `fill_world` leaves to fill
PRIVATE_MODE = 0o600  # the permission bits of a private state file

# ---- fill: a short form and a topic proposed into a file the owner reads ------------------------------------------

SAME = (
    "Hand a subagent the acceptance check before it starts, as it may help it tell when it is done."
)
SHORT = "Give a subagent the acceptance check first, as it may help it know when it is done."


def fill_world(w):
    """The same claim (so the same handle) in two projects, one global lesson and one that stays out of the file."""
    lesson(w, w.pa, SAME, ("s1", "s2"))
    lesson(w, w.pb, SAME, ("s3", "s4"))
    g = records.write_memory(
        w.gmem,
        "global",
        kind="lesson",
        claim="Read the whole failing test output before you change any code.",
        body="b\n",
        today=TODAY,
        origin="transcript",
        reach="general",
        weight="light",
        sources=[
            f"session s5 project {records.project_key(w.pa)}",
            f"session s6 project {records.project_key(w.pb)}",
        ],
    )
    g = records.update(g, TODAY, triage=None)  # a released global record starts as pending
    lesson(
        w,
        w.pa,
        "Run the narrowest test that covers a change before the whole suite, as it may save time.",
        ("s7", "s8"),
    )
    return g


def fill_ids(w):
    return {(x.id.split(":")[0], x.memory.handle): x.id for x in lessons(w)}


def fill_answer(w, items):
    (w.tmp / "fill-answer.json").write_text(
        items if isinstance(items, str) else json.dumps({"items": items})
    )
    os.environ["FAKE_FILL"] = str(w.tmp / "fill-answer.json")


def fill_run(w, *args, **kw):
    return run(w, *args, cmd="fill", **kw)


def cut_problems(out):
    """The owner cuts the items the dry run marked with a problem."""
    out.write_text(json.dumps([i for i in json.loads(out.read_text()) if "problem" not in i]))


def proposal(w, g):
    ids = fill_ids(w)
    handle = records.load_memories(records.project_dir(w.pa), "project")[0].handle
    shared = [i for (kind, h), i in ids.items() if kind != "g" and h == handle]
    assert len(shared) == ITEM_PAIR
    gid = ids["g", g.handle]
    fill_answer(
        w,
        [
            {"id": shared[0], "short": SHORT, "topic": "process"},
            {
                "id": shared[1],
                "short": SHORT + " ",
                "topic": "Process",
            },  # invalid: kept for the owner, with a problem
            {
                "id": gid,
                "short": "Read a failing test output to the end before changing code.",
                "topic": "testing",
            },
            {"id": "g:nothing", "short": SHORT, "topic": "process"},
        ],
    )
    return shared, gid


def test_fill_dry_run_writes_the_proposal_and_changes_nothing(w):
    g = fill_world(w)
    shared, gid = proposal(w, g)
    before = snapshot(w)
    out = w.tmp / "proposal.json"
    done = fill_run(w, "--dry-run", "--out", str(out))
    assert done.returncode == 0, done.stderr
    assert "4 lessons asked, 2 kept, 2 to edit, 1 dropped" in done.stdout, done.stdout
    items = json.loads(out.read_text())
    assert {(i["id"], i["scope"]) for i in items if "problem" not in i} == {
        (shared[0], w.pa.name),
        (gid, "global"),
    }
    assert (
        len([i for i in items if "problem" in i]) == ITEM_PAIR
    )  # the invalid one and the lesson with no proposal
    items = [i for i in items if "problem" not in i]
    first = items[0]
    assert set(first) == {
        "id",
        "handle",
        "scope",
        "claim",
        "short",
        "topic",
        "load",
        "claim_digest",
    }
    assert (first["claim"], first["short"], first["topic"], first["load"]) == (
        SAME,
        SHORT,
        "process",
        "yes",
    )
    assert first["claim_digest"] == corroborate.claim_digest(
        next(m for m in project_records(w.pa).values() if m.claim == SAME)
    )
    assert (
        snapshot(w) == before
        and calls(w) == 1
        and not log_lines(w)
        and not (w.cdir / "runs").exists()
    )
    call = json.loads(w.calls_file.read_text().splitlines()[0])
    assert (
        call["args"][call["args"].index("--tools") + 1] == "Read,Write"
        and "fill.json" not in call["files"]
    )
    assert "lessons.txt" in call["files"] and not any(
        v.startswith("CLAUDE_PLUGIN") for v in call["mem_vars"]
    )


def test_fill_dry_run_keeps_what_needs_editing_with_its_problem_and_apply_ignores_the_field(w):
    g = fill_world(w)
    shared, gid = proposal(w, g)
    other = next(i for (k, h), i in fill_ids(w).items() if k != "g" and i not in shared)
    fill_answer(
        w,
        [
            {"id": shared[0], "short": "x" * 134, "topic": "process"},
            {
                "id": gid,
                "short": "Read a failing test output to the end before changing code.",
                "topic": "Testing",
            },
            {"id": "g:nothing", "short": SHORT, "topic": "process"},
        ],
    )
    out = w.tmp / "proposal.json"
    done = fill_run(w, "--dry-run", "--out", str(out))
    assert done.returncode == 0, done.stderr
    assert "4 lessons asked, 0 kept, 4 to edit, 1 dropped" in done.stdout, done.stdout
    by_id = {i["id"]: i for i in json.loads(out.read_text())}
    assert set(by_id) == {shared[0], shared[1], gid, other}
    assert (
        by_id[shared[0]]["problem"] == "short has 134 characters, at most 120"
        and by_id[shared[0]]["short"] == "x" * 134
    )
    assert (
        by_id[gid]["problem"] == "topic must be one or two lowercase words"
        and by_id[gid]["topic"] == "Testing"
    )
    assert by_id[shared[1]]["problem"] == by_id[other]["problem"] == "no proposal"
    assert (by_id[other]["short"], by_id[other]["topic"]) == ("", "")
    assert {
        "id",
        "handle",
        "scope",
        "claim",
        "short",
        "topic",
        "load",
        "claim_digest",
        "problem",
    } == set(by_id[other])
    # the owner repairs one item and leaves the others: `problem` is ignored, the rest is validated as ever
    items = list(by_id.values())
    for i in items:
        if i["id"] == shared[0]:
            i["short"] = SHORT
    out.write_text(json.dumps(items))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 4, "written": 1, "dropped": 3, "failed": 0}
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    assert (a.short, a.topic) == (SHORT, "process")


def test_fill_dry_run_asks_for_no_lesson_that_has_nothing_to_fill(w):
    done = fill_run(w, "--dry-run", "--out", str(w.tmp / "p.json"), mode="never")
    assert done.returncode == 0 and json.loads((w.tmp / "p.json").read_text()) == []


def test_fill_items_write_exactly_the_file_and_undo_puts_them_back(w):
    g = fill_world(w)
    _shared, _gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    before = snapshot(w)
    items = json.loads(out.read_text())
    for i in items:
        i["topic"] = "review"  # the owner edits the file
    out.write_text(json.dumps(items))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    b = next(m for m in project_records(w.pb).values() if m.claim == SAME)
    assert a.handle == b.handle  # the same handle, in two projects
    assert (a.short, a.topic) == (SHORT, "review") and (b.short, b.topic) == (
        None,
        None,
    )  # only the project of the item
    (g_now,) = [m for m in globals_(w) if m.handle == g.handle]
    assert (
        g_now.short is not None
        and g_now.short.startswith("Read a failing test")
        and g_now.topic == "review"
    )
    other = [m for m in project_records(w.pa).values() if m.claim.startswith("Run the narrowest")]
    assert other[0].short is None
    line = log_lines(w)[-1]
    assert (
        line["fill"] == {"asked": 2, "written": 2, "dropped": 0, "failed": 0}
        and "t" in line
        and "ms" in line
    )
    assert not (w.cdir / "seen.json").exists() and not (w.cdir / "status.json").exists()
    (stamp,) = [p.name for p in (w.cdir / "runs").iterdir()]
    assert stamp in done.stdout
    undone = run(w, stamp, cmd="undo", claude=False)
    assert undone.returncode == 0, undone.stderr
    assert snapshot(w) == before and not (w.cdir / "seen.json").exists()


def test_fill_items_applies_a_read_file_without_the_mark(w):
    g = fill_world(w)
    proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    written = [m for m in [*project_records(w.pa).values(), *globals_(w)] if m.short]
    assert written and all(m.short_by is None for m in written)


def test_fill_items_write_the_second_project_of_a_shared_handle(w):
    g = fill_world(w)
    shared, _gid = proposal(w, g)
    fill_answer(w, [{"id": shared[1], "short": SHORT, "topic": "process"}])
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    assert fill_run(w, "--items", str(out), claude=False, mode="never").returncode == 0
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    b = next(m for m in project_records(w.pb).values() if m.claim == SAME)
    assert (a.short, b.short, b.topic) == (None, SHORT, "process")


def test_fill_items_refuse_an_item_whose_claim_changed(w):
    g = fill_world(w)
    proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    records.update(a, TODAY, claim=SAME + " Provisional.")
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 1
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 1, "dropped": 0, "failed": 1}
    a = next(m for m in project_records(w.pa).values() if m.claim.startswith(SAME))
    assert a.short is None
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert "changed its claim" in (run_dir / "log.txt").read_text()


def test_fill_items_drop_what_is_invalid_or_unknown_and_rewrite_a_filled_record(w):
    fill_world(w)
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    records.update(
        a, TODAY, short="An older short form that the owner chose to rewrite.", topic="docs"
    )
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    ids = fill_ids(w)
    pid = (
        ids["p", a.handle]
        if ("p", a.handle) in ids
        else next(i for (k, h), i in ids.items() if h == a.handle and k != "g")
    )
    digest = corroborate.claim_digest(a)
    good = {
        "id": pid,
        "handle": a.handle,
        "scope": w.pa.name,
        "claim": SAME,
        "short": SHORT,
        "topic": "process",
        "claim_digest": digest,
    }
    file = w.tmp / "items.json"
    file.write_text(
        json.dumps([
            good,
            {**good, "short": "x" * 121},
            {**good, "id": "g:nothing"},
            {**good},
            "nonsense",
            {**good, "id": "p9:" + a.handle},
        ])
    )
    done = fill_run(w, "--items", str(file), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 6, "written": 1, "dropped": 5, "failed": 0}
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    assert (a.short, a.topic) == (SHORT, "process")


def test_fill_alone_or_with_a_bad_file_exits_2(w):
    fill_world(w)
    done = fill_run(w, mode="never")
    assert done.returncode == EXIT_USAGE and "usage" in done.stderr and not log_lines(w)
    assert fill_run(w, "--dry-run", mode="never").returncode == EXIT_USAGE
    assert fill_run(w, "--out", str(w.tmp / "x.json"), mode="never").returncode == EXIT_USAGE
    assert (
        fill_run(w, "--items", str(w.tmp / "none.json"), "--dry-run", mode="never").returncode
        == EXIT_USAGE
    )
    (w.tmp / "bad.json").write_text("{}")
    assert (
        fill_run(w, "--items", str(w.tmp / "bad.json"), claude=False, mode="never").returncode
        == EXIT_USAGE
    )
    assert not (w.cdir / "runs").exists()


def fill_file(w, g, **change):
    """The proposal file of `proposal`, with the changes applied to every item."""
    shared, gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    items = [{**i, **change} for i in json.loads(out.read_text())]
    out.write_text(json.dumps(items))
    return out, shared, gid


def test_fill_items_drop_an_item_whose_handle_or_scope_disagrees_with_its_id(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g)
    items = json.loads(out.read_text())
    items[0]["handle"] = "other-handle"
    items[1]["scope"] = w.pb.name
    out.write_text(json.dumps(items))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 0, "dropped": 2, "failed": 0}
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert (run_dir / "log.txt").read_text().count(
        "handle or scope does not match its id"
    ) == ITEM_PAIR
    assert all(m.short is None for m in project_records(w.pa).values()) and all(
        m.short is None for m in globals_(w)
    )


def test_fill_items_apply_an_item_without_handle_and_scope_by_its_id(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g)
    items = [
        {k: v for k, v in i.items() if k not in {"handle", "scope"}}
        for i in json.loads(out.read_text())
    ]
    out.write_text(json.dumps(items))
    assert fill_run(w, "--items", str(out), claude=False, mode="never").returncode == 0
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 2, "dropped": 0, "failed": 0}


def test_fill_items_start_no_settling_run(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g)
    seen_env = w.tmp / "seen-env"
    broken = fake_plugin(
        w,
        f'if [ "$1" = memory ]; then echo "$MEM_SETTLE_AUTO|$MEM_SETTLE_MINUTES|$MEM_SETTLE_CLAUDE" >> {seen_env}; fi',
    )
    env = {"MEM_SETTLE_AUTO": "1", "MEM_SETTLE_MINUTES": "5", "MEM_SETTLE_CLAUDE": "/bin/true"}
    done = run(w, "--items", str(out), cmd="fill", claude=False, mode="never", corr=broken, env=env)
    assert done.returncode == 0, done.stderr
    assert seen_env.read_text().split() == ["||"] * 2


def test_fill_items_drop_a_record_that_cannot_load(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g)
    (g_now,) = [m for m in globals_(w) if m.handle == g.handle]
    records.update(g_now, TODAY, triage="pending")
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    records.update(a, TODAY, origin="web")
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 0, "dropped": 2, "failed": 0}
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert (run_dir / "log.txt").read_text().count("not a lesson that can load") == ITEM_PAIR


def test_fill_dry_run_checks_the_output_folder_before_the_session(w):
    fill_world(w)
    done = fill_run(w, "--dry-run", "--out", str(w.tmp / "missing" / "p.json"))
    assert (
        done.returncode == EXIT_USAGE
        and len(done.stderr.strip().splitlines()) == 1
        and calls(w) == 0
    )
    locked = w.tmp / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("permissions are not enforced here")
        done = fill_run(w, "--dry-run", "--out", str(locked / "p.json"))
        assert (
            done.returncode == EXIT_USAGE
            and len(done.stderr.strip().splitlines()) == 1
            and calls(w) == 0
        )
    finally:
        locked.chmod(0o700)


def _a(w):
    return next(m for m in project_records(w.pa).values() if m.claim == SAME)


def test_fill_dry_run_writes_index_for_an_index_only_lesson(w):
    g = fill_world(w)
    records.update(_a(w), TODAY, load="index")
    out, shared, _gid = fill_file(w, g)
    assert {i["id"]: i["load"] for i in json.loads(out.read_text())}[shared[0]] == "index"


def test_fill_items_apply_the_load_value(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g)
    items = json.loads(out.read_text())
    items[0]["load"] = "index"
    items[1]["load"] = "no"
    out.write_text(json.dumps(items))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 2, "dropped": 0, "failed": 0}
    assert (_a(w).short, _a(w).load) == (SHORT, "index")
    (gl,) = [m for m in globals_(w) if m.handle == g.handle]
    assert gl.short and gl.load == "no"
    items[0]["load"] = "yes"
    out.write_text(json.dumps(items[:1]))
    assert fill_run(w, "--items", str(out), claude=False, mode="never").returncode == 0
    assert _a(w).load is None and _a(w).short == SHORT


def test_fill_items_load_alone_with_unchanged_short_and_topic(w):
    g = fill_world(w)
    out, shared, _gid = fill_file(w, g)
    records.update(_a(w), TODAY, short=SHORT, topic="process")
    item = {
        "id": shared[0],
        "handle": _a(w).handle,
        "scope": w.pa.name,
        "claim": SAME,
        "short": SHORT,
        "topic": "process",
        "load": "index",
        "claim_digest": corroborate.claim_digest(_a(w)),
    }
    out.write_text(json.dumps([item]))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert (_a(w).short, _a(w).topic, _a(w).load) == (SHORT, "process", "index")


def test_fill_items_drop_a_bad_load_value(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g, load="maybe")
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 0, "dropped": 2, "failed": 0}
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert (run_dir / "log.txt").read_text().count("load must be yes, index or no") == ITEM_PAIR
    assert _a(w).short is None


def test_fill_items_drop_a_list_valued_load(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g, load=["yes"])
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 0, "dropped": 2, "failed": 0}
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert (run_dir / "log.txt").read_text().count("load must be yes, index or no") == ITEM_PAIR
    assert _a(w).short is None


def test_fill_items_turn_on_a_record_that_was_turned_off(w):
    g = fill_world(w)
    out, _shared, _gid = fill_file(w, g)
    records.update(_a(w), TODAY, load="no")
    done = fill_run(w, "--items", str(out), claude=False, mode="never")  # the items say load yes
    assert done.returncode == 0, done.stderr
    assert (_a(w).short, _a(w).load) == (SHORT, None)
    records.update(_a(w), TODAY, load="no")
    items = [{k: v for k, v in i.items() if k != "load"} for i in json.loads(out.read_text())][:1]
    out.write_text(json.dumps(items))  # no load value: a rule turned off stays off
    assert fill_run(w, "--items", str(out), claude=False, mode="never").returncode == 0
    assert _a(w).load == "no" and log_lines(w)[-1]["fill"]["dropped"] == 1


def test_fill_items_and_undo_behave_as_before_through_apply_fill(w):
    g = fill_world(w)
    _shared, _gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    before = snapshot(w)
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert "2 asked, 2 written, 0 dropped, 0 failed" in done.stdout
    (stamp,) = [p.name for p in (w.cdir / "runs").iterdir()]
    assert (
        stamp.endswith("-fill") and (w.cdir / "runs" / stamp / "fill").exists()
    )  # never shares a name with a pass run
    assert run(w, cmd="status", claude=False).returncode == 0
    assert run(w, stamp, cmd="undo", claude=False).returncode == 0
    assert snapshot(w) == before and not (w.cdir / "seen.json").exists()


def test_apply_fill_passes_user_read_only_when_asked(w):
    g = fill_world(w)
    shared, gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    items = json.loads(out.read_text())
    result = corroborate_fill.apply_fill(items, w.cdir / "runs" / "direct-fill", user_read=False)
    assert result["written"] == ITEM_PAIR and result["dropped"] == result["failed"] == 0
    assert sorted(result["applied"]) == sorted([shared[0], gid])
    written = [m for m in [*project_records(w.pa).values(), *globals_(w)] if m.short]
    assert len(written) == ITEM_PAIR and all(m.short_by == "model" for m in written)


SHORTS = {
    SAME: SHORT,
    GCLAIM: "Read the whole failing test output before changing code.",
    NARROW: "Run the narrowest covering test before the whole suite, as it may save time.",
}


def answers(w, mp, writer: str = "ok", checker: bool | str = True, shorts=None):
    """The fake's two answers. writer: "ok" (a short for every candidate), "none" (no file) or the file's text;
    checker: True or False for every short, "none", or the file's text."""
    shorts = {**SHORTS, **(shorts or {})}
    mp.delenv("FAKE_FILL", raising=False)
    mp.delenv("FAKE_VERDICTS", raising=False)
    if writer == "ok":
        items = [
            {"id": i, "short": shorts[c], "topic": "process"}
            for c, ids in candidate_ids(w).items()
            for i in ids
        ]
        writer = json.dumps({"items": items})
    if writer != "none":
        (w.tmp / "fill-answer.json").write_text(writer)
        mp.setenv("FAKE_FILL", str(w.tmp / "fill-answer.json"))
    if checker in {True, False}:
        every = [i for ids in candidate_ids(w).values() for i in ids]
        checker = json.dumps({
            "verdicts": [{"id": i, "reason": "r", "faithful": checker} for i in every]
        })
    if checker != "none":
        (w.tmp / "verdicts.json").write_text(checker)
        mp.setenv("FAKE_VERDICTS", str(w.tmp / "verdicts.json"))


def auto(w):
    return corroborate_fill.fill_auto(str(w.fake), 0.25)


def attempts(w):
    return json.loads((w.cdir / "fill-attempts.json").read_text())


def one_lesson(w, claim=NARROW):
    return lesson(w, w.pa, claim, ("s7", "s8"))


def fill_runs(w):
    return (
        sorted(p for p in (w.cdir / "runs").iterdir() if p.name.endswith("-fill"))
        if (w.cdir / "runs").exists()
        else []
    )


def test_fill_auto_writes_a_checked_short_form_marked_as_the_models(w, monkeypatch):
    g = fill_world(w)
    answers(w, monkeypatch)
    result = auto(w)
    assert result == {
        "asked": 4,
        "written": 4,
        "dropped": 0,
        "refused_code": 0,
        "refused_check": 0,
        "to_triage": 0,
        "left": 0,
        "cost": 0.06,
        "stopped": None,
    }
    assert calls(w) == SESSION_PAIR
    narrow = by_claim(w, NARROW)
    assert (narrow.short, narrow.topic, narrow.short_by, narrow.load) == (
        SHORTS[NARROW],
        "process",
        "model",
        None,
    )
    (gl,) = [m for m in globals_(w) if m.handle == g.handle]
    assert gl.short_by == "model" and gl.short == SHORTS[GCLAIM]
    assert status(w)["fill"] == result


def test_fill_auto_refuses_by_code_before_paying_the_checker(w, monkeypatch):
    one_lesson(w)
    answers(
        w, monkeypatch, shorts={NARROW: "Run the narrowest covering test before the whole suite."}
    )
    result = auto(w)
    assert (result["refused_code"], result["written"], result["refused_check"]) == (1, 0, 0)
    assert calls(w) == 1 and by_claim(w, NARROW).short is None


def test_fill_auto_does_not_write_what_the_checker_refused(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, checker=False)
    result = auto(w)
    assert (result["refused_check"], result["written"]) == (1, 0)
    assert calls(w) == SESSION_PAIR and by_claim(w, NARROW).short is None and not fill_runs(w)


def test_a_general_lesson_is_held_at_triage_with_its_reason_after_two_refusals_and_a_project_lesson_is_left(
    w, monkeypatch
):
    g = fill_world(w)
    answers(w, monkeypatch, checker=False)
    first = auto(w)
    assert (first["to_triage"], first["left"], first["refused_check"]) == (0, 0, 4)
    assert attempts(w)["lessons"] and all(v["count"] == 1 for v in attempts(w)["lessons"].values())
    second = auto(w)
    assert (second["to_triage"], second["left"]) == (1, 3)
    (gl,) = [m for m in globals_(w) if m.handle == g.handle]
    assert (gl.triage, gl.triage_reason) == (
        "pending",
        "the checker did not find the short form faithful to the claim",
    )
    assert all(m.triage is None for m in project_records(w.pa).values())


def test_a_third_run_starts_no_session_for_a_lesson_refused_twice(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, checker=False)
    auto(w)
    auto(w)
    assert calls(w) == CALLS_TWO_RUNS
    third = auto(w)
    assert calls(w) == CALLS_TWO_RUNS and third["asked"] == 0 and third["stopped"] is None


def test_an_applied_short_form_that_was_undone_is_not_written_again(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    assert auto(w)["written"] == 1
    (run_dir,) = fill_runs(w)
    assert run(w, run_dir.name, cmd="undo", claude=False).returncode == 0
    assert by_claim(w, NARROW).short is None
    again = auto(w)
    assert calls(w) == SESSION_PAIR and again["asked"] == 0 and by_claim(w, NARROW).short is None


def test_an_applied_short_form_the_owner_removed_is_not_written_again_until_the_claim_changes(
    w, monkeypatch
):
    m = one_lesson(w)
    answers(w, monkeypatch)
    assert auto(w)["written"] == 1
    records.update(by_claim(w, NARROW), TODAY, short=None, topic=None)
    assert by_claim(w, NARROW).short is None
    assert auto(w)["asked"] == 0 and calls(w) == SESSION_PAIR
    records.update(by_claim(w, NARROW), TODAY, claim=NARROW + " It was seen twice.")
    answers(w, monkeypatch, shorts={NARROW + " It was seen twice.": SHORTS[NARROW]})
    assert auto(w)["asked"] == 1 and calls(w) == CALLS_TWO_RUNS
    assert m.handle in project_records(w.pa)


def test_a_claim_edited_during_the_run_gets_no_short_form_and_no_attempt(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    real = corroborate_run.run_session
    seen_sessions = []

    def edit_after_the_writer(cmd, work):
        done = real(cmd, work)
        if not seen_sessions:
            records.update(by_claim(w, NARROW), TODAY, claim=NARROW + " Edited meanwhile.")
        seen_sessions.append(cmd)
        return done

    monkeypatch.setattr(corroborate_run, "run_session", edit_after_the_writer)
    result = auto(w)
    assert (result["written"], result["left"]) == (0, 1)
    assert by_claim(w, NARROW + " Edited meanwhile.").short is None
    assert attempts(w)["lessons"] == {}


def test_an_index_only_lesson_keeps_its_load_and_a_turned_off_lesson_is_not_asked(w, monkeypatch):
    one_lesson(w)
    other = one_lesson(
        w, "Keep a failing command's output in a file, as it may help when it is long."
    )
    off = one_lesson(
        w, "Name a branch after its task, as it may help when one searches for it later."
    )
    records.update(by_claim(w, NARROW), TODAY, load="index")
    records.update(off, TODAY, load="no")
    shorts = {
        other.claim: "Keep a failing command's output in a file, as it may help.",
        off.claim: "Name a branch after its task, as it may help.",
    }
    answers(w, monkeypatch, shorts=shorts)
    result = auto(w)
    assert (result["asked"], result["written"]) == (2, 2)
    assert (by_claim(w, NARROW).load, by_claim(w, NARROW).short) == ("index", SHORTS[NARROW])
    assert (by_claim(w, off.claim).load, by_claim(w, off.claim).short) == ("no", None)


@pytest.mark.parametrize("bad", ["no file", "not json", '{"items": 3}'])
def test_an_unusable_writer_answer_counts_no_attempt_and_sends_nothing_to_triage(
    w, monkeypatch, bad
):
    g = fill_world(w)
    answers(w, monkeypatch, writer="none" if bad == "no file" else bad)
    result = auto(w)
    assert result["stopped"] and result["written"] == result["to_triage"] == 0 and calls(w) == 1
    state = attempts(w)
    assert state["lessons"] == {} and state["failures"]["count"] == 1
    assert [m.triage for m in globals_(w) if m.handle == g.handle] == [None]
    assert not fill_runs(w)


def test_an_unusable_checker_answer_counts_no_attempt_and_applies_nothing(w, monkeypatch):
    g = fill_world(w)
    for checker in ("none", '{"verdicts": 3}'):
        answers(w, monkeypatch, checker=checker)
        result = auto(w)
        assert result["stopped"] and result["written"] == result["to_triage"] == 0
    assert calls(w) == CALLS_TWO_RUNS
    state = attempts(w)
    assert state["lessons"] == {} and state["failures"]["count"] == SESSION_PAIR
    assert not any(
        m.short
        for m in [*project_records(w.pa).values(), *project_records(w.pb).values(), *globals_(w)]
    )
    assert [m.triage for m in globals_(w) if m.handle == g.handle] == [None] and not fill_runs(w)


def test_after_three_failed_sessions_no_session_starts_until_the_candidates_change(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, writer="none")
    for _ in range(3):
        assert auto(w)["stopped"]
    assert calls(w) == CALLS_THREE_FAILS
    waiting = auto(w)
    assert (
        calls(w) == CALLS_THREE_FAILS and waiting["stopped"] == "waiting for the lessons to change"
    )
    one_lesson(w, "Keep a failing command's output in a file, as it may help when it is long.")
    answers(w, monkeypatch, writer="none")
    assert auto(w)["stopped"] != "waiting for the lessons to change" and calls(w) == CALLS_TWO_RUNS


def test_a_good_run_between_failures_starts_the_count_of_failures_again(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, writer="none")
    assert auto(w)["stopped"]
    answers(w, monkeypatch, checker=False)
    assert auto(w)["stopped"] is None and attempts(w)["failures"]["count"] == 0
    answers(w, monkeypatch, writer="none")
    assert auto(w)["stopped"] and auto(w)["stopped"]
    before = calls(w)
    assert auto(w)["stopped"] != "waiting for the lessons to change" and calls(w) == before + 1


def test_the_run_folder_keeps_the_fill_marker_and_the_applied_handles(w, monkeypatch):
    m = one_lesson(w)
    answers(w, monkeypatch)
    assert auto(w)["written"] == 1
    (run_dir,) = fill_runs(w)
    assert (run_dir / "fill").exists() and (run_dir / "journal.jsonl").exists()
    assert json.loads((run_dir / "applied.json").read_text()) == [m.handle]


def test_fill_auto_with_the_lock_taken_writes_nothing(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    lock = jobs.take_run_lock(w.cdir)
    assert lock is not None
    try:
        result = auto(w)
    finally:
        os.close(lock)
    assert result["stopped"] == "a run is going" and result["written"] == 0 and calls(w) == 0
    assert (
        not (w.cdir / "fill-attempts.json").exists()
        and "fill" not in status(w)
        and by_claim(w, NARROW).short is None
    )


def test_two_fill_runs_in_the_same_second_keep_separate_run_folders(w, monkeypatch):
    pinned = one_lesson(w)
    monkeypatch.setattr(corroborate_fill.time, "strftime", lambda fmt: "20260101-000000")
    answers(w, monkeypatch)
    assert auto(w)["written"] == 1
    other = one_lesson(
        w, "Keep a failing command's output in a file, as it may help when it is long."
    )
    answers(
        w,
        monkeypatch,
        shorts={other.claim: "Keep a failing command's output in a file, as it may help."},
    )
    assert auto(w)["written"] == 1
    first, second = fill_runs(w)
    stamp = f"20260101-000000-{os.getpid()}"
    assert {first.name, second.name} == {f"{stamp}-fill", f"{stamp}-2-fill"}
    applied = {run.name: json.loads((run / "applied.json").read_text()) for run in (first, second)}
    assert sorted(h for handles in applied.values() for h in handles) == sorted([
        pinned.handle,
        other.handle,
    ])
    assert all(len(handles) == 1 for handles in applied.values())


def test_undo_of_an_automatic_fill_run_restores_the_records(w, monkeypatch):
    fill_world(w)
    answers(w, monkeypatch)
    before = snapshot(w)
    assert auto(w)["written"] == FILL_WORLD_LESSONS
    assert snapshot(w) != before
    (run_dir,) = fill_runs(w)
    assert run(w, run_dir.name, cmd="undo", claude=False).returncode == 0
    assert snapshot(w) == before and not (w.cdir / "seen.json").exists()


def test_auto_runs_the_fill_after_the_pass_and_logs_its_counts(w, monkeypatch):
    fill_world(w)
    model(w, [])
    answers(w, monkeypatch)
    done = run(w, cmd="auto", env={OPTION: "true"})
    assert done.returncode == 0 and not done.stdout and not done.stderr
    lines = log_lines(w)
    (filled,) = [x for x in lines if "fill" in x]
    assert (
        lines[-1] is filled
        and "lessons" in lines[0]
        and filled["fill"]["written"] > 0
        and filled["fill"]["stopped"] is None
    )
    assert isinstance(filled["ms"], int) and filled["t"]
    assert status(w)["fill"] == filled["fill"] and status(w)["state"] == "ok"


def test_auto_skips_the_fill_when_loaded_rules_is_off(w, monkeypatch):
    fill_world(w)
    model(w, [])
    answers(w, monkeypatch)
    for env in ({"MEM_LOADED_RULES": "off"}, {"CLAUDE_PLUGIN_OPTION_LOADED_RULES": "false"}):
        done = run(w, cmd="auto", env={OPTION: "true", **env})
        assert done.returncode == 0 and not done.stdout and not done.stderr
        assert not any("fill" in x for x in log_lines(w)) and "fill" not in status(w)
        assert not (w.cdir / "fill-attempts.json").exists()


def test_a_fill_that_raises_leaves_the_pass_result_seen_and_status_alone(w, monkeypatch):
    a, b = two_projects(w)
    model(w, [group(a, b)])

    def boom(*_args, **_kw):
        raise RuntimeError("the fill broke")

    monkeypatch.setattr(corroborate_fill, "fill_auto", boom)
    monkeypatch.setenv(OPTION, "true")
    kept = {}
    real = corroborate_run.execute

    def execute_then_look(*args, **kw):  # what the pass left, read before the fill runs
        out = real(*args, **kw)
        kept.update(
            seen=(w.cdir / "seen.json").read_bytes(), status=(w.cdir / "status.json").read_bytes()
        )
        return out

    monkeypatch.setattr(corroborate_run, "execute", execute_then_look)
    assert corroborate_cli.cmd_auto(argparse.Namespace(claude=str(w.fake))) == 0
    (line,) = log_lines(w)
    assert (
        "fill" not in line
        and line["failed"] is None
        and line["written"] == 1
        and len(globals_(w)) == 1
    )
    assert (w.cdir / "seen.json").read_bytes() == kept["seen"]
    assert (w.cdir / "status.json").read_bytes() == kept["status"]
    assert status(w)["state"] == "ok" and "fill" not in status(w) and "failure" not in status(w)


def test_status_shows_the_last_fill_and_its_failure(w, capsys):
    w.cdir.mkdir(parents=True)
    fill = {
        "asked": 5,
        "written": 2,
        "dropped": 0,
        "refused_code": 1,
        "refused_check": 1,
        "to_triage": 1,
        "left": 1,
        "cost": 0.1,
        "stopped": "over budget",
    }
    jobs.write_json(w.cdir / "status.json", {"state": "ok", "cost": 0.1, "fill": fill})
    assert corroborate_state.cmd_status() == 0
    out = capsys.readouterr().out
    assert "last fill: 2 written, 2 refused, 1 to triage, stopped: over budget\n" in out
    quiet = {**fill, "written": 0, "refused_code": 0, "refused_check": 0, "stopped": None}
    jobs.write_json(
        w.cdir / "status.json", {"state": "ok", "fill": quiet}
    )  # a run that only held a lesson
    assert corroborate_state.cmd_status() == 0
    assert "last fill: 0 written, 0 refused, 1 to triage\n" in capsys.readouterr().out
    jobs.write_json(w.cdir / "status.json", {"state": "ok", "fill": {**quiet, "to_triage": 0}})
    assert corroborate_state.cmd_status() == 0
    assert "last fill" not in capsys.readouterr().out


# ---- fill_auto: a step that fails, a load the owner changed, a partial check ----------------------------------------

OTHER = "Keep a failing command's output in a file, as it may help when it is long."
OTHER_SHORT = "Keep a failing command's output in a file, as it may help."
CODE_REFUSED = {
    NARROW: "Run the narrowest covering test before the whole suite."
}  # the hedge is gone: shortcheck refuses it


def count_of(w, claim):
    digest = hashlib.sha256(claim.encode()).hexdigest()
    return [v["count"] for v in attempts(w)["lessons"].values() if v["digest"] == digest]


def test_a_fill_that_raises_after_a_code_refusal_still_counts_the_attempt(w, monkeypatch):
    one_lesson(w)
    other = one_lesson(w, OTHER)
    answers(w, monkeypatch, shorts={**CODE_REFUSED, other.claim: OTHER_SHORT})

    def boom(*_args, **_kw):
        raise RuntimeError("apply broke")

    monkeypatch.setattr(corroborate_fill, "apply_fill", boom)
    for _ in range(2):
        assert auto(w)["stopped"] == "the apply failed"
    assert count_of(w, NARROW) == [2]
    assert count_of(w, OTHER) == [
        2
    ]  # it passed the checks but was not written: its apply did not complete


def _breaking_apply(w, monkeypatch):

    def boom(*_args, **_kw):
        raise RuntimeError("apply broke")

    monkeypatch.setattr(corroborate_fill, "apply_fill", boom)


def test_a_general_lesson_refused_by_code_in_two_runs_with_a_failing_apply_is_held_at_triage(
    w, monkeypatch
):
    g = fill_world(w)
    answers(
        w,
        monkeypatch,
        shorts={GCLAIM: "Always read the whole failing test output before changing code."},
    )
    _breaking_apply(w, monkeypatch)
    assert auto(w)["to_triage"] == 0
    second = auto(w)
    assert (second["stopped"], second["to_triage"]) == ("the apply failed", 1)
    (gl,) = [m for m in globals_(w) if m.handle == g.handle]
    assert (
        gl.triage == "pending"
        and gl.triage_reason == 'the short form says "always" and the claim does not'
    )


def test_a_failing_apply_three_times_in_a_row_makes_the_step_wait(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    _breaking_apply(w, monkeypatch)
    # two attempts per lesson end the asking sooner than three failures could, so the attempts are cleared between
    # runs: what is under test is the failure count on the same lessons
    for n in range(corroborate.FILL_FAILURES):
        assert auto(w)["stopped"] == "the apply failed"
        state = attempts(w)
        assert state["failures"]["count"] == n + 1
        jobs.write_json(w.cdir / "fill-attempts.json", {**state, "lessons": {}})
    before = calls(w)
    result = auto(w)
    assert result["stopped"] == "waiting for the lessons to change" and calls(w) == before


def test_an_item_that_passed_the_checks_before_a_failing_apply_has_one_attempt(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    _breaking_apply(w, monkeypatch)
    assert auto(w)["stopped"] == "the apply failed"
    assert count_of(w, NARROW) == [1]


def test_a_fill_that_raises_after_writing_marks_what_was_written_as_spent(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    real = corroborate_fill.apply_fill

    def write_then_break(*args, **kw):
        real(*args, **kw)
        raise RuntimeError("after the write")

    monkeypatch.setattr(corroborate_fill, "apply_fill", write_then_break)
    assert auto(w)["stopped"] == "the apply failed"
    assert by_claim(w, NARROW).short == SHORTS[NARROW]
    assert count_of(w, NARROW) == [corroborate.FILL_ATTEMPTS]
    records.update(by_claim(w, NARROW), TODAY, short=None, topic=None)  # the owner removes it
    assert auto(w)["asked"] == 0 and calls(w) == SESSION_PAIR


def test_the_automatic_fill_never_sets_load_and_a_record_turned_off_meanwhile_stays_so(
    w, monkeypatch
):
    one_lesson(w)
    answers(w, monkeypatch)
    real = corroborate_run.run_session
    sessions = []

    def turn_off_after_the_writer(cmd, work):
        done = real(cmd, work)
        if not sessions:
            records.update(by_claim(w, NARROW), TODAY, load="no")
        sessions.append(cmd)
        return done

    monkeypatch.setattr(corroborate_run, "run_session", turn_off_after_the_writer)
    result = auto(w)
    assert result["written"] == 0 and result["dropped"] == 1
    assert (by_claim(w, NARROW).load, by_claim(w, NARROW).short) == ("no", None)


def test_apply_fill_without_user_read_passes_no_load_flag(w, monkeypatch):
    m = one_lesson(w)
    seen_args = []
    real = corroborate_run.Applier.mem

    def spy(self, args, *rest, **kw):
        seen_args.append(args)
        return real(self, args, *rest, **kw)

    monkeypatch.setattr(corroborate_run.Applier, "mem", spy)
    (ident,) = candidate_ids(w)[NARROW]
    item = {
        "id": ident,
        "short": SHORTS[NARROW],
        "topic": "process",
        "load": "yes",
        "claim_digest": corroborate.claim_digest(m),
    }
    assert (
        corroborate_fill.apply_fill([item], w.cdir / "runs" / "direct-fill", user_read=False)[
            "written"
        ]
        == 1
    )
    (args,) = seen_args
    assert not {"--load", "--index-only", "--no-load"} & set(args)


def test_a_checker_that_answers_for_the_first_id_only_is_a_failed_session_twice(w, monkeypatch):
    g = fill_world(w)
    first = min(i for ids in candidate_ids(w).values() for i in ids)
    answers(
        w,
        monkeypatch,
        checker=json.dumps({"verdicts": [{"id": first, "reason": "r", "faithful": True}]}),
    )
    for _ in range(2):
        result = auto(w)
        assert result["stopped"] and result["written"] == result["to_triage"] == 0
    state = attempts(w)
    assert state["lessons"] == {} and state["failures"]["count"] == SESSION_PAIR
    assert [m.triage for m in globals_(w) if m.handle == g.handle] == [None]
    assert not any(
        m.short
        for m in [*project_records(w.pa).values(), *project_records(w.pb).values(), *globals_(w)]
    )


def test_a_missing_claude_binary_is_a_failed_session_not_an_exception(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    result = corroborate_fill.fill_auto("/nonexistent/claude", 0.25)
    assert result["stopped"] and result["written"] == 0
    assert attempts(w)["failures"]["count"] == 1 and attempts(w)["lessons"] == {}


def test_an_unreadable_registry_stops_the_fill_without_raising(w):
    (w.data / "projects.json").write_text("{not json")
    result = corroborate_fill.fill_auto(str(w.fake), 0.25)
    assert result["stopped"] and result["written"] == 0 and calls(w) == 0


def test_a_new_candidate_set_starts_the_count_of_failures_at_zero(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, writer="none")
    for _ in range(3):
        assert auto(w)["stopped"]
    one_lesson(w, OTHER)
    answers(w, monkeypatch, writer="none")
    assert auto(w)["stopped"] != "waiting for the lessons to change"
    assert attempts(w)["failures"]["count"] == 1
    before = calls(w)
    assert auto(w)["stopped"] != "waiting for the lessons to change" and calls(w) == before + 1


def test_the_attempts_file_is_private_and_a_failed_write_keeps_the_old_one(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, checker=False)
    auto(w)
    path = w.cdir / "fill-attempts.json"
    assert stat.S_IMODE(path.stat().st_mode) == PRIVATE_MODE
    before = path.read_text()

    def broken(*_args):
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        auto(w)
    assert path.read_text() == before


def test_a_lesson_whose_edit_mem_refused_gets_one_attempt(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    real = corroborate_run.Applier.mem

    def refuse_edits(self, args, *rest, **kw):
        if args[:2] == ["memory", "edit"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        return real(self, args, *rest, **kw)

    monkeypatch.setattr(corroborate_run.Applier, "mem", refuse_edits)
    result = auto(w)
    assert (result["written"], result["left"]) == (0, 1)
    assert count_of(w, NARROW) == [1]


def test_a_writer_item_with_a_problem_is_refused_counted_and_not_sent_to_the_checker(
    w, monkeypatch
):
    one_lesson(w)
    answers(w, monkeypatch, shorts={NARROW: "Run the narrowest covering test. " + "x" * 120})
    result = auto(w)
    assert (result["written"], result["refused_code"], result["refused_check"]) == (
        0,
        1,
        0,
    )  # the length rule is code
    assert calls(w) == 1 and count_of(w, NARROW) == [1] and by_claim(w, NARROW).short is None


def test_a_verdict_that_is_not_exactly_true_writes_nothing(w, monkeypatch):
    one_lesson(w)
    answers(
        w,
        monkeypatch,
        checker=json.dumps({
            "verdicts": [
                {"id": i, "reason": "r", "faithful": "yes"} for i in candidate_ids(w)[NARROW]
            ]
        }),
    )
    result = auto(w)
    assert (result["written"], result["refused_check"]) == (0, 1) and by_claim(
        w, NARROW
    ).short is None


def test_an_unusable_writer_answer_twice_sends_nothing_to_triage(w, monkeypatch):
    g = fill_world(w)
    answers(w, monkeypatch, writer="none")
    for _ in range(2):
        assert auto(w)["to_triage"] == 0
    assert [m.triage for m in globals_(w) if m.handle == g.handle] == [None] and attempts(w)[
        "lessons"
    ] == {}


def _records_only(w):
    # the settle state is a side file that a global write creates and an undo leaves
    return {k: v for k, v in snapshot(w).items() if Path(k).name != ".settle-state.json"}


def _with_log(w, project, claim, session, log):
    m = lesson(w, project, claim, (session,))
    return records.update(m, TODAY, log=log)


def test_the_pass_applies_cases_to_the_global_record(w):
    # a write_global with two sessions, then a sighting for a third on the record it made
    _with_log(w, w.pa, BRIEF, "s1", ["2026-11-20 session s1 failed"])
    _with_log(w, w.pb, BRIEF2, "s2", ["2026-11-21 session s2 worked"])
    a, b = ident(w, "Brief the subagent"), ident(w, "Give a subagent")
    model(w, [group(a, b)])
    before = _records_only(w)
    assert run(w).returncode == 0
    (g,) = globals_(w)
    assert sorted(records.sessions(g)) == ["session s1", "session s2"]
    assert sorted(g.log) == ["2026-11-20 session s1 failed", "2026-11-21 session s2 worked"]
    assert log_lines(w)[-1]["written"] == 1 and log_lines(w)[-1]["sightings"] == 0
    stamp = Path(status(w)["log"]).name
    assert run(w, stamp, cmd="undo", claude=False).returncode == 0
    assert _records_only(w) == before
    # a sighting: a global record exists and the project member of s2 brings its session with its case
    glob(w, BRIEF, ("s1",), project=w.pa)
    (gm,) = list(globals_(w))
    model(w, [group(f"g:{gm.handle}", ident(w, "Give a subagent"))])
    before = _records_only(w)
    assert run(w).returncode == 0
    (g,) = globals_(w)
    assert records.sessions(g).count("session s2") == 1 and g.log == [
        "2026-11-21 session s2 worked"
    ]
    assert log_lines(w)[-1]["sightings"] == 1 and log_lines(w)[-1]["cases"] == 1
    assert run(w, Path(status(w)["log"]).name, cmd="undo", claude=False).returncode == 0
    assert _records_only(w) == before


def _two_cases(w):
    return _with_log(
        w, w.pb, BRIEF2, "s2", ["2026-11-19 session s2 failed", "2026-11-21 session s2 worked"]
    )


def test_the_pass_repairs_a_half_applied_sighting(w):
    # the global record counts s2 already but has none of the member's cases
    _two_cases(w)
    gm = glob(w, BRIEF, ("s1", "s2"), project=w.pa)
    model(w, [group(f"g:{gm.handle}", ident(w, "Give a subagent"))])
    before = _records_only(w)
    assert run(w).returncode == 0
    (g,) = globals_(w)
    assert sorted(g.log) == ["2026-11-19 session s2 failed", "2026-11-21 session s2 worked"]
    line = log_lines(w)[-1]
    assert (line["sightings"], line["cases"]) == (0, 2)
    assert run(w, Path(status(w)["log"]).name, cmd="undo", claude=False).returncode == 0
    assert _records_only(w) == before


def test_a_failed_case_call_still_counts_the_sighting(w):
    _two_cases(w)
    gm = glob(w, BRIEF, ("s1",), project=w.pa)
    model(w, [group(f"g:{gm.handle}", ident(w, "Give a subagent"))])
    n = w.tmp / "confirms"
    broken = fake_plugin(
        w,
        f'if [ "$1" = confirm ]; then echo x >> {n}; '
        f'if [ "$(wc -l < {n})" = 2 ]; then echo boom >&2; exit 2; fi; fi',
    )
    assert run(w, corr=broken).returncode == 0
    line = log_lines(w)[-1]
    assert (line["sightings"], line["failed_actions"]) == (1, 1)


def test_a_failed_case_call_after_a_global_write_still_counts_the_write(w):
    _with_log(w, w.pa, BRIEF, "s1", ["2026-11-20 session s1 failed"])
    _with_log(w, w.pb, BRIEF2, "s2", ["2026-11-21 session s2 worked"])
    model(w, [group(ident(w, "Brief the subagent"), ident(w, "Give a subagent"))])
    broken = fake_plugin(w, 'if [ "$1" = confirm ]; then echo boom >&2; exit 2; fi')
    assert run(w, corr=broken).returncode == 0
    line = log_lines(w)[-1]
    assert len(globals_(w)) == 1  # the record exists
    assert (line["written"], line["failed_actions"]) == (1, 1)
