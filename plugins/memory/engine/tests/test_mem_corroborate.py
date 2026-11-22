"""`bin/mem-corroborate`: the pass that matches lessons by meaning, with a fake `claude` and invented lessons."""
import datetime
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import auto_state
import capture_state
import corroborate
import records

PLUGIN = Path(__file__).resolve().parents[2]
CORR = PLUGIN / "bin" / "mem-corroborate"
MEM = PLUGIN / "bin" / "mem"
TODAY = datetime.date.today()
OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_CAPTURE"

FAKE = """#!/usr/bin/env python3
import json, os, re, shutil, sys
mode = os.environ.get("FAKE_MODE", "good")
if mode == "never":
    sys.exit("the fake must not be called")
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "files": sorted(os.listdir(".")),
                        "mem_vars": sorted(k for k in os.environ if k.startswith(("MEM_", "CLAUDE_PLUGIN"))),
                        "path": os.environ.get("PATH", "")}) + "\\n")
brief = sys.argv[sys.argv.index("-p") + 1]
out = re.search(r"Write (\\S+) as JSON", brief).group(1)
src = os.environ.get("FAKE_VERDICTS" if out.endswith("verdicts.json") else "FAKE_FILL" if out.endswith("fill.json") else "FAKE_GROUPS")
if mode == "exit1":
    sys.exit(1)
if src and os.path.exists(src):
    shutil.copy(src, out)
print(json.dumps({"type": "result", "is_error": False, "result": "done", "total_cost_usd": 0.03}))
"""

BRIEF = "Brief the subagent with the acceptance check before it starts, so it can tell when it is done."
BRIEF2 = "Give a subagent the acceptance check first: with it the subagent can tell by itself when it is done."


@pytest.fixture
def w(tmp_path, monkeypatch):
    class World:
        pass

    w = World()
    w.tmp = tmp_path
    w.fake = tmp_path / "fake-claude"
    w.fake.write_text(FAKE)
    w.fake.chmod(0o755)
    w.calls_file = tmp_path / "calls"
    w.gmem = tmp_path / "gmem"
    w.gmem.mkdir()
    w.data = Path(os.environ["MEM_DATA"])
    w.cdir = w.data / "corroborate"
    w.pa, w.pb = tmp_path / "alpha-p-a", tmp_path / "beta-p-b"
    for p in (w.pa, w.pb):
        records.project_dir(p).mkdir(parents=True)
    w.data.mkdir(parents=True)
    (w.data / "projects.json").write_text(json.dumps(
        {p.name: {"path": str(p), "seen": TODAY.isoformat()} for p in (w.pa, w.pb)}))
    monkeypatch.setenv("MEM_COUNT_TEMP_PROJECTS", "1")
    monkeypatch.setenv("MEM_MEMORIES", str(w.gmem))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FAKE_CALLS", str(w.calls_file))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.delenv(OPTION, raising=False)
    (tmp_path / "tmp").mkdir()
    return w


def lesson(w, project, claim, sessions=("s1",), created=TODAY, weight="light", scope="project"):
    folder = records.project_dir(project) if scope == "project" else w.gmem
    sources = [f"session {s}" if scope == "project" else f"session {s} project {records.project_key(project)}"
               for s in sessions]
    return records.write_memory(folder, scope, kind="lesson", claim=claim, body="b\n", today=created, sources=sources,
                                origin="transcript", reach="general", weight=weight)


def glob(w, claim, sessions, project=None, created=TODAY):
    return lesson(w, project or w.pa, claim, sessions, created, scope="global")


def lessons(w):
    registry = records.read_registry(w.data)
    return corroborate.collect(corroborate.counted_projects(registry), w.gmem, TODAY)


def ident(w, snippet):
    found = [x.id for x in lessons(w) if snippet in x.memory.claim]
    assert len(found) == 1, (snippet, found)
    return found[0]


def group(*ids, claim="Hand a subagent the check that tells it the task is done before it starts, and see whether it helps.",
          context="when briefing a subagent"):
    return {"ids": list(ids), "claim": claim, "context": context}


def verdict(n, **override):
    return {"group": n, "reason": "both ask for the same", "same": True, "faithful": True, "general": True, **override}


def model(w, groups, verdicts="all"):
    """The fake writes these files as the model's answers; `verdicts` "all" approves every group, None writes none."""
    (w.tmp / "groups.json").write_text(groups if isinstance(groups, str) else json.dumps({"groups": groups}))
    os.environ["FAKE_GROUPS"] = str(w.tmp / "groups.json")
    if verdicts is None:
        os.environ.pop("FAKE_VERDICTS", None)
        return
    if verdicts == "all":
        verdicts = [verdict(n) for n in range(1, len(groups) + 1)]
    (w.tmp / "verdicts.json").write_text(verdicts if isinstance(verdicts, str) else json.dumps({"verdicts": verdicts}))
    os.environ["FAKE_VERDICTS"] = str(w.tmp / "verdicts.json")


def run(w, *args, mode="good", cmd="run", env=None, claude=True, corr=None):
    full = {k: v for k, v in os.environ.items() if k != "MEM_PROJECT"}
    full["FAKE_MODE"] = mode
    full.update(env or {})
    argv = [str(corr or CORR), cmd, *(["--claude", str(w.fake)] if claude else []), *args]
    return subprocess.run(argv, env=full, capture_output=True, text=True, timeout=300)


def status(w):
    return auto_state.read_json(w.cdir / "status.json")


def log_lines(w):
    path = w.cdir / "log.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def calls(w):
    return len(w.calls_file.read_text().splitlines()) if w.calls_file.exists() else 0


def globals_(w):
    return [m for m in records.load_memories(w.gmem, "global") if m.status == "active"]


def project_records(project):
    return {m.handle: m for m in records.load_memories(records.project_dir(project), "project")}


def snapshot(w):
    out = {}
    for folder in (w.gmem, records.project_dir(w.pa), records.project_dir(w.pb)):
        for p in folder.iterdir():
            if p.is_file():
                out[str(p)] = p.read_bytes()
    return out


def two_projects(w):
    lesson(w, w.pa, BRIEF, ("s1",))
    lesson(w, w.pb, BRIEF2, ("s2",))
    return ident(w, "Brief the subagent"), ident(w, "Give a subagent")


def test_two_projects_make_one_established_global_record(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    done = run(w)
    assert done.returncode == 0, done.stderr
    (g,) = globals_(w)
    assert g.claim.startswith("Hand a subagent the check")
    assert sorted(g.sources) == sorted([f"session s1 project {records.project_key(w.pa)}",
                                         f"session s2 project {records.project_key(w.pb)}"])
    assert records.standing(g) == "established" and g.triage == "pending"
    for project in (w.pa, w.pb):
        (m,) = project_records(project).values()
        assert m.promote == "done" and m.general == g.handle
    assert status(w)["state"] == "ok"
    line = log_lines(w)[-1]
    assert (line["written"], line["links"], line["verified"], line["failed"]) == (1, 2, 1, None)
    assert calls(w) == 2


def test_one_project_makes_a_quarantined_record(w):
    lesson(w, w.pa, BRIEF, ("s1",))
    a = ident(w, "Brief the subagent")
    model(w, [group(a)])
    assert run(w).returncode == 0
    (g,) = globals_(w)
    assert records.standing(g) == "unconfirmed" and records.quarantined(g)
    assert g.body.strip() == "Written by the corroboration pass; its sightings are the sessions and projects in `sources`."
    found = subprocess.run([str(MEM), "search", "acceptance"], capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "MEM_PROJECT"}, cwd=w.tmp)
    assert g.handle not in found.stdout


def test_rerun_after_a_stop_joins_the_record(w):
    g = glob(w, "Hand a subagent the check that tells it the task is done before it starts.", ("s1",))
    lesson(w, w.pa, BRIEF, ("s1",))
    lesson(w, w.pb, BRIEF2, ("s2",))
    model(w, [group(f"g:{g.handle}", ident(w, "Brief the subagent"), ident(w, "Give a subagent"))])
    assert run(w).returncode == 0
    (only,) = globals_(w)
    assert only.handle == g.handle and len(records.projects(only)) == 2
    for project in (w.pa, w.pb):
        (m,) = project_records(project).values()
        assert m.general == g.handle and m.promote == "done"
    assert log_lines(w)[-1]["written"] == 0


def test_two_global_records_of_one_lesson_are_merged(w):
    old = glob(w, "Hand a subagent the check that tells it the task is done before it starts.", ("s1",),
               created=TODAY - datetime.timedelta(days=3))
    new = glob(w, "Give a subagent the check that tells it the task is done before it starts.", ("s2",), project=w.pb)
    model(w, [group(f"g:{old.handle}", f"g:{new.handle}")])
    assert run(w).returncode == 0
    kept = {m.handle: m for m in records.load_memories(w.gmem, "global")}
    assert kept[new.handle].status == "superseded" and kept[old.handle].status == "active"
    assert {"session s1", "session s2"} <= set(records.sessions(kept[old.handle]))
    assert log_lines(w)[-1]["merges"] == 1


def test_nothing_new_starts_no_model(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    assert run(w).returncode == 0
    before = calls(w)
    again = run(w, mode="never")
    assert again.returncode == 0 and calls(w) == before
    assert log_lines(w)[-1]["skipped"] == "nothing new"


def test_bad_model_file_writes_nothing(w):
    two_projects(w)
    model(w, "this is not json", verdicts=None)
    before = snapshot(w)
    assert run(w).returncode == 0
    assert status(w)["state"] == "ok" and log_lines(w)[-1]["dropped"] > 0
    assert snapshot(w) == before and calls(w) == 1


def test_unverified_group_is_not_applied(w):
    a, b = two_projects(w)
    model(w, [group(a, b)], [verdict(1, same=False)])
    before = snapshot(w)
    assert run(w).returncode == 0
    assert snapshot(w) == before
    seen = json.loads((w.cdir / "seen.json").read_text())
    assert len(seen["refused"]) == 2
    assert log_lines(w)[-1]["verified"] == 0


def test_a_group_refused_only_for_its_rewording_is_not_applied_and_not_marked(w):
    a, b = two_projects(w)
    model(w, [group(a, b)], [verdict(1, faithful=False)])
    before = snapshot(w)
    assert run(w).returncode == 0
    assert snapshot(w) == before
    assert not json.loads((w.cdir / "seen.json").read_text()).get("refused")  # the next run rewords it again
    assert log_lines(w)[-1]["verified"] == 0


@pytest.mark.parametrize("verdicts", [None, "garbage"])
def test_missing_verdicts_apply_nothing(w, verdicts):
    a, b = two_projects(w)
    model(w, [group(a, b)], verdicts)
    before = snapshot(w)
    assert run(w).returncode == 0
    assert snapshot(w) == before and calls(w) == 2
    assert log_lines(w)[-1]["verified"] == 0


def test_existing_global_claim_is_never_rewritten(w):
    g = glob(w, "Hand a subagent the check that tells it the task is done before it starts.", ("s1",))
    lesson(w, w.pb, BRIEF2, ("s2",))
    model(w, [group(f"g:{g.handle}", ident(w, "Give a subagent"), claim="A completely different wording of it all.")])
    assert run(w).returncode == 0
    (after,) = globals_(w)
    assert after.claim == g.claim and "different wording" not in after.path.read_text()


def test_forbidden_term_refuses_the_group_once(w):
    terms = w.tmp / "mem-config" / "agent-memory" / "forbidden-terms"
    terms.parent.mkdir(parents=True)
    terms.write_text("zebra\n")
    a, b = two_projects(w)
    model(w, [group(a, b, claim="Hand a subagent the check first, as the zebra team found.")])
    assert run(w).returncode == 0
    line = log_lines(w)[-1]
    assert line["refused"] == 1 and line["links"] == 0 and status(w)["state"] == "ok"
    assert globals_(w) == []
    for project in (w.pa, w.pb):
        assert not any(m.general for m in project_records(project).values())
    again = run(w, mode="never")
    assert again.returncode == 0 and log_lines(w)[-1]["skipped"] == "nothing new"


def test_same_project_duplicates_are_merged(w):
    older = lesson(w, w.pa, BRIEF, ("s1",), created=TODAY - datetime.timedelta(days=2))
    newer = lesson(w, w.pa, BRIEF2, ("s2",))
    model(w, [group(ident(w, "Brief the subagent"), ident(w, "Give a subagent"))])
    assert run(w).returncode == 0
    found = project_records(w.pa)
    assert found[newer.handle].status == "superseded" and found[older.handle].status == "active"
    assert {"session s1", "session s2"} <= set(records.sessions(found[older.handle]))
    assert log_lines(w)[-1]["merges"] == 1


def test_refused_merge_is_counted_not_forced(w):
    one = lesson(w, w.pa, "Run the whole suite 2 times before a release to catch flaky tests.", ("s1",),
                 created=TODAY - datetime.timedelta(days=1))
    two = lesson(w, w.pa, "Run the whole suite 3 times before a release to catch flaky tests.", ("s2",))
    model(w, [group(ident(w, "suite 2 times"), ident(w, "suite 3 times"))])
    assert run(w).returncode == 0
    line = log_lines(w)[-1]
    assert line["merges"] == 0 and line["refused"] == 1
    found = project_records(w.pa)
    assert found[one.handle].status == found[two.handle].status == "active"
    assert globals_(w) == [] and len(json.loads((w.cdir / "seen.json").read_text())["refused"]) == 2


def full_run(w):
    """A run with a write, a sighting, a link and a merge."""
    g = glob(w, "Hand a subagent the check that tells it the task is done before it starts.", ("s1",), project=w.pb)
    lesson(w, w.pb, BRIEF2, ("s2",))
    lesson(w, w.pa, "Read the failing test output to the end before changing code, because the cause is often in the last lines.",
           ("s3",), created=TODAY - datetime.timedelta(days=1))
    lesson(w, w.pa, "Read the test output to the end before you change code: the last lines often hold the cause.", ("s4",))
    first = group(f"g:{g.handle}", ident(w, "Give a subagent"))
    second = group(ident(w, "Read the failing test"), ident(w, "Read the test output"),
                   claim="Read a failing test's whole output before changing code; the cause may be in its last lines.")
    model(w, [first, second])
    before = snapshot(w)
    assert run(w).returncode == 0
    return before, g


def test_undo_restores_every_file(w):
    before, _ = full_run(w)
    line = log_lines(w)[-1]
    assert (line["written"], line["sightings"], line["links"], line["merges"]) == (1, 1, 2, 1)
    assert snapshot(w) != before
    stamp = Path(status(w)["log"]).name
    done = run(w, stamp, cmd="undo", claude=False)
    assert done.returncode == 0, done.stderr
    assert snapshot(w) == before


def test_undo_refuses_when_a_file_changed(w):
    full_run(w)
    after = snapshot(w)
    edited = next(m for m in globals_(w) if "Read a failing" in m.claim)
    edited.path.write_text(edited.path.read_text() + "\nedited by the owner\n")
    after[str(edited.path)] = edited.path.read_bytes()
    done = run(w, Path(status(w)["log"]).name, cmd="undo", claude=False)
    assert done.returncode == 1 and edited.path.name in done.stderr
    assert snapshot(w) == after


def test_groups_file_starts_no_model(w):
    a, b = two_projects(w)
    reviewed = w.tmp / "reviewed.json"
    reviewed.write_text(json.dumps({"groups": [group(a, b)]}))
    done = run(w, "--groups", str(reviewed), mode="never")
    assert done.returncode == 0, done.stderr
    assert len(globals_(w)) == 1 and calls(w) == 0


def test_dry_run_writes_only_the_out_file(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    before = snapshot(w)
    out = w.tmp / "plan.json"
    done = run(w, "--dry-run", "--out", str(out))
    assert done.returncode == 0, done.stderr
    plan = json.loads(out.read_text())
    assert plan["plan"][0]["actions"][0]["kind"] == "write_global" and plan["verdicts"]["verdicts"]
    assert snapshot(w) == before and calls(w) == 2 and not w.cdir.exists()


def test_auto_does_nothing_without_the_option(w):
    two_projects(w)
    done = run(w, cmd="auto")
    assert done.returncode == 0 and done.stdout == "" and done.stderr == "" and not w.cdir.exists()
    a, b = ident(w, "Brief the subagent"), ident(w, "Give a subagent")
    model(w, [group(a, b)])
    done = run(w, cmd="auto", env={OPTION: "true"})
    assert done.returncode == 0 and done.stdout == "" and done.stderr == "" and len(globals_(w)) == 1


def test_lock_held_skips(w):
    two_projects(w)
    held = auto_state.take_run_lock(w.cdir)
    try:
        done = run(w, mode="never")
    finally:
        os.close(held)
    assert done.returncode == 0 and "lock" in log_lines(w)[-1]["skipped"] and calls(w) == 0


def test_model_failure_leaves_a_failure_line_until_ack(w):
    two_projects(w)
    done = run(w, mode="exit1")
    assert done.returncode == 1
    assert status(w)["state"] == "failed" and auto_state.failure(status(w), 0)
    assert "fingerprint" not in auto_state.read_json(w.cdir / "seen.json")
    assert run(w, cmd="ack", claude=False).returncode == 0
    assert auto_state.failure(status(w), 0) is None


def test_no_project_name_or_path_in_log_and_lessons_file(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    assert run(w).returncode == 0
    run_dir = Path(status(w)["log"])
    texts = [(w.cdir / "log.jsonl").read_text(), (run_dir / "lessons.txt").read_text(),
             (run_dir / "verify" / "groups.txt").read_text()]
    for text in texts:
        assert "alpha" not in text and "beta" not in text and str(w.tmp) not in text
    assert oct(run_dir.stat().st_mode & 0o777) == "0o700"


def test_promote_done_to_names_an_existing_global_record(w):
    m = lesson(w, w.pa, BRIEF, ("s1",))
    g = glob(w, "Hand a subagent the check that tells it the task is done before it starts.", ("s1",))
    env = {**os.environ, "MEM_PROJECT": str(w.pa)}
    bad = subprocess.run([str(MEM), "promote", "--done", f"m:{m.handle}", "--to", "m:nope"], env=env,
                         capture_output=True, text=True)
    assert bad.returncode == 2 and project_records(w.pa)[m.handle].general is None
    good = subprocess.run([str(MEM), "promote", "--done", f"m:{m.handle}", "--to", f"m:{g.handle}"], env=env,
                          capture_output=True, text=True)
    assert good.returncode == 0 and project_records(w.pa)[m.handle].general == g.handle


# ---- fix round: failures against refusals, silent non-work, repeatable undo, process ----------------------------

def fake_plugin(w, shell):
    """A copy of the command beside a `mem` wrapper: `shell` runs first, then the real `mem` (REAL is its path)."""
    plug = w.tmp / "plug"
    (plug / "bin").mkdir(parents=True)
    shutil.copy(CORR, plug / "bin" / "mem-corroborate")
    (plug / "engine").symlink_to(PLUGIN / "engine")
    mem = plug / "bin" / "mem"
    mem.write_text("#!/bin/sh\n" + shell.replace("REAL", str(MEM)) + f'\nexec {MEM} "$@"\n')
    for f in (mem, plug / "bin" / "mem-corroborate"):
        f.chmod(0o755)
    return plug / "bin" / "mem-corroborate"


def seen(w):
    return auto_state.read_json(w.cdir / "seen.json")


def key_of(x):
    return f"{records.project_key(x.project)}:{x.memory.handle}" if x.project is not None else f"g:{x.memory.handle}"


def test_a_failing_mem_call_is_a_failure_not_a_refusal(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    flag = w.tmp / "flag"
    broken = fake_plugin(w, f'if [ "$1" = promote ] && [ ! -e {flag} ]; then touch {flag}; echo boom >&2; exit 2; fi')
    assert run(w, corr=broken).returncode == 0
    line = log_lines(w)[-1]
    assert (line["written"], line["links"], line["refused"], line["failed_actions"]) == (1, 0, 0, 1)
    assert "fingerprint" not in seen(w) and not seen(w).get("refused")
    assert run(w).returncode == 0
    line = log_lines(w)[-1]
    assert line["links"] == 2 and line["failed_actions"] == 0 and calls(w) == 4
    for project in (w.pa, w.pb):
        (m,) = project_records(project).values()
        assert m.promote == "done"


@pytest.mark.parametrize("missing", ["groups", "verdicts"])
def test_a_session_that_leaves_no_file_saves_no_fingerprint(w, missing):
    a, b = two_projects(w)
    model(w, [group(a, b)], None if missing == "verdicts" else "all")
    if missing == "groups":
        os.environ.pop("FAKE_GROUPS")
    assert run(w).returncode == 0
    assert status(w)["state"] == "ok" and log_lines(w)[-1]["dropped"] > 0
    assert "fingerprint" not in seen(w) and not seen(w).get("refused")
    first = calls(w)
    model(w, [group(a, b)])
    assert run(w).returncode == 0 and calls(w) > first and len(globals_(w)) == 1


def merged_then_refused(w):
    """Two duplicates of one project and one of another: the merge is applied, then the write is refused."""
    terms = w.tmp / "mem-config" / "agent-memory" / "forbidden-terms"
    terms.parent.mkdir(parents=True, exist_ok=True)
    terms.write_text("zebra\n")
    lesson(w, w.pa, BRIEF, ("s1",), created=TODAY - datetime.timedelta(days=2))
    lesson(w, w.pa, BRIEF2, ("s2",))
    lesson(w, w.pb, "Hand over the acceptance check before the subagent starts, so it knows when it is done.", ("s3",))
    ids = [ident(w, "Brief the subagent"), ident(w, "Give a subagent"), ident(w, "Hand over the acceptance")]
    model(w, [group(*ids, claim="Hand a subagent the check first, as the zebra team found.")])
    before = snapshot(w)
    assert run(w).returncode == 0
    return before, terms


def test_marks_use_the_fingerprint_after_the_runs_own_writes(w):
    merged_then_refused(w)
    assert log_lines(w)[-1]["merges"] == 1 and log_lines(w)[-1]["refused"] == 1
    marks = seen(w)["refused"]
    live = {key_of(x): corroborate.lesson_fingerprint(x) for x in lessons(w)}
    assert marks and all(live.get(k) == v for k, v in marks.items())
    assert len(marks) == len(live)


def test_a_refused_group_is_not_applied_again_until_a_lesson_changes(w):
    terms = w.tmp / "mem-config" / "agent-memory" / "forbidden-terms"
    terms.parent.mkdir(parents=True)
    terms.write_text("zebra\n")
    a, b = two_projects(w)
    model(w, [group(a, b, claim="Hand a subagent the check first, as the zebra team found.")])
    assert run(w).returncode == 0 and log_lines(w)[-1]["refused"] == 1
    terms.unlink()
    lesson(w, w.pa, "Read the failing test output to the end before changing code, because the cause is often there.")
    a, b = ident(w, "Brief the subagent"), ident(w, "Give a subagent")
    model(w, [group(a, b)])
    first = calls(w)
    assert run(w).returncode == 0
    line = log_lines(w)[-1]
    assert calls(w) == first + 1 and line["skipped"] is None and (line["written"], line["refused"]) == (0, 0)
    assert globals_(w) == []
    env = {**os.environ, "MEM_PROJECT": str(w.pa)}
    handle = ident(w, "Brief the subagent").split(":")[-1]
    done = subprocess.run([str(MEM), "confirm", f"m:{handle}", "--source=session s9"], env=env, capture_output=True,
                          text=True, cwd=w.tmp)
    assert done.returncode == 0, done.stderr
    assert run(w).returncode == 0 and len(globals_(w)) == 1


def test_undo_can_be_repeated_after_an_interruption(w):
    before, _ = full_run(w)
    stamp = Path(status(w)["log"]).name
    w.gmem.chmod(0o500)
    try:
        broken = run(w, stamp, cmd="undo", claude=False)
    finally:
        w.gmem.chmod(0o700)
    assert broken.returncode == 1 and ".md" in broken.stderr and snapshot(w) != before
    done = run(w, stamp, cmd="undo", claude=False)
    assert done.returncode == 0, done.stderr
    assert snapshot(w) == before
    again = run(w, stamp, cmd="undo", claude=False)
    assert again.returncode == 0 and "already undone" in again.stdout


def test_undo_restores_the_curation_log_too(w):
    seeded = records.project_dir(w.pa) / records.CURATION_LOG
    seeded.write_text(json.dumps({"t": "2020-01-01T00:00:00Z", "action": "x", "handle": "none", "before": ""}) + "\n")
    before, _ = full_run(w)
    logs = [p for p in list(records.project_dir(w.pa).glob(".curation-log")) + list(w.gmem.glob(".curation-log"))]
    assert seeded.read_bytes() != before[str(seeded)]
    done = run(w, Path(status(w)["log"]).name, cmd="undo", claude=False)
    assert done.returncode == 0, done.stderr
    assert snapshot(w) == before and logs


def test_undo_clears_the_fingerprint_and_the_marks_of_the_run(w):
    before, _ = merged_then_refused(w)
    assert "fingerprint" in seen(w) and seen(w)["refused"]
    assert run(w, Path(status(w)["log"]).name, cmd="undo", claude=False).returncode == 0
    assert snapshot(w) == before
    assert "fingerprint" not in seen(w) and not seen(w).get("refused")
    first = calls(w)
    assert run(w).returncode == 0 and calls(w) > first


def test_restored_files_are_private(w):
    full_run(w)
    for p in list(records.project_dir(w.pa).glob("*.md")) + list(records.project_dir(w.pb).glob("*.md")):
        p.chmod(0o644)
    before = {p: p.read_bytes() for p in records.project_dir(w.pa).glob("*.md")}
    done = run(w, Path(status(w)["log"]).name, cmd="undo", claude=False)
    assert done.returncode == 0, done.stderr
    for p in records.project_dir(w.pa).glob("*.md"):
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def runs_of(w):
    return sorted(p.name for p in (w.cdir / "runs").iterdir()) if (w.cdir / "runs").exists() else []


def test_a_run_that_skips_leaves_no_run_folder(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    env = {OPTION: "true"}
    assert run(w, cmd="auto", env=env).returncode == 0
    assert len(runs_of(w)) == 1
    for _ in range(3):
        assert run(w, cmd="auto", env=env, mode="never").returncode == 0
    held = auto_state.take_run_lock(w.cdir)
    try:
        lesson(w, w.pa, "Read the failing test output to the end before changing code, because the cause is often there.")
        assert run(w, mode="never").returncode == 0
    finally:
        os.close(held)
    assert len(runs_of(w)) == 1


def test_old_run_folders_are_pruned_after_a_failure(w):
    two_projects(w)
    runs = w.cdir / "runs"
    runs.mkdir(parents=True)
    for i in range(capture_state.KEEP_RUNS + 5):
        d = runs / f"old-{i:02d}"
        d.mkdir()
        os.utime(d, (1_700_000_000 + i, 1_700_000_000 + i))
    capture_state_now = __import__("time").time()
    for d in runs.iterdir():
        os.utime(d, (capture_state_now - 3600 - int(d.name[4:]) * 60,) * 2)
    assert run(w, mode="exit1").returncode == 1
    assert len(runs_of(w)) == capture_state.KEEP_RUNS


def test_a_failure_stays_until_ack(w):
    a, b = two_projects(w)
    assert run(w, mode="exit1").returncode == 1
    assert auto_state.failure(status(w), 0)
    model(w, [group(a, b)])
    assert run(w).returncode == 0 and status(w)["state"] == "ok"
    assert auto_state.failure(status(w), 0)
    assert run(w, cmd="ack", claude=False).returncode == 0
    assert auto_state.failure(status(w), 0) is None


def test_the_session_has_only_read_and_write_and_no_mem(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    path = f"{PLUGIN / 'bin'}:{os.environ['PATH']}"
    assert run(w, env={"PATH": path, "CLAUDE_PLUGIN_ROOT": str(PLUGIN)}).returncode == 0
    for row in map(json.loads, w.calls_file.read_text().splitlines()):
        argv = row["args"]
        assert argv[argv.index("--tools") + 1] == "Read,Write" and "--strict-mcp-config" in argv
        assert row["mem_vars"] == [] and str(PLUGIN / "bin") not in row["path"].split(os.pathsep)


def test_dry_run_out_inside_a_repository_is_refused(w):
    two_projects(w)
    repo = w.tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    done = run(w, "--dry-run", "--out", str(repo / "plan.json"), mode="never")
    assert done.returncode == 2 and "repository" in done.stderr and not (repo / "plan.json").exists()
    assert calls(w) == 0


def test_dry_run_out_is_private_even_when_it_exists(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    out = w.tmp / "plan.json"
    out.write_text("old")
    out.chmod(0o644)
    assert run(w, "--dry-run", "--out", str(out)).returncode == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o600 and "plan" in json.loads(out.read_text())


def test_the_log_line_holds_a_fixed_reason_only(w):
    two_projects(w)
    assert run(w, mode="exit1").returncode == 1
    assert log_lines(w)[-1]["failed"] == "session error"
    (w.data / "projects.json").write_text("{not json /secret/path")
    assert run(w, mode="exit1").returncode == 1
    assert log_lines(w)[-1]["failed"] == "registry unreadable"
    assert "secret" not in (w.cdir / "log.jsonl").read_text()
    assert "registry" in (Path(status(w)["log"]) / "log.txt").read_text()


def test_undecodable_mem_output_is_not_a_failure(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    noisy = fake_plugin(w, r'if [ "$1" = promote ]; then printf "\377\376 bad"; fi')
    assert run(w, corr=noisy).returncode == 0
    line = log_lines(w)[-1]
    assert (line["links"], line["failed_actions"], line["failed"]) == (2, 0, None)


# ---- second fix round: error text stays private, bounded retries, groups without a verdict -------------------------

def test_the_status_keeps_a_fixed_reason_and_the_detail_stays_in_the_run_log(w):
    two_projects(w)
    data = w.tmp / "quokka-data"
    (data / "projects.json").mkdir(parents=True)   # unreadable: the OSError names this path
    assert run(w, env={"MEM_DATA": str(data)}).returncode == 1
    cdir = data / "corroborate"
    failure = auto_state.read_json(cdir / "status.json")["failure"]
    assert failure["reason"] == "registry unreadable"
    assert "quokka" not in (cdir / "status.json").read_text().replace(failure["log"], "")
    assert "quokka" not in (cdir / "log.jsonl").read_text()
    assert "quokka" in (Path(failure["log"]) / "log.txt").read_text()


def always_failing_promote(w):
    return fake_plugin(w, 'if [ "$1" = promote ]; then echo boom >&2; exit 2; fi')


def test_repeated_failures_give_up_until_a_lesson_changes(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    broken = always_failing_promote(w)
    assert run(w, corr=broken).returncode == 0 and calls(w) == 2
    assert seen(w)["retry"]["count"] == 1 and "fingerprint" not in seen(w)
    assert run(w, corr=broken).returncode == 1 and calls(w) == 4
    assert status(w)["failure"]["reason"] == "gave up after repeated failures"
    assert log_lines(w)[-1]["failed"] == "gave up after repeated failures"
    assert "fingerprint" in seen(w) and "retry" not in seen(w)
    assert run(w, mode="never", corr=broken).returncode == 0 and calls(w) == 4
    assert log_lines(w)[-1]["skipped"] == "nothing new"
    lesson(w, w.pa, BRIEF, ("s1", "s3"))   # a new sighting changes the lesson
    assert run(w, corr=broken).returncode == 0 and calls(w) == 6


def test_a_clean_run_or_other_lessons_clear_the_retry(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    assert run(w, corr=always_failing_promote(w)).returncode == 0
    assert seen(w)["retry"]["count"] == 1
    assert run(w).returncode == 0
    assert "retry" not in seen(w) and "fingerprint" in seen(w)


def test_a_group_without_a_verdict_makes_the_run_incomplete(w):
    a, b = two_projects(w)
    lesson(w, w.pa, "Read the failing test output to the end before changing code, because the cause is often there.")
    lesson(w, w.pb, "Read the whole failing test output before you change any code, since the cause is often there.",
               ("s2",))
    model(w, [group(a, b), group(ident(w, "Read the failing"), ident(w, "Read the whole"), claim="Read the whole failing test output before changing code.")],
          [verdict(1)])
    assert run(w).returncode == 0
    assert "fingerprint" not in seen(w) and seen(w)["retry"]["count"] == 1
    first = calls(w)
    assert run(w).returncode == 0 and calls(w) == first + 2


def test_old_run_folders_are_pruned_when_a_run_skips(w):
    a, b = two_projects(w)
    model(w, [group(a, b)])
    assert run(w).returncode == 0
    runs = w.cdir / "runs"
    old = __import__("time").time() - 3600
    for i in range(capture_state.KEEP_RUNS + 5):
        d = runs / f"old-{i:02d}"
        d.mkdir()
        os.utime(d, (old - i * 60,) * 2)
    assert run(w, mode="never").returncode == 0 and log_lines(w)[-1]["skipped"] == "nothing new"
    assert len(runs_of(w)) == capture_state.KEEP_RUNS


# ---- fill: a short form and a topic proposed into a file the owner reads ------------------------------------------

SAME = "Hand a subagent the acceptance check before it starts, as it may help it tell when it is done."
SHORT = "Give a subagent the acceptance check first, as it may help it know when it is done."


def fill_world(w):
    """The same claim (so the same handle) in two projects, one global lesson and one that stays out of the file."""
    lesson(w, w.pa, SAME, ("s1", "s2"))
    lesson(w, w.pb, SAME, ("s3", "s4"))
    g = records.write_memory(w.gmem, "global", kind="lesson", claim="Read the whole failing test output before you change any code.",
                             body="b\n", today=TODAY, origin="transcript", reach="general", weight="light",
                             sources=[f"session s5 project {records.project_key(w.pa)}",
                                      f"session s6 project {records.project_key(w.pb)}"])
    g = records.update(g, TODAY, triage=None)   # a released global record starts as pending
    lesson(w, w.pa, "Run the narrowest test that covers a change before the whole suite, as it may save time.", ("s7", "s8"))
    return g


def fill_ids(w):
    return {(x.id.split(":")[0], x.memory.handle): x.id for x in lessons(w)}


def fill_answer(w, items):
    (w.tmp / "fill-answer.json").write_text(items if isinstance(items, str) else json.dumps({"items": items}))
    os.environ["FAKE_FILL"] = str(w.tmp / "fill-answer.json")


def fill_run(w, *args, **kw):
    return run(w, *args, cmd="fill", **kw)


def proposal(w, g):
    ids = fill_ids(w)
    handle = records.load_memories(records.project_dir(w.pa), "project")[0].handle
    shared = [i for (kind, h), i in ids.items() if kind != "g" and h == handle]
    assert len(shared) == 2
    gid = ids[("g", g.handle)]
    fill_answer(w, [{"id": shared[0], "short": SHORT, "topic": "process"},
                    {"id": shared[1], "short": SHORT + " ", "topic": "Process"},   # invalid: dropped
                    {"id": gid, "short": "Read a failing test output to the end before changing code.", "topic": "testing"},
                    {"id": "g:nothing", "short": SHORT, "topic": "process"}])
    return shared, gid


def test_fill_dry_run_writes_the_proposal_and_changes_nothing(w):
    g = fill_world(w)
    shared, gid = proposal(w, g)
    before = snapshot(w)
    out = w.tmp / "proposal.json"
    done = fill_run(w, "--dry-run", "--out", str(out))
    assert done.returncode == 0, done.stderr
    assert "4 lessons asked, 2 kept, 2 dropped" in done.stdout, done.stdout
    items = json.loads(out.read_text())
    assert [(i["id"], i["scope"]) for i in items] == [(shared[0], w.pa.name), (gid, "global")]
    first = items[0]
    assert set(first) == {"id", "handle", "scope", "claim", "short", "topic", "load", "claim_digest"}
    assert (first["claim"], first["short"], first["topic"], first["load"]) == (SAME, SHORT, "process", "yes")
    assert first["claim_digest"] == corroborate.claim_digest(
        next(m for m in project_records(w.pa).values() if m.claim == SAME))
    assert snapshot(w) == before and calls(w) == 1 and not log_lines(w) and not (w.cdir / "runs").exists()
    call = json.loads(w.calls_file.read_text().splitlines()[0])
    assert call["args"][call["args"].index("--tools") + 1] == "Read,Write" and "fill.json" not in call["files"]
    assert "lessons.txt" in call["files"] and not any(v.startswith("CLAUDE_PLUGIN") for v in call["mem_vars"])


def test_fill_dry_run_asks_for_no_lesson_that_has_nothing_to_fill(w):
    done = fill_run(w, "--dry-run", "--out", str(w.tmp / "p.json"), mode="never")
    assert done.returncode == 0 and json.loads((w.tmp / "p.json").read_text()) == []


def test_fill_items_write_exactly_the_file_and_undo_puts_them_back(w):
    g = fill_world(w)
    shared, gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    before = snapshot(w)
    items = json.loads(out.read_text())
    for i in items:
        i["topic"] = "review"   # the owner edits the file
    out.write_text(json.dumps(items))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    b = next(m for m in project_records(w.pb).values() if m.claim == SAME)
    assert a.handle == b.handle   # the same handle, in two projects
    assert (a.short, a.topic) == (SHORT, "review") and (b.short, b.topic) == (None, None)   # only the project of the item
    (g_now,) = [m for m in globals_(w) if m.handle == g.handle]
    assert g_now.short.startswith("Read a failing test") and g_now.topic == "review"
    other = [m for m in project_records(w.pa).values() if m.claim.startswith("Run the narrowest")]
    assert other[0].short is None
    line = log_lines(w)[-1]
    assert line["fill"] == {"asked": 2, "written": 2, "dropped": 0, "failed": 0} and "t" in line and "ms" in line
    assert not (w.cdir / "seen.json").exists() and not (w.cdir / "status.json").exists()
    (stamp,) = [p.name for p in (w.cdir / "runs").iterdir()]
    assert stamp in done.stdout
    undone = run(w, stamp, cmd="undo", claude=False)
    assert undone.returncode == 0, undone.stderr
    assert snapshot(w) == before and not (w.cdir / "seen.json").exists()


def test_fill_items_write_the_second_project_of_a_shared_handle(w):
    g = fill_world(w)
    shared, _gid = proposal(w, g)
    fill_answer(w, [{"id": shared[1], "short": SHORT, "topic": "process"}])
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    assert fill_run(w, "--items", str(out), claude=False, mode="never").returncode == 0
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    b = next(m for m in project_records(w.pb).values() if m.claim == SAME)
    assert (a.short, b.short, b.topic) == (None, SHORT, "process")


def test_fill_items_refuse_an_item_whose_claim_changed(w):
    g = fill_world(w)
    proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
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
    g = fill_world(w)
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    records.update(a, TODAY, short="An older short form that the owner chose to rewrite.", topic="docs")
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    ids = fill_ids(w)
    pid = ids[("p", a.handle)] if ("p", a.handle) in ids else next(i for (k, h), i in ids.items() if h == a.handle and k != "g")
    digest = corroborate.claim_digest(a)
    good = {"id": pid, "handle": a.handle, "scope": w.pa.name, "claim": SAME, "short": SHORT, "topic": "process", "claim_digest": digest}
    file = w.tmp / "items.json"
    file.write_text(json.dumps([good, {**good, "short": "x" * 121}, {**good, "id": "g:nothing"}, {**good}, "nonsense",
                                {**good, "id": "p9:" + a.handle}]))
    done = fill_run(w, "--items", str(file), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 6, "written": 1, "dropped": 5, "failed": 0}
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    assert (a.short, a.topic) == (SHORT, "process")


def test_fill_alone_or_with_a_bad_file_exits_2(w):
    fill_world(w)
    done = fill_run(w, mode="never")
    assert done.returncode == 2 and "usage" in done.stderr and not log_lines(w)
    assert fill_run(w, "--dry-run", mode="never").returncode == 2
    assert fill_run(w, "--out", str(w.tmp / "x.json"), mode="never").returncode == 2
    assert fill_run(w, "--items", str(w.tmp / "none.json"), "--dry-run", mode="never").returncode == 2
    (w.tmp / "bad.json").write_text("{}")
    assert fill_run(w, "--items", str(w.tmp / "bad.json"), claude=False, mode="never").returncode == 2
    assert not (w.cdir / "runs").exists()


def fill_file(w, g, **change):
    """The proposal file of `proposal`, with the changes applied to every item."""
    shared, gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    items = [{**i, **change} for i in json.loads(out.read_text())]
    out.write_text(json.dumps(items))
    return out, shared, gid


def test_fill_items_drop_an_item_whose_handle_or_scope_disagrees_with_its_id(w):
    g = fill_world(w)
    out, shared, gid = fill_file(w, g)
    items = json.loads(out.read_text())
    items[0]["handle"] = "other-handle"
    items[1]["scope"] = w.pb.name
    out.write_text(json.dumps(items))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 0, "dropped": 2, "failed": 0}
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert (run_dir / "log.txt").read_text().count("handle or scope does not match its id") == 2
    assert all(m.short is None for m in project_records(w.pa).values()) and all(m.short is None for m in globals_(w))


def test_fill_items_apply_an_item_without_handle_and_scope_by_its_id(w):
    g = fill_world(w)
    out, shared, gid = fill_file(w, g)
    items = [{k: v for k, v in i.items() if k not in ("handle", "scope")} for i in json.loads(out.read_text())]
    out.write_text(json.dumps(items))
    assert fill_run(w, "--items", str(out), claude=False, mode="never").returncode == 0
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 2, "dropped": 0, "failed": 0}


def test_fill_items_start_no_settling_run(w):
    g = fill_world(w)
    out, shared, gid = fill_file(w, g)
    seen_env = w.tmp / "seen-env"
    broken = fake_plugin(w, f'if [ "$1" = memory ]; then echo "$MEM_SETTLE_AUTO|$MEM_SETTLE_MINUTES|$MEM_SETTLE_CLAUDE" >> {seen_env}; fi')
    env = {"MEM_SETTLE_AUTO": "1", "MEM_SETTLE_MINUTES": "5", "MEM_SETTLE_CLAUDE": "/bin/true"}
    done = run(w, "--items", str(out), cmd="fill", claude=False, mode="never", corr=broken, env=env)
    assert done.returncode == 0, done.stderr
    assert seen_env.read_text().split() == ["||"] * 2


def test_fill_items_drop_a_record_that_cannot_load(w):
    g = fill_world(w)
    out, shared, gid = fill_file(w, g)
    (g_now,) = [m for m in globals_(w) if m.handle == g.handle]
    records.update(g_now, TODAY, triage="pending")
    a = next(m for m in project_records(w.pa).values() if m.claim == SAME)
    records.update(a, TODAY, origin="web")
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 0, "dropped": 2, "failed": 0}
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert (run_dir / "log.txt").read_text().count("not a lesson that can load") == 2


def test_fill_dry_run_checks_the_output_folder_before_the_session(w):
    fill_world(w)
    done = fill_run(w, "--dry-run", "--out", str(w.tmp / "missing" / "p.json"))
    assert done.returncode == 2 and len(done.stderr.strip().splitlines()) == 1 and calls(w) == 0
    locked = w.tmp / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("permissions are not enforced here")
        done = fill_run(w, "--dry-run", "--out", str(locked / "p.json"))
        assert done.returncode == 2 and len(done.stderr.strip().splitlines()) == 1 and calls(w) == 0
    finally:
        locked.chmod(0o700)


def _a(w):
    return next(m for m in project_records(w.pa).values() if m.claim == SAME)


def test_fill_dry_run_writes_index_for_an_index_only_lesson(w):
    g = fill_world(w)
    records.update(_a(w), TODAY, load="index")
    out, shared, gid = fill_file(w, g)
    assert {i["id"]: i["load"] for i in json.loads(out.read_text())}[shared[0]] == "index"


def test_fill_items_apply_the_load_value(w):
    g = fill_world(w)
    out, shared, gid = fill_file(w, g)
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
    out, shared, gid = fill_file(w, g)
    records.update(_a(w), TODAY, short=SHORT, topic="process")
    item = {"id": shared[0], "handle": _a(w).handle, "scope": w.pa.name, "claim": SAME, "short": SHORT, "topic": "process",
            "load": "index", "claim_digest": corroborate.claim_digest(_a(w))}
    out.write_text(json.dumps([item]))
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert (_a(w).short, _a(w).topic, _a(w).load) == (SHORT, "process", "index")


def test_fill_items_drop_a_bad_load_value(w):
    g = fill_world(w)
    out, shared, gid = fill_file(w, g, load="maybe")
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert log_lines(w)[-1]["fill"] == {"asked": 2, "written": 0, "dropped": 2, "failed": 0}
    (run_dir,) = (w.cdir / "runs").iterdir()
    assert (run_dir / "log.txt").read_text().count("load must be yes, index or no") == 2
    assert _a(w).short is None


def test_fill_items_turn_on_a_record_that_was_turned_off(w):
    g = fill_world(w)
    out, shared, gid = fill_file(w, g)
    records.update(_a(w), TODAY, load="no")
    done = fill_run(w, "--items", str(out), claude=False, mode="never")   # the items say load yes
    assert done.returncode == 0, done.stderr
    assert (_a(w).short, _a(w).load) == (SHORT, None)
    records.update(_a(w), TODAY, load="no")
    items = [{k: v for k, v in i.items() if k != "load"} for i in json.loads(out.read_text())][:1]
    out.write_text(json.dumps(items))   # no load value: a rule turned off stays off
    assert fill_run(w, "--items", str(out), claude=False, mode="never").returncode == 0
    assert _a(w).load == "no" and log_lines(w)[-1]["fill"]["dropped"] == 1
