"""`bin/mem-corroborate`: the pass that matches lessons by meaning, with a fake `claude` and invented lessons."""
import argparse
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
import corroborate_cli
import corroborate_digest
import corroborate_fill
import corroborate_reword
import corroborate_run
import corroborate_state
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
src = os.environ.get("FAKE_DIGEST_CHECK" if out.endswith("digest-check.json") else "FAKE_DIGEST" if out.endswith("digest-write.json")
                     else "FAKE_REWORD_CHECK" if out.endswith("reword-check.json") else "FAKE_REWORD" if out.endswith("reword.json")
                     else "FAKE_VERDICTS" if out.endswith("verdicts.json") else "FAKE_FILL" if out.endswith("fill.json") else "FAKE_GROUPS")
if os.path.basename(out).startswith("digest-") and os.environ.get("FAKE_INPUTS"):   # what the session was asked, kept for the test
    shutil.copy("input.txt", os.environ["FAKE_INPUTS"] + "-" + os.path.basename(out)[:-5])
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
    monkeypatch.setenv("FAKE_INPUTS", str(tmp_path / "asked"))
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
    assert records.standing(g) == "established" and g.released and g.triage is None   # a light lesson waits for nobody
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


def cut_problems(out):
    """The owner cuts the items the dry run marked with a problem."""
    out.write_text(json.dumps([i for i in json.loads(out.read_text()) if "problem" not in i]))


def proposal(w, g):
    ids = fill_ids(w)
    handle = records.load_memories(records.project_dir(w.pa), "project")[0].handle
    shared = [i for (kind, h), i in ids.items() if kind != "g" and h == handle]
    assert len(shared) == 2
    gid = ids[("g", g.handle)]
    fill_answer(w, [{"id": shared[0], "short": SHORT, "topic": "process"},
                    {"id": shared[1], "short": SHORT + " ", "topic": "Process"},   # invalid: kept for the owner, with a problem
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
    assert "4 lessons asked, 2 kept, 2 to edit, 1 dropped" in done.stdout, done.stdout
    items = json.loads(out.read_text())
    assert {(i["id"], i["scope"]) for i in items if "problem" not in i} == {(shared[0], w.pa.name), (gid, "global")}
    assert len([i for i in items if "problem" in i]) == 2   # the invalid one and the lesson with no proposal
    items = [i for i in items if "problem" not in i]
    first = items[0]
    assert set(first) == {"id", "handle", "scope", "claim", "short", "topic", "load", "claim_digest"}
    assert (first["claim"], first["short"], first["topic"], first["load"]) == (SAME, SHORT, "process", "yes")
    assert first["claim_digest"] == corroborate.claim_digest(
        next(m for m in project_records(w.pa).values() if m.claim == SAME))
    assert snapshot(w) == before and calls(w) == 1 and not log_lines(w) and not (w.cdir / "runs").exists()
    call = json.loads(w.calls_file.read_text().splitlines()[0])
    assert call["args"][call["args"].index("--tools") + 1] == "Read,Write" and "fill.json" not in call["files"]
    assert "lessons.txt" in call["files"] and not any(v.startswith("CLAUDE_PLUGIN") for v in call["mem_vars"])


def test_fill_dry_run_keeps_what_needs_editing_with_its_problem_and_apply_ignores_the_field(w):
    g = fill_world(w)
    shared, gid = proposal(w, g)
    other = next(i for (k, h), i in fill_ids(w).items() if k != "g" and i not in shared)
    fill_answer(w, [{"id": shared[0], "short": "x" * 134, "topic": "process"},
                    {"id": gid, "short": "Read a failing test output to the end before changing code.", "topic": "Testing"},
                    {"id": "g:nothing", "short": SHORT, "topic": "process"}])
    out = w.tmp / "proposal.json"
    done = fill_run(w, "--dry-run", "--out", str(out))
    assert done.returncode == 0, done.stderr
    assert "4 lessons asked, 0 kept, 4 to edit, 1 dropped" in done.stdout, done.stdout
    by_id = {i["id"]: i for i in json.loads(out.read_text())}
    assert set(by_id) == {shared[0], shared[1], gid, other}
    assert by_id[shared[0]]["problem"] == "short has 134 characters, at most 120" and by_id[shared[0]]["short"] == "x" * 134
    assert by_id[gid]["problem"] == "topic must be one or two lowercase words" and by_id[gid]["topic"] == "Testing"
    assert by_id[shared[1]] ["problem"] == by_id[other]["problem"] == "no proposal"
    assert (by_id[other]["short"], by_id[other]["topic"]) == ("", "")
    assert {"id", "handle", "scope", "claim", "short", "topic", "load", "claim_digest", "problem"} == set(by_id[other])
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
    shared, gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
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
    cut_problems(out)
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


def test_fill_items_and_undo_behave_as_before_through_apply_fill(w):
    g = fill_world(w)
    shared, gid = proposal(w, g)
    out = w.tmp / "proposal.json"
    assert fill_run(w, "--dry-run", "--out", str(out)).returncode == 0
    cut_problems(out)
    before = snapshot(w)
    done = fill_run(w, "--items", str(out), claude=False, mode="never")
    assert done.returncode == 0, done.stderr
    assert "2 asked, 2 written, 0 dropped, 0 failed" in done.stdout
    (stamp,) = [p.name for p in (w.cdir / "runs").iterdir()]
    assert stamp.endswith("-fill") and (w.cdir / "runs" / stamp / "fill").exists()   # never shares a name with a pass run
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
    assert result["written"] == 2 and result["dropped"] == result["failed"] == 0
    assert sorted(result["applied"]) == sorted([shared[0], gid])
    written = [m for m in [*project_records(w.pa).values(), *globals_(w)] if m.short]
    assert len(written) == 2 and all(m.short_by == "model" for m in written)


# ---- fill_auto: the pass writes and checks short forms by itself ---------------------------------------------------

NARROW = "Run the narrowest test that covers a change before the whole suite, as it may save time."
GCLAIM = "Read the whole failing test output before you change any code."
SHORTS = {SAME: SHORT, GCLAIM: "Read the whole failing test output before changing code.",
          NARROW: "Run the narrowest covering test before the whole suite, as it may save time."}


def candidate_ids(w):
    """claim -> ids of the lessons that lack a short form, as the fill sees them."""
    registry = records.read_registry(w.data)
    found = {}
    for i, _p, m in corroborate.fill_records(corroborate.counted_projects(registry), w.gmem):
        found.setdefault(m.claim, []).append(i)
    return found


def answers(w, mp, writer="ok", checker=True, shorts=None):
    """The fake's two answers. writer: "ok" (a short for every candidate), "none" (no file) or the file's text;
    checker: True or False for every short, "none", or the file's text."""
    shorts = {**SHORTS, **(shorts or {})}
    mp.delenv("FAKE_FILL", raising=False)
    mp.delenv("FAKE_VERDICTS", raising=False)
    if writer == "ok":
        items = [{"id": i, "short": shorts[c], "topic": "process"} for c, ids in candidate_ids(w).items() for i in ids]
        writer = json.dumps({"items": items})
    if writer != "none":
        (w.tmp / "fill-answer.json").write_text(writer)
        mp.setenv("FAKE_FILL", str(w.tmp / "fill-answer.json"))
    if checker in (True, False):
        every = [i for ids in candidate_ids(w).values() for i in ids]
        checker = json.dumps({"verdicts": [{"id": i, "reason": "r", "faithful": checker} for i in every]})
    if checker != "none":
        (w.tmp / "verdicts.json").write_text(checker)
        mp.setenv("FAKE_VERDICTS", str(w.tmp / "verdicts.json"))


def auto(w):
    return corroborate_fill.fill_auto(str(w.fake), 0.25)


def attempts(w):
    return json.loads((w.cdir / "fill-attempts.json").read_text())


def one_lesson(w, claim=NARROW):
    return lesson(w, w.pa, claim, ("s7", "s8"))


def by_claim(w, claim):
    return next(m for m in project_records(w.pa).values() if m.claim == claim)


def fill_runs(w):
    return sorted(p for p in (w.cdir / "runs").iterdir() if p.name.endswith("-fill")) if (w.cdir / "runs").exists() else []


def test_fill_auto_writes_a_checked_short_form_marked_as_the_models(w, monkeypatch):
    g = fill_world(w)
    answers(w, monkeypatch)
    result = auto(w)
    assert result == {"asked": 4, "written": 4, "dropped": 0, "refused_code": 0, "refused_check": 0, "to_triage": 0,
                      "left": 0, "cost": 0.06, "stopped": None}
    assert calls(w) == 2
    narrow = by_claim(w, NARROW)
    assert (narrow.short, narrow.topic, narrow.short_by, narrow.load) == (SHORTS[NARROW], "process", "model", None)
    (gl,) = [m for m in globals_(w) if m.handle == g.handle]
    assert gl.short_by == "model" and gl.short == SHORTS[GCLAIM]
    assert status(w)["fill"] == result


def test_fill_auto_refuses_by_code_before_paying_the_checker(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, shorts={NARROW: "Run the narrowest covering test before the whole suite."})
    result = auto(w)
    assert (result["refused_code"], result["written"], result["refused_check"]) == (1, 0, 0)
    assert calls(w) == 1 and by_claim(w, NARROW).short is None


def test_fill_auto_does_not_write_what_the_checker_refused(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, checker=False)
    result = auto(w)
    assert (result["refused_check"], result["written"]) == (1, 0)
    assert calls(w) == 2 and by_claim(w, NARROW).short is None and not fill_runs(w)


def test_a_general_lesson_is_held_at_triage_with_its_reason_after_two_refusals_and_a_project_lesson_is_left(w, monkeypatch):
    g = fill_world(w)
    answers(w, monkeypatch, checker=False)
    first = auto(w)
    assert (first["to_triage"], first["left"], first["refused_check"]) == (0, 0, 4)
    assert attempts(w)["lessons"] and all(v["count"] == 1 for v in attempts(w)["lessons"].values())
    second = auto(w)
    assert (second["to_triage"], second["left"]) == (1, 3)
    (gl,) = [m for m in globals_(w) if m.handle == g.handle]
    assert (gl.triage, gl.triage_reason) == ("pending", "the checker did not find the short form faithful to the claim")
    assert all(m.triage is None for m in project_records(w.pa).values())


def test_a_third_run_starts_no_session_for_a_lesson_refused_twice(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, checker=False)
    auto(w)
    auto(w)
    assert calls(w) == 4
    third = auto(w)
    assert calls(w) == 4 and third["asked"] == 0 and third["stopped"] is None


def test_an_applied_short_form_that_was_undone_is_not_written_again(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch)
    assert auto(w)["written"] == 1
    (run_dir,) = fill_runs(w)
    assert run(w, run_dir.name, cmd="undo", claude=False).returncode == 0
    assert by_claim(w, NARROW).short is None
    again = auto(w)
    assert calls(w) == 2 and again["asked"] == 0 and by_claim(w, NARROW).short is None


def test_an_applied_short_form_the_owner_removed_is_not_written_again_until_the_claim_changes(w, monkeypatch):
    m = one_lesson(w)
    answers(w, monkeypatch)
    assert auto(w)["written"] == 1
    records.update(by_claim(w, NARROW), TODAY, short=None, topic=None)
    assert by_claim(w, NARROW).short is None
    assert auto(w)["asked"] == 0 and calls(w) == 2
    records.update(by_claim(w, NARROW), TODAY, claim=NARROW + " It was seen twice.")
    answers(w, monkeypatch, shorts={NARROW + " It was seen twice.": SHORTS[NARROW]})
    assert auto(w)["asked"] == 1 and calls(w) == 4
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
    other = one_lesson(w, "Keep a failing command's output in a file, as it may help when it is long.")
    off = one_lesson(w, "Name a branch after its task, as it may help when one searches for it later.")
    records.update(by_claim(w, NARROW), TODAY, load="index")
    records.update(off, TODAY, load="no")
    shorts = {other.claim: "Keep a failing command's output in a file, as it may help.",
              off.claim: "Name a branch after its task, as it may help."}
    answers(w, monkeypatch, shorts=shorts)
    result = auto(w)
    assert (result["asked"], result["written"]) == (2, 2)
    assert (by_claim(w, NARROW).load, by_claim(w, NARROW).short) == ("index", SHORTS[NARROW])
    assert (by_claim(w, off.claim).load, by_claim(w, off.claim).short) == ("no", None)


@pytest.mark.parametrize("bad", ["no file", "not json", '{"items": 3}'])
def test_an_unusable_writer_answer_counts_no_attempt_and_sends_nothing_to_triage(w, monkeypatch, bad):
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
    assert calls(w) == 4
    state = attempts(w)
    assert state["lessons"] == {} and state["failures"]["count"] == 2
    assert not any(m.short for m in [*project_records(w.pa).values(), *project_records(w.pb).values(), *globals_(w)])
    assert [m.triage for m in globals_(w) if m.handle == g.handle] == [None] and not fill_runs(w)


def test_after_three_failed_sessions_no_session_starts_until_the_candidates_change(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, writer="none")
    for _ in range(3):
        assert auto(w)["stopped"]
    assert calls(w) == 3
    waiting = auto(w)
    assert calls(w) == 3 and waiting["stopped"] == "waiting for the lessons to change"
    one_lesson(w, "Keep a failing command's output in a file, as it may help when it is long.")
    answers(w, monkeypatch, writer="none")
    assert auto(w)["stopped"] != "waiting for the lessons to change" and calls(w) == 4


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
    lock = auto_state.take_run_lock(w.cdir)
    try:
        result = auto(w)
    finally:
        os.close(lock)
    assert result["stopped"] == "a run is going" and result["written"] == 0 and calls(w) == 0
    assert not (w.cdir / "fill-attempts.json").exists() and "fill" not in status(w) and by_claim(w, NARROW).short is None


def test_two_fill_runs_in_the_same_second_keep_separate_run_folders(w, monkeypatch):
    one_lesson(w)
    monkeypatch.setattr(corroborate_fill.time, "strftime", lambda fmt: "20260101-000000")
    answers(w, monkeypatch)
    assert auto(w)["written"] == 1
    other = one_lesson(w, "Keep a failing command's output in a file, as it may help when it is long.")
    answers(w, monkeypatch, shorts={other.claim: "Keep a failing command's output in a file, as it may help."})
    assert auto(w)["written"] == 1
    first, second = fill_runs(w)
    assert first != second and (first / "journal.jsonl").exists() and (second / "journal.jsonl").exists()


def test_undo_of_an_automatic_fill_run_restores_the_records(w, monkeypatch):
    fill_world(w)
    answers(w, monkeypatch)
    before = snapshot(w)
    assert auto(w)["written"] == 4
    assert snapshot(w) != before
    (run_dir,) = fill_runs(w)
    assert run(w, run_dir.name, cmd="undo", claude=False).returncode == 0
    assert snapshot(w) == before and not (w.cdir / "seen.json").exists()


def test_auto_runs_the_fill_after_the_pass_and_logs_its_counts(w, monkeypatch):
    fill_world(w)
    model(w, [])
    answers(w, monkeypatch)
    done = run(w, cmd="auto", env={OPTION: "true"})
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    lines = log_lines(w)
    (filled,) = [x for x in lines if "fill" in x]
    assert lines[-1] is filled and "lessons" in lines[0] and filled["fill"]["written"] > 0 and filled["fill"]["stopped"] is None
    assert isinstance(filled["ms"], int) and filled["t"]
    assert status(w)["fill"] == filled["fill"] and status(w)["state"] == "ok"


def test_auto_skips_the_fill_when_loaded_rules_is_off(w, monkeypatch):
    fill_world(w)
    model(w, [])
    answers(w, monkeypatch)
    for env in ({"MEM_LOADED_RULES": "off"}, {"CLAUDE_PLUGIN_OPTION_LOADED_RULES": "false"}):
        done = run(w, cmd="auto", env={OPTION: "true", **env})
        assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
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

    def execute_then_look(*args, **kw):   # what the pass left, read before the fill runs
        out = real(*args, **kw)
        kept.update(seen=(w.cdir / "seen.json").read_bytes(), status=(w.cdir / "status.json").read_bytes())
        return out

    monkeypatch.setattr(corroborate_run, "execute", execute_then_look)
    assert corroborate_cli.cmd_auto(argparse.Namespace(claude=str(w.fake))) == 0
    (line,) = log_lines(w)
    assert "fill" not in line and line["failed"] is None and line["written"] == 1 and len(globals_(w)) == 1
    assert (w.cdir / "seen.json").read_bytes() == kept["seen"]
    assert (w.cdir / "status.json").read_bytes() == kept["status"]
    assert status(w)["state"] == "ok" and "fill" not in status(w) and "failure" not in status(w)


def test_status_shows_the_last_fill_and_its_failure(w, capsys):
    w.cdir.mkdir(parents=True)
    fill = {"asked": 5, "written": 2, "dropped": 0, "refused_code": 1, "refused_check": 1, "to_triage": 1, "left": 1,
            "cost": 0.1, "stopped": "over budget"}
    auto_state.write_json(w.cdir / "status.json", {"state": "ok", "cost": 0.1, "fill": fill})
    assert corroborate_state.cmd_status() == 0
    out = capsys.readouterr().out
    assert "last fill: 2 written, 2 refused, 1 to triage, stopped: over budget\n" in out
    quiet = {**fill, "written": 0, "refused_code": 0, "refused_check": 0, "stopped": None}
    auto_state.write_json(w.cdir / "status.json", {"state": "ok", "fill": quiet})   # a run that only held a lesson
    assert corroborate_state.cmd_status() == 0
    assert "last fill: 0 written, 0 refused, 1 to triage\n" in capsys.readouterr().out
    auto_state.write_json(w.cdir / "status.json", {"state": "ok", "fill": {**quiet, "to_triage": 0}})
    assert corroborate_state.cmd_status() == 0
    assert "last fill" not in capsys.readouterr().out


# ---- fill_auto: a step that fails, a load the owner changed, a partial check ----------------------------------------

OTHER = "Keep a failing command's output in a file, as it may help when it is long."
OTHER_SHORT = "Keep a failing command's output in a file, as it may help."
CODE_REFUSED = {NARROW: "Run the narrowest covering test before the whole suite."}   # the hedge is gone: shortcheck refuses it


def count_of(w, claim):
    import hashlib
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
    assert count_of(w, OTHER) == [2]   # it passed the checks but was not written: its apply did not complete


def _breaking_apply(w, monkeypatch):

    def boom(*_args, **_kw):
        raise RuntimeError("apply broke")

    monkeypatch.setattr(corroborate_fill, "apply_fill", boom)


def test_a_general_lesson_refused_by_code_in_two_runs_with_a_failing_apply_is_held_at_triage(w, monkeypatch):
    g = fill_world(w)
    answers(w, monkeypatch, shorts={GCLAIM: "Always read the whole failing test output before changing code."})
    _breaking_apply(w, monkeypatch)
    assert auto(w)["to_triage"] == 0
    second = auto(w)
    assert (second["stopped"], second["to_triage"]) == ("the apply failed", 1)
    (gl,) = [m for m in globals_(w) if m.handle == g.handle]
    assert gl.triage == "pending" and gl.triage_reason == 'the short form says "always" and the claim does not'


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
        auto_state.write_json(w.cdir / "fill-attempts.json", {**state, "lessons": {}})
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
    records.update(by_claim(w, NARROW), TODAY, short=None, topic=None)   # the owner removes it
    assert auto(w)["asked"] == 0 and calls(w) == 2


def test_the_automatic_fill_never_sets_load_and_a_record_turned_off_meanwhile_stays_so(w, monkeypatch):
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
    item = {"id": ident, "short": SHORTS[NARROW], "topic": "process", "load": "yes",
            "claim_digest": corroborate.claim_digest(m)}
    assert corroborate_fill.apply_fill([item], w.cdir / "runs" / "direct-fill", user_read=False)["written"] == 1
    (args,) = seen_args
    assert not {"--load", "--index-only", "--no-load"} & set(args)


def test_a_checker_that_answers_for_the_first_id_only_is_a_failed_session_twice(w, monkeypatch):
    g = fill_world(w)
    first = sorted(i for ids in candidate_ids(w).values() for i in ids)[0]
    answers(w, monkeypatch, checker=json.dumps({"verdicts": [{"id": first, "reason": "r", "faithful": True}]}))
    for _ in range(2):
        result = auto(w)
        assert result["stopped"] and result["written"] == result["to_triage"] == 0
    state = attempts(w)
    assert state["lessons"] == {} and state["failures"]["count"] == 2
    assert [m.triage for m in globals_(w) if m.handle == g.handle] == [None]
    assert not any(m.short for m in [*project_records(w.pa).values(), *project_records(w.pb).values(), *globals_(w)])


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
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before = path.read_text()

    def broken(*_args):
        raise OSError("disk")

    monkeypatch.setattr(auto_state.os, "replace", broken)
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


def test_a_writer_item_with_a_problem_is_refused_counted_and_not_sent_to_the_checker(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, shorts={NARROW: "Run the narrowest covering test. " + "x" * 120})
    result = auto(w)
    assert (result["written"], result["refused_code"], result["refused_check"]) == (0, 1, 0)   # the length rule is code
    assert calls(w) == 1 and count_of(w, NARROW) == [1] and by_claim(w, NARROW).short is None


def test_a_verdict_that_is_not_exactly_true_writes_nothing(w, monkeypatch):
    one_lesson(w)
    answers(w, monkeypatch, checker=json.dumps({"verdicts": [{"id": i, "reason": "r", "faithful": "yes"}
                                                              for i in candidate_ids(w)[NARROW]]}))
    result = auto(w)
    assert (result["written"], result["refused_check"]) == (0, 1) and by_claim(w, NARROW).short is None


def test_an_unusable_writer_answer_twice_sends_nothing_to_triage(w, monkeypatch):
    g = fill_world(w)
    answers(w, monkeypatch, writer="none")
    for _ in range(2):
        assert auto(w)["to_triage"] == 0
    assert [m.triage for m in globals_(w) if m.handle == g.handle] == [None] and attempts(w)["lessons"] == {}


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
    (gm,) = [m for m in globals_(w)]
    model(w, [group(f"g:{gm.handle}", ident(w, "Give a subagent"))])
    before = _records_only(w)
    assert run(w).returncode == 0
    (g,) = globals_(w)
    assert records.sessions(g).count("session s2") == 1 and g.log == ["2026-11-21 session s2 worked"]
    assert log_lines(w)[-1]["sightings"] == 1 and log_lines(w)[-1]["cases"] == 1
    assert run(w, Path(status(w)["log"]).name, cmd="undo", claude=False).returncode == 0
    assert _records_only(w) == before


def _two_cases(w):
    return _with_log(w, w.pb, BRIEF2, "s2", ["2026-11-19 session s2 failed", "2026-11-21 session s2 worked"])


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
    broken = fake_plugin(w, f'if [ "$1" = confirm ]; then echo x >> {n}; '
                            f'if [ "$(wc -l < {n})" = 2 ]; then echo boom >&2; exit 2; fi; fi')
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
    assert len(globals_(w)) == 1   # the record exists
    assert (line["written"], line["failed_actions"]) == (1, 1)


# ---- reword_auto: the pass rewords a loaded lesson whose present wording got worse ----------------------------------

OLD_WORDING = "Running the narrowest covering test before the whole suite may save time."
NEW_WORDING = "Before the whole suite, running the narrowest test that covers a change may save time."
SECOND_CLAIM = "Keep a failing command's output in a file, as it may help when it is long."


def ago(n):
    return TODAY - datetime.timedelta(days=n)


def worse_one(w, claim=NARROW, scope="project", failed=(5, 4), worked=()):
    """A loaded lesson whose only wording (10 days old) failed twice since: the step's candidate."""
    if scope == "global":   # as `fill_world` makes it: seen in two projects, released from triage
        m = records.write_memory(w.gmem, "global", kind="lesson", claim=claim, body="b\n", today=TODAY, origin="transcript",
                                 reach="general", weight="light",
                                 sources=[f"session s5 project {records.project_key(w.pa)}",
                                          f"session s6 project {records.project_key(w.pb)}"])
        m = records.update(m, TODAY, triage=None)
    else:
        m = lesson(w, w.pa, claim, ("s7", "s8"))
    log = [records.case_entry(ago(n), f"session z{n}", "failed") for n in failed]
    log += [records.case_entry(ago(n), f"session y{n}", "worked") for n in worked]
    return records.update(m, TODAY, short=OLD_WORDING, short_by="model",
                          versions=[records.version_entry(ago(10), OLD_WORDING)], log=log)


def reword_answers(w, mp, shorts=None, writer="ok", checker=True):
    """The fake's two answers of the step. shorts: claim -> proposed short (default NEW_WORDING for every candidate);
    writer/checker as in `answers`, with no `topic` anywhere."""
    mp.delenv("FAKE_REWORD", raising=False)
    mp.delenv("FAKE_REWORD_CHECK", raising=False)
    found = candidate_ids(w)
    if writer == "ok":
        items = [{"id": i, "short": (shorts or {}).get(c, NEW_WORDING)} for c, ids in found.items() for i in ids]
        writer = json.dumps({"items": items})
    if writer != "none":
        (w.tmp / "reword-answer.json").write_text(writer)
        mp.setenv("FAKE_REWORD", str(w.tmp / "reword-answer.json"))
    if checker in (True, False):
        every = [i for ids in found.values() for i in ids]
        checker = json.dumps({"verdicts": [{"id": i, "reason": "the checker's reason", "faithful": checker} for i in every]})
    if checker != "none":
        (w.tmp / "reword-check-answer.json").write_text(checker)
        mp.setenv("FAKE_REWORD_CHECK", str(w.tmp / "reword-check-answer.json"))


def reword(w, **kw):
    return corroborate_reword.reword_auto(str(w.fake), 0.25, **kw)


def reword_state(w):
    return json.loads((w.cdir / "reword-attempts.json").read_text())


def reword_runs(w):
    return sorted(p for p in (w.cdir / "runs").iterdir() if p.name.endswith("-reword")) if (w.cdir / "runs").exists() else []


def mem_curate(w):
    env = {**os.environ, "MEM_PROJECT": str(w.pa)}
    return subprocess.run([str(MEM), "curate"], env=env, capture_output=True, text=True, cwd=w.pa, timeout=120).stdout


NOTHING = {"asked": 0, "written": 0, "refused_code": 0, "refused_check": 0, "same_text": 0, "no_proposal": 0,
           "gave_up": 0, "changed": 0, "failed_edits": 0, "cost": 0.0, "stopped": None}


def test_reword_applies_an_accepted_wording(w, monkeypatch):
    worse_one(w)
    found = candidate_ids(w)
    answer = json.dumps({"items": [{"id": i, "short": NEW_WORDING, "topic": "other-topic"} for ids in found.values() for i in ids]})
    reword_answers(w, monkeypatch, writer=answer)
    topic_before = by_claim(w, NARROW).topic
    assert reword(w) == {**NOTHING, "asked": 1, "written": 1, "cost": 0.06}
    assert calls(w) == 2
    m = by_claim(w, NARROW)
    assert (m.short, m.reworded, m.short_by) == (NEW_WORDING, TODAY, "model")
    assert m.topic == topic_before and m.topic != "other-topic"
    assert [t for _, t in records.version_list(m)] == [OLD_WORDING, NEW_WORDING]
    assert not records.got_worse(m)


def test_reword_applies_an_answer_with_no_topic(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)   # the default answer has no `topic`
    assert reword(w)["written"] == 1 and by_claim(w, NARROW).short == NEW_WORDING


def test_reword_applies_to_a_global_lesson(w, monkeypatch):
    worse_one(w, claim=GCLAIM, scope="global")
    reword_answers(w, monkeypatch, shorts={GCLAIM: "Reading the whole failing test output before changing code may help."})
    got = reword(w)
    assert got["written"] == 1, got
    (g,) = globals_(w)
    assert g.reworded == TODAY and g.short.startswith("Reading the whole")


def test_two_refusals_give_up_and_mark_the_lesson(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, checker=False)
    first = reword(w)
    assert (first["refused_check"], first["gave_up"], first["written"]) == (1, 0, 0)
    assert by_claim(w, NARROW).reword_failed is None
    second = reword(w)
    assert (second["refused_check"], second["gave_up"]) == (1, 1)
    m = by_claim(w, NARROW)
    assert m.reword_failed == ago(10) and m.short == OLD_WORDING and m.reworded is None
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before


def test_a_refusal_by_code_and_a_repeat_are_counted_and_the_checker_is_not_paid(w, monkeypatch):
    worse_one(w)
    worse_one(w, claim=SECOND_CLAIM)
    reword_answers(w, monkeypatch, shorts={NARROW: "Run the narrowest covering test before the whole suite.",   # the hedge is gone
                                           SECOND_CLAIM: OLD_WORDING})   # an earlier wording
    result = reword(w)
    assert (result["refused_code"], result["same_text"], result["written"]) == (1, 1, 0)
    assert calls(w) == 1


def test_an_unusable_answer_changes_no_lesson_and_three_in_a_row_wait(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, writer="this is not json")
    for n in (1, 2, 3):
        result = reword(w)
        assert result["stopped"] and result["written"] == 0
        assert reword_state(w) == {"lessons": {}, "failures": {"count": n, "fingerprint": reword_state(w)["failures"]["fingerprint"]}}
    assert by_claim(w, NARROW).short == OLD_WORDING
    before = calls(w)
    waiting = reword(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]
    worse_one(w, claim=SECOND_CLAIM)   # the candidates changed
    assert reword(w)["stopped"] != waiting["stopped"] and calls(w) == before + 1


def test_a_checker_that_gives_no_usable_answer_is_a_failed_session(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, checker="none")
    result = reword(w)
    assert result["stopped"] and result["written"] == 0
    assert reword_state(w)["lessons"] == {} and reword_state(w)["failures"]["count"] == 1
    assert by_claim(w, NARROW).short == OLD_WORDING


def test_undo_still_does_not_bring_a_second_rewording(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    auto_state.private_dir(w.cdir)
    seen_file = w.cdir / "seen.json"
    seen_file.write_text(json.dumps({"fingerprint": "kept", "refused": {}}))
    assert reword(w)["written"] == 1
    (run_dir,) = reword_runs(w)
    assert (run_dir / "fill").exists() and (run_dir / "journal.jsonl").exists()
    assert run(w, run_dir.name, cmd="undo", claude=False).returncode == 0
    m = by_claim(w, NARROW)
    assert (m.short, m.reworded) == (OLD_WORDING, None) and m.short_by == "model"
    assert reword_state(w)["lessons"][next(iter(reword_state(w)["lessons"]))] == {
        "version": ago(10).isoformat(), "count": 0, "spent": True}   # spent for the version it was written from
    assert json.loads(seen_file.read_text())["fingerprint"] == "kept"   # not taken for a corroboration run
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before
    assert m.handle in mem_curate(w)


def test_a_reworded_version_that_got_worse_stays_with_the_owner(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    assert reword(w)["written"] == 1
    m = by_claim(w, NARROW)
    records.update(m, TODAY, log=[*m.log, records.case_entry(TODAY + datetime.timedelta(days=1), "session q", "failed"),
                                  records.case_entry(TODAY + datetime.timedelta(days=2), "session r", "failed")])
    assert records.got_worse(by_claim(w, NARROW))
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before
    shown = mem_curate(w)
    assert m.handle in shown and "got worse too" in shown


def test_dry_run_writes_the_sheet_and_nothing_else(w, monkeypatch):
    worse_one(w)
    worse_one(w, claim=SECOND_CLAIM)
    worse_one(w, claim=GCLAIM, failed=())   # loaded, never failed: only `--every` takes it
    reword_answers(w, monkeypatch, shorts={SECOND_CLAIM: "Keeping a long failing command's output in a file may help."},
                   checker=True)
    before = snapshot(w)
    sheet = w.tmp / "sheet.md"
    done = run(w, "--every", "--dry-run", "--sheet", str(sheet), cmd="reword")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["asked"] == 3
    assert snapshot(w) == before and not (w.cdir / "reword-attempts.json").exists() and not reword_runs(w)
    rows = [x for x in sheet.read_text().splitlines() if x.startswith("| ") and "---" not in x][1:]
    assert len(rows) == 3 and sum("the checker's reason" in x for x in rows) >= 1
    assert any(NEW_WORDING in x for x in rows) and any(NARROW in x for x in rows)


def test_without_a_sheet_nothing_is_written_beside_the_records(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    before = snapshot(w)
    result = reword(w, apply=False)
    assert result["asked"] == 1 and result["written"] == 0 and snapshot(w) == before
    assert not (w.cdir / "reword-attempts.json").exists()


def test_every_and_limit_pass_through(w, monkeypatch):
    for claim in (NARROW, SECOND_CLAIM, GCLAIM):
        worse_one(w, claim=claim)
    worse_one(w, claim="Read the build log from the top before guessing at a cause, as it may help.", failed=())
    reword_answers(w, monkeypatch, checker=False)
    assert reword(w, every=True, limit=2, apply=False)["asked"] == 2
    assert reword(w, every=True, apply=False)["asked"] == 4
    assert reword(w, apply=False)["asked"] == 3


def test_reword_respects_the_lock(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    lock = auto_state.take_run_lock(w.cdir)
    try:
        result = reword(w)
    finally:
        os.close(lock)
    assert "run is going" in result["stopped"] and result["written"] == 0 and calls(w) == 0
    assert not (w.cdir / "reword-attempts.json").exists() and by_claim(w, NARROW).short == OLD_WORDING


def test_a_missing_claude_binary_is_a_stop_not_an_exception(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    result = corroborate_reword.reword_auto("/nonexistent/claude", 0.25)
    assert result["stopped"] and result["written"] == 0
    assert by_claim(w, NARROW).short == OLD_WORDING


def test_reword_skips_a_lesson_edited_meanwhile(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    by_hand = "A short form the owner wrote while the sessions ran, which the step must not overwrite."
    edit_between(w, monkeypatch, short=by_hand)
    result = reword(w)
    assert result["changed"] == 1 and result["written"] == 0 and result["no_proposal"] == 0
    m = by_claim(w, NARROW)
    assert m.short == by_hand and m.reworded is None
    assert reword_state(w)["lessons"] == {} and not reword_runs(w)


def edit_between(w, mp, **changes):
    """The record is changed after the checker session and before the step's edit."""
    real = corroborate_run._ask

    def ask_then_edit(*args, **kw):
        got = real(*args, **kw)
        if args[2] == "check":
            records.update(by_claim(w, NARROW), TODAY, **changes)
        return got

    mp.setattr(corroborate_run, "_ask", ask_then_edit)


@pytest.mark.parametrize("changes", [{"reviewed": TODAY}, {"reworded": ago(10)},
                                     {"status": "superseded", "superseded_by": "other"}])
def test_reword_skips_a_lesson_the_owner_kept_meanwhile(w, monkeypatch, changes):
    worse_one(w)
    reword_answers(w, monkeypatch)
    edit_between(w, monkeypatch, **changes)
    result = reword(w)
    assert (result["changed"], result["written"], result["no_proposal"], result["failed_edits"]) == (1, 0, 0, 0)
    assert reword_state(w)["lessons"] == {} and not reword_runs(w)
    assert [m for m in project_lessons(w) if m.claim == NARROW][0].short == OLD_WORDING


def test_a_strong_lesson_that_got_worse_is_reworded(w, monkeypatch):
    worse_one(w)
    m = by_claim(w, NARROW)
    records.update(m, TODAY, weight="strong", owner_confirmed=TODAY)
    reword_answers(w, monkeypatch)
    assert reword(w)["written"] == 1 and by_claim(w, NARROW).short == NEW_WORDING


def test_a_lesson_that_became_strong_meanwhile_is_still_applied(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    edit_between(w, monkeypatch, weight="strong")
    result = reword(w)
    assert (result["written"], result["changed"]) == (1, 0) and by_claim(w, NARROW).short == NEW_WORDING


def project_lessons(w):
    return records.load_memories(records.project_dir(w.pa), "project")


def fake_mem(w, mp, shell):
    """The step's `mem` calls go through a wrapper: `shell` runs first (REAL is the real command), then the real one."""
    script = w.tmp / "mem-fake"
    script.write_text("#!/bin/sh\n" + shell.replace("REAL", str(corroborate_run.MEM)) + f'\nexec {corroborate_run.MEM} "$@"\n')
    script.chmod(0o755)
    mp.setattr(corroborate_run, "MEM", script)


EDIT_EXITS = 'if [ "$1" = memory ] && [ "$2" = edit ]; then case "$*" in *--short=*) exit %d;; esac; fi'


def test_a_missing_proposal_spends_an_attempt_and_two_give_up(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, writer=json.dumps({"items": []}))
    first = reword(w)
    assert (first["no_proposal"], first["gave_up"]) == (1, 0) and first["stopped"] is None
    assert list(reword_state(w)["lessons"].values())[0]["count"] == 1
    second = reword(w)
    assert (second["no_proposal"], second["gave_up"]) == (1, 1)
    assert by_claim(w, NARROW).reword_failed == ago(10) and by_claim(w, NARROW).short == OLD_WORDING
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before


def test_a_usage_error_of_the_edit_is_a_failed_edit(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    fake_mem(w, monkeypatch, EDIT_EXITS % 2)
    for n in (1, 2, 3):
        got = reword(w)
        assert (got["failed_edits"], got["written"], got["refused_code"], got["gave_up"]) == (1, 0, 0, 0)
        assert reword_state(w)["lessons"] == {} and reword_state(w)["failures"]["count"] == n
        assert by_claim(w, NARROW).reword_failed is None and by_claim(w, NARROW).short == OLD_WORDING
    before = calls(w)
    waiting = reword(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]


def test_a_forbidden_term_is_a_refusal(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    fake_mem(w, monkeypatch, EDIT_EXITS % 4)
    got = reword(w)
    assert (got["refused_code"], got["failed_edits"], got["written"]) == (1, 0, 0)
    (entry,) = reword_state(w)["lessons"].values()
    assert entry["count"] == 1 and reword_state(w)["failures"]["count"] == 0


def test_a_failed_give_up_is_retried_without_a_session(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, checker=False)
    marker = w.tmp / "failed-once"
    fake_mem(w, monkeypatch, f'case "$*" in *--reword-failed*) if [ ! -f {marker} ]; then touch {marker}; exit 2; fi;; esac')
    assert reword(w)["gave_up"] == 0
    second = reword(w)
    assert (second["refused_check"], second["gave_up"]) == (1, 0)
    assert list(reword_state(w)["lessons"].values())[0]["count"] == 2 and by_claim(w, NARROW).reword_failed is None
    before = calls(w)
    third = reword(w)
    assert third == {**NOTHING, "gave_up": 1} and calls(w) == before
    assert by_claim(w, NARROW).reword_failed == ago(10)
    assert reword(w) == NOTHING and calls(w) == before


def test_every_needs_dry_run(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    done = run(w, "--every", cmd="reword")
    assert done.returncode == 2 and "--dry-run" in done.stderr and calls(w) == 0
    assert by_claim(w, NARROW).short == OLD_WORDING and not (w.cdir / "reword-attempts.json").exists()


@pytest.mark.parametrize("content", ["[1, 2]", "not json", '"text"', '{"lessons": [], "failures": 5}',
                                     '{"lessons": {"k": 5, "j": []}, "failures": {"count": "x", "fingerprint": 3}}',
                                     '{"lessons": 7, "failures": []}'])
def test_a_broken_state_file_reads_as_empty(w, content):
    auto_state.private_dir(w.cdir)
    (w.cdir / "reword-attempts.json").write_text(content)
    got = corroborate_reword._reword_state(w.cdir)
    assert got["lessons"] == {} and got["failures"]["count"] == 0 and got["failures"]["fingerprint"] in (None, 3)


# ---- the option auto_reword: the step in the automatic run ---------------------------------------------------------

REWORD_OPTION = "CLAUDE_PLUGIN_OPTION_AUTO_REWORD"


def test_auto_runs_reword_only_with_the_option(w, monkeypatch):
    worse_one(w)
    model(w, [])
    reword_answers(w, monkeypatch)
    for env in ({}, {REWORD_OPTION: "false"}, {REWORD_OPTION: "1"}, {REWORD_OPTION: "TRUE"}):
        done = run(w, cmd="auto", env={OPTION: "true", **env})
        assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
        assert not any("reword" in x for x in log_lines(w)) and by_claim(w, NARROW).short == OLD_WORDING
        assert not (w.cdir / "reword-attempts.json").exists()
    off = [{k: v for k, v in x.items() if k not in ("t", "ms")} for x in log_lines(w)]
    done = run(w, cmd="auto", env={OPTION: "true", REWORD_OPTION: "true"})
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    lines = log_lines(w)
    (reworded,) = [x for x in lines if "reword" in x]
    assert lines[-1] is reworded and "fill" in lines[-2] and reworded["reword"]["written"] == 1
    assert isinstance(reworded["ms"], int) and reworded["t"]
    assert by_claim(w, NARROW).short == NEW_WORDING
    assert [{k: v for k, v in x.items() if k not in ("t", "ms")} for x in lines[:len(off)]] == off


def test_auto_skips_reword_when_loaded_rules_are_off(w, monkeypatch):
    worse_one(w)
    model(w, [])
    reword_answers(w, monkeypatch)
    for env in ({"MEM_LOADED_RULES": "off"}, {"CLAUDE_PLUGIN_OPTION_LOADED_RULES": "false"}):
        done = run(w, cmd="auto", env={OPTION: "true", REWORD_OPTION: "true", **env})
        assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
        assert not any("reword" in x for x in log_lines(w)) and by_claim(w, NARROW).short == OLD_WORDING


def test_auto_does_not_reword_without_auto_capture(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    done = run(w, cmd="auto", env={REWORD_OPTION: "true"})
    assert done.returncode == 0 and log_lines(w) == [] and by_claim(w, NARROW).short == OLD_WORDING


def test_a_failure_in_reword_does_not_fail_auto(w, monkeypatch):
    worse_one(w)
    model(w, [])

    def boom(*_args, **_kw):
        raise RuntimeError("the step broke")

    monkeypatch.setattr(corroborate_reword, "reword_auto", boom)
    monkeypatch.setenv(OPTION, "true")
    monkeypatch.setenv(REWORD_OPTION, "true")
    monkeypatch.setattr(sys, "argv", ["mem-corroborate", "auto", "--claude", str(w.fake)])
    assert corroborate_cli.cmd_auto(argparse.Namespace(claude=str(w.fake))) == 0
    lines = log_lines(w)
    assert any("fill" in x for x in lines) and not any("reword" in x for x in lines)


# ---- the option rules_layout: the digest step in the automatic run -------------------------------------------------

LAYOUT_OPTION = "CLAUDE_PLUGIN_OPTION_RULES_LAYOUT"


def test_auto_runs_digest_only_with_the_layout(w, monkeypatch):
    worse_one(w)
    model(w, [])
    for env in ({}, {LAYOUT_OPTION: "flat"}, {LAYOUT_OPTION: "grouped"}, {LAYOUT_OPTION: "DIGEST"}):
        done = run(w, cmd="auto", env={OPTION: "true", **env})
        assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
        assert not any("digest" in x for x in log_lines(w)) and not (w.data / "rules-digest.json").exists()
    for off in ({"MEM_LOADED_RULES": "off"}, {"CLAUDE_PLUGIN_OPTION_LOADED_RULES": "false"}):
        done = run(w, cmd="auto", env={OPTION: "true", LAYOUT_OPTION: "digest", **off})
        assert done.returncode == 0 and not any("digest" in x for x in log_lines(w))
    done = run(w, cmd="auto", env={OPTION: "true", LAYOUT_OPTION: "digest"})
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    lines = log_lines(w)
    (digested,) = [x for x in lines if "digest" in x]
    assert lines[-1] is digested and "fill" in lines[-2] and isinstance(digested["digest"], dict)
    assert isinstance(digested["ms"], int) and digested["t"]


def test_a_failure_in_digest_does_not_fail_auto(w, monkeypatch):
    worse_one(w)
    model(w, [])

    def boom(*_args, **_kw):
        raise RuntimeError("the step broke")

    monkeypatch.setattr(corroborate_digest, "digest_auto", boom)
    monkeypatch.setenv(OPTION, "true")
    monkeypatch.setenv(LAYOUT_OPTION, "digest")
    monkeypatch.setattr(sys, "argv", ["mem-corroborate", "auto", "--claude", str(w.fake)])
    assert corroborate_cli.cmd_auto(argparse.Namespace(claude=str(w.fake))) == 0
    lines = log_lines(w)
    assert any("fill" in x for x in lines) and not any("digest" in x for x in lines)


def test_auto_without_the_layout_is_as_before(w, monkeypatch):
    worse_one(w)
    model(w, [])
    reword_answers(w, monkeypatch)
    env = {OPTION: "true", REWORD_OPTION: "true"}
    run(w, cmd="auto", env=env)
    before = [{k: v for k, v in x.items() if k not in ("t", "ms")} for x in log_lines(w)]
    store = by_claim(w, NARROW).short
    assert [list(x) for x in before][-1] == ["reword"] and store == NEW_WORDING
    run(w, cmd="auto", env=env)
    after = [{k: v for k, v in x.items() if k not in ("t", "ms")} for x in log_lines(w)]
    assert after[:len(before)] == before and not any("digest" in x for x in after)
    assert by_claim(w, NARROW).short == store and not (w.data / "rules-digest.json").exists()


def test_plugin_json_has_the_option_off():
    config = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["userConfig"]
    assert config["auto_reword"]["type"] == "boolean" and config["auto_reword"].get("default") is False


def test_reword_sheet_is_refused_inside_a_repository(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    repo = w.tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    done = run(w, "--every", "--dry-run", "--sheet", str(repo / "sheet.md"), cmd="reword", mode="never")
    assert done.returncode == 2 and "repository" in done.stderr and "--sheet" in done.stderr
    assert calls(w) == 0 and not (repo / "sheet.md").exists()


class _Run:
    def __init__(self, code):
        self.returncode, self.stdout, self.stderr = code, "", "fake"


def _edit_exits(monkeypatch, code):
    """Every `mem memory edit --reworded` call ends with `code` (None: could not run) and writes nothing."""
    real = corroborate_run.Applier.mem

    def mem(self, args, *a, **kw):
        if "--reworded" in args:
            return None if code is None else _Run(code)
        return real(self, args, *a, **kw)

    monkeypatch.setattr(corroborate_run.Applier, "mem", mem)


@pytest.mark.parametrize("code", [None, 1, 2, 3])
def test_a_failed_edit_spends_no_attempt(w, monkeypatch, code):
    worse_one(w)
    reword_answers(w, monkeypatch)
    _edit_exits(monkeypatch, code)
    before = by_claim(w, NARROW)
    for _ in range(2):
        result = reword(w)
        assert (result["failed_edits"], result["written"], result["refused_code"], result["no_proposal"]) == (1, 0, 0, 0)
    assert by_claim(w, NARROW) == before and by_claim(w, NARROW).reword_failed is None
    assert reword_state(w)["lessons"] == {}


@pytest.mark.parametrize("code", [4])
def test_a_refused_edit_still_spends_an_attempt(w, monkeypatch, code):
    worse_one(w)
    reword_answers(w, monkeypatch)
    _edit_exits(monkeypatch, code)
    result = reword(w)
    assert (result["refused_code"], result["failed_edits"], result["written"]) == (1, 0, 0)
    (entry,) = reword_state(w)["lessons"].values()
    assert entry["count"] == 1 and not entry["spent"]


def test_an_unwritable_sheet_does_not_fail_an_applied_run(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    result = reword(w, sheet=w.tmp / "no-such-folder" / "sheet.md")
    assert result["written"] == 1 and by_claim(w, NARROW).short == NEW_WORDING
    assert "sheet" in result["stopped"] and result["stopped"] != "the step failed"
    assert reword_state(w)["lessons"]


# ---- digest_auto: a heading per topic and a line per lesson, written for the session start --------------------------

import digest  # noqa: E402
import mem  # noqa: E402

DG_TOPIC = "briefing"
DG_HEADING = "when briefing a subagent"
DG_LESSONS = [
    ("Give a subagent the check that tells it the task is done before it starts, as it may stop early otherwise.",
     "When briefing a subagent, giving it the acceptance check first may help."),
    ("Name the files a subagent may touch and the ones it must leave alone, as it may otherwise widen its scope.",
     "When briefing a subagent, naming the files it may touch may keep its scope narrow."),
    ("Ask a subagent for a report of a fixed length, as long reports may hide the one finding that matters.",
     "When reading a subagent's report, a fixed length may keep the finding visible."),
]
DG_LINES = ["giving it the acceptance check first may let it tell when it is done",
            "naming the files it may touch may keep it from widening its scope",
            "asking for a report of a fixed length may keep the one finding visible"]
DG_NEW_SHORT = "When briefing a subagent, stating the check it must pass first may help."


def digest_world(w):
    """Three ready global lessons of one topic, as the fill and the rewording leave them."""
    made = []
    for claim, short in DG_LESSONS:
        m = records.write_memory(w.gmem, "global", kind="lesson", claim=claim, body="b\n", today=TODAY, origin="transcript",
                                 reach="general", weight="light", topic=DG_TOPIC,
                                 sources=[f"session s5 project {records.project_key(w.pa)}",
                                          f"session s6 project {records.project_key(w.pb)}"])
        made.append(records.update(m, TODAY, short=short, short_by="model", triage=None))
    return made


def digest_lessons(w):
    return sorted((m for m in globals_(w) if m.topic == DG_TOPIC), key=lambda m: m.handle)


def digest_answers(w, mp, *, heading=DG_HEADING, lines=None, fits=True, unfaithful=(), writer="ok", checker="ok"):
    """The fake's two answers of the step. lines: claim -> line (default DG_LINES in the order of DG_LESSONS); unfaithful: claims
    the checker does not find faithful; writer/checker "ok", "none" (no file) or the file's text."""
    mp.delenv("FAKE_DIGEST", raising=False)
    mp.delenv("FAKE_DIGEST_CHECK", raising=False)
    by = {m.claim: m for m in digest_lessons(w)}
    texts = lines or {claim: line for (claim, _s), line in zip(DG_LESSONS, DG_LINES)}
    if writer == "ok":
        topic = {"topic": DG_TOPIC, "lines": [{"id": f"g:{by[c].handle}", "line": t} for c, t in texts.items()]}
        if heading is not None:
            topic["heading"] = heading
        writer = json.dumps({"topics": [topic]})
    if writer != "none":
        (w.tmp / "digest-answer.json").write_text(writer)
        mp.setenv("FAKE_DIGEST", str(w.tmp / "digest-answer.json"))
    if checker == "ok":
        checker = json.dumps({"verdicts": [{"id": f"g:{m.handle}", "reason": "the checker's reason", "fits": fits,
                                            "faithful": m.claim not in unfaithful} for m in by.values()]})
    if checker != "none":
        (w.tmp / "digest-check-answer.json").write_text(checker)
        mp.setenv("FAKE_DIGEST_CHECK", str(w.tmp / "digest-check-answer.json"))


def do_digest(w, **kw):
    return corroborate_digest.digest_auto(str(w.fake), 0.25, **kw)


def engine_digest():
    return digest.read(mem.data_dir(os.environ))   # the folder the session start resolves


def digest_state(w):
    return json.loads((w.cdir / "digest-attempts.json").read_text())


def asked(w, which):
    return Path(os.environ["FAKE_INPUTS"] + f"-digest-{which}").read_text()


DG_NOTHING = {"topics": 0, "headings_written": 0, "lines_written": 0, "refused_code": 0, "refused_check": 0, "missing": 0,
              "unjudged": 0, "cost": 0.0, "stopped": None}


def test_digest_writes_a_topic_the_engine_reads_as_fresh(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    before = snapshot(w)
    assert do_digest(w) == {**DG_NOTHING, "topics": 1, "headings_written": 1, "lines_written": 3, "cost": 0.06}
    assert calls(w) == 2
    lessons = digest_lessons(w)
    stored = engine_digest()
    assert stored["topics"][DG_TOPIC]["heading"] == DG_HEADING
    assert digest.heading(stored, DG_TOPIC, lessons) == DG_HEADING
    for m in lessons:
        want = DG_LINES[[c for c, _s in DG_LESSONS].index(m.claim)]
        assert digest.line(stored, DG_TOPIC, m, lessons) == want
    assert snapshot(w) == before   # no record is written
    assert (w.data / digest.FILE).exists() and digest_state(w)["failures"]["count"] == 0
    assert not (w.cdir / "runs").exists()   # no journal: nothing to undo


def test_a_refused_line_falls_back_and_is_tried_twice(w, monkeypatch):
    digest_world(w)
    refused = DG_LESSONS[0][0]
    digest_answers(w, monkeypatch, unfaithful=(refused,))
    first = do_digest(w)
    assert (first["headings_written"], first["lines_written"], first["refused_check"]) == (1, 2, 1)
    second = do_digest(w)
    assert (second["headings_written"], second["lines_written"], second["refused_check"]) == (0, 0, 1)
    before = calls(w)
    assert do_digest(w) == DG_NOTHING and calls(w) == before   # nothing left to ask
    lessons, stored = digest_lessons(w), engine_digest()
    for m in lessons:
        got = digest.line(stored, DG_TOPIC, m, lessons)
        assert got is None if m.claim == refused else got in DG_LINES


def test_a_reworded_lesson_gets_a_new_line_and_the_rest_keep_theirs(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    assert do_digest(w)["lines_written"] == 3
    first = engine_digest()
    target = next(m for m in digest_lessons(w) if m.claim == DG_LESSONS[1][0])
    records.update(target, TODAY, short=DG_NEW_SHORT)
    new_line = "stating the check it must pass first may let it tell when it is done"
    digest_answers(w, monkeypatch, heading=None, lines={DG_LESSONS[1][0]: new_line})
    assert do_digest(w) == {**DG_NOTHING, "topics": 1, "lines_written": 1, "cost": 0.06}
    text = asked(w, "write")
    assert text.count("do: write") == 1 and text.count("do: keep") == 2 and "heading (keep)" in text
    lessons, stored = digest_lessons(w), engine_digest()
    for m in lessons:
        if m.handle == target.handle:
            assert digest.line(stored, DG_TOPIC, m, lessons) == new_line
        else:
            assert stored["topics"][DG_TOPIC]["lines"][m.handle] == first["topics"][DG_TOPIC]["lines"][m.handle]
            assert digest.line(stored, DG_TOPIC, m, lessons) is not None


def test_an_unusable_answer_changes_nothing_and_three_in_a_row_wait(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, writer="this is not json")
    for n in (1, 2, 3):
        result = do_digest(w)
        assert result["stopped"] and result["headings_written"] == 0
        state = digest_state(w)
        assert state == {"tries": {}, "failures": {"count": n, "fingerprint": state["failures"]["fingerprint"]}}
    assert not (w.data / digest.FILE).exists()
    before = calls(w)
    waiting = do_digest(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]
    records.update(digest_lessons(w)[0], TODAY, claim="Give a subagent the check that tells it the task is done first, as it may help.")
    assert do_digest(w)["stopped"] != waiting["stopped"] and calls(w) == before + 1


def test_a_digest_checker_that_gives_no_usable_answer_is_a_failed_session(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, checker="none")
    result = do_digest(w)
    assert result["stopped"] and result["headings_written"] == 0 and calls(w) == 2
    assert not (w.data / digest.FILE).exists() and digest_state(w)["tries"] == {}
    assert digest_state(w)["failures"]["count"] == 1


def test_digest_dry_run_writes_the_sheet_and_nothing_else(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, unfaithful=(DG_LESSONS[2][0],))
    before = snapshot(w)
    sheet = w.tmp / "sheet.md"
    done = run(w, "--dry-run", "--sheet", str(sheet), cmd="digest")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["topics"] == 1 and calls(w) == 2
    assert snapshot(w) == before and not (w.data / digest.FILE).exists() and not (w.cdir / "digest-attempts.json").exists()
    rows = [x for x in sheet.read_text().splitlines() if x.startswith("| ") and "---" not in x][1:]
    assert len(rows) == 4 and sum("the checker's reason" in x for x in rows) == 3   # the heading has a row of its own
    assert any(DG_HEADING in x and DG_LINES[0] in x for x in rows) and sum("refused_check" in x for x in rows) == 1
    repo = w.tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    refused = run(w, "--dry-run", "--sheet", str(repo / "sheet.md"), cmd="digest", mode="never")
    assert refused.returncode == 2 and "repository" in refused.stderr and calls(w) == 2 and not (repo / "sheet.md").exists()


def test_digest_respects_the_lock(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    lock = auto_state.take_run_lock(w.cdir)
    try:
        result = do_digest(w)
    finally:
        os.close(lock)
    assert "run is going" in result["stopped"] and result["headings_written"] == 0 and calls(w) == 0
    assert not (w.data / digest.FILE).exists() and not (w.cdir / "digest-attempts.json").exists()


def test_an_unwritable_sheet_does_not_fail_an_applied_digest_run(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    result = do_digest(w, sheet=w.tmp / "no-such-folder" / "sheet.md")
    assert result["headings_written"] == 1 and "sheet" in result["stopped"] and result["stopped"] != "the step failed"
    assert engine_digest()["topics"][DG_TOPIC]["heading"] == DG_HEADING


def sheet_rows(path):
    return [[c.strip() for c in x.strip("|").split(" | ")] for x in path.read_text().splitlines()
            if x.startswith("| ") and "---" not in x][1:]


def test_the_sheet_has_a_row_for_a_heading_the_code_refused(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, heading="h" * 81)
    sheet = w.tmp / "sheet.md"
    result = do_digest(w, sheet=sheet)
    assert result["refused_code"] == 1 and result["headings_written"] == 0 and calls(w) == 1   # nothing for the checker
    rows = sheet_rows(sheet)
    assert len(rows) == 4
    head, *lines = rows
    assert head[0] == DG_TOPIC and head[1] == "h" * 81 and head[2] == "" and head[5] == "" and head[6] == "refused_code"
    assert "80" in head[7]
    assert all(r[2].startswith("g:") and r[6] == "unjudged" for r in lines)


def test_the_sheet_has_a_row_for_a_line_the_code_refused(w, monkeypatch):
    digest_world(w)
    bad = {DG_LESSONS[0][0]: "x" * 121, DG_LESSONS[1][0]: DG_LINES[1], DG_LESSONS[2][0]: DG_LINES[2]}
    digest_answers(w, monkeypatch, lines=bad)
    sheet = w.tmp / "sheet.md"
    result = do_digest(w, sheet=sheet)
    assert result["refused_code"] == 1 and result["lines_written"] == 2
    rows = sheet_rows(sheet)
    assert sorted(r[6] for r in rows) == ["refused_code", "written", "written", "written"]
    refused = next(r for r in rows if r[6] == "refused_code")
    assert refused[1] == DG_HEADING and refused[5] == "x" * 121 and "120" in refused[7]


def test_a_lesson_the_checker_left_out_is_not_judged_and_spends_no_try(w, monkeypatch):
    digest_world(w)
    by = {m.claim: m for m in digest_lessons(w)}
    only = by[DG_LESSONS[0][0]]
    verdict = json.dumps({"verdicts": [{"id": f"g:{only.handle}", "reason": "ok", "fits": True, "faithful": True}]})
    digest_answers(w, monkeypatch, checker=verdict)
    result = do_digest(w)
    assert result == {**DG_NOTHING, "topics": 1, "headings_written": 1, "lines_written": 1, "unjudged": 2, "cost": 0.06}
    assert digest_state(w)["tries"] == {}
    assert list(engine_digest()["topics"][DG_TOPIC]["lines"]) == [only.handle]
    # the two left out are asked again, as nothing was spent
    digest_answers(w, monkeypatch, heading=None)
    assert do_digest(w)["lines_written"] == 2


def test_a_run_with_nothing_to_write_still_prunes_and_starts_no_session(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    assert do_digest(w)["lines_written"] == 3
    data = mem.data_dir(os.environ)
    stored = engine_digest()
    stored["topics"]["vanished"] = {"heading": "when gone", "of": "x", "lines": {"h1": {"text": "t", "of": "o", "under": "x"}}}
    digest.write(data, stored)
    state = digest_state(w)
    state["tries"]["h:vanished@x"] = 1
    state["tries"]["l:old@x@y"] = 2
    (w.cdir / "digest-attempts.json").write_text(json.dumps(state))
    before = calls(w)
    assert do_digest(w) == DG_NOTHING and calls(w) == before
    assert list(engine_digest()["topics"]) == [DG_TOPIC] and digest_state(w)["tries"] == {}
    # a dry run prunes nothing
    stored["topics"]["vanished"] = {"heading": "when gone", "of": "x", "lines": {}}
    digest.write(data, stored)
    do_digest(w, apply=False)
    assert "vanished" in engine_digest()["topics"]


def test_a_run_that_writes_also_prunes(w, monkeypatch):
    digest_world(w)
    data = mem.data_dir(os.environ)
    digest.write(data, {"topics": {"vanished": {"heading": "when gone", "of": "x", "lines": {}}}})
    digest_answers(w, monkeypatch)
    assert do_digest(w)["headings_written"] == 1
    assert list(engine_digest()["topics"]) == [DG_TOPIC]


def test_a_digest_that_cannot_be_written_is_a_counted_failed_run(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    (w.data / digest.FILE).mkdir()   # the path is taken by a directory: the write fails
    for n in (1, 2, 3):
        before = calls(w)
        result = do_digest(w)
        assert calls(w) == before + 2 and result["stopped"] and "written" in result["stopped"] and result["headings_written"] == 0
        assert digest_state(w)["failures"]["count"] == n and digest_state(w)["tries"] == {}
    before = calls(w)
    waiting = do_digest(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]


def test_a_state_that_cannot_be_written_still_gives_a_result(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    w.cdir.mkdir(parents=True, exist_ok=True)
    w.cdir.mkdir(parents=True, exist_ok=True)
    (w.cdir / "digest-attempts.json").mkdir()
    result = do_digest(w)
    assert result["stopped"] and result["stopped"] != "the step failed"


# ---- an engine that cannot load: `auto` still reports, `status` and `ack` still work ---------------------------------

ENGINE_LOG_KEYS = ["t", "lessons", "groups", "proposed", "verified", "dropped", "written", "sightings", "links", "merges",
                   "refused", "failed_actions", "cases", "skipped", "cost", "failed", "ms"]


def test_auto_with_an_engine_that_cannot_load_writes_its_failed_status(w):
    plug = w.tmp / "plug-no-yaml"
    (plug / "bin").mkdir(parents=True)
    launcher = plug / "bin" / "mem-corroborate"
    shutil.copy(CORR, launcher)
    (plug / "engine").symlink_to(PLUGIN / "engine")
    stub = w.tmp / "stub"
    stub.mkdir()
    (stub / "yaml.py").write_text('raise ImportError("no yaml in this test")\n')
    env = {"PYTHONPATH": str(stub), OPTION: "true"}
    done = run(w, cmd="auto", env=env, corr=launcher)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    status = auto_state.read_json(w.cdir / "status.json")
    assert status["state"] == "failed" and status["failure"]["reason"] == "engine import error"
    log = [json.loads(x) for x in (w.cdir / "log.jsonl").read_text().splitlines()]
    assert len(log) == 1 and list(log[0]) == ENGINE_LOG_KEYS and log[0]["failed"] == "engine import error"
    shown = run(w, cmd="status", claude=False, env=env, corr=launcher)
    assert shown.returncode == 0 and "unacknowledged failure: engine import error" in shown.stdout
    assert run(w, cmd="ack", claude=False, env=env, corr=launcher).returncode == 0
    shown = run(w, cmd="status", claude=False, env=env, corr=launcher)
    assert shown.returncode == 0 and "unacknowledged" not in shown.stdout
    refused = run(w, "--dry-run", "--out", str(w.tmp / "o.json"), env=env, corr=launcher)
    assert refused.returncode == 1 and "cannot load the engine" in refused.stderr
