"""`bin/mem-capture run`: the offline trial of capture from a transcript, with a fake `claude` and invented transcripts."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import capture

PLUGIN = Path(__file__).resolve().parents[2]
CAPTURE = PLUGIN / "bin" / "mem-capture"
MEM = PLUGIN / "bin" / "mem"

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")

FAKE = """#!/usr/bin/env python3
import json, os, shutil, sys
mode = os.environ.get("FAKE_MODE", "good")
if mode == "never":
    sys.exit("the fake must not be called")
settings = sys.argv[sys.argv.index("--settings") + 1]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "files": sorted(os.listdir(".")),
                        "settings": open(settings).read()}) + "\\n")
if os.environ.get("FAKE_COPY_RECORDED"):
    shutil.copy("recorded.txt", os.environ["FAKE_COPY_RECORDED"])
if mode == "good":
    shutil.copy(os.environ["FAKE_CANDIDATES"], "candidates.json")
elif mode == "badjson":
    open("candidates.json", "w").write("not json")
if mode == "exit1":
    sys.exit(1)
print(json.dumps({"type": "result", "is_error": False, "result": "done", "total_cost_usd": 0.03}))
"""

OWNER = "No, never mock the database in these tests because a mock hid a broken migration last month."
GOOD = {"kind": "lesson", "signal": "owner_correction", "reach": "project",
        "claim": "Do not mock the database in this project's tests: a mock hid a broken migration.",
        "context": "when writing tests that touch storage", "evidence": "never mock the database in these tests"}
PARAPHRASE = {**GOOD, "claim": "Prefer a real database over a mock when testing storage code here.",
              "evidence": "the owner asked us to stop mocking the database"}


def entry(kind, content):
    return {"type": kind, "message": {"content": content}}


def transcript(path, owners=(OWNER, "ok, continue", "run the suite again")):
    lines = []
    for text in owners:
        lines += [entry("user", text), entry("assistant", [{"type": "text", "text": "Working on it."}])]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    fake = tmp_path / "fake-claude"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps([GOOD, PARAPHRASE]))
    monkeypatch.setenv("FAKE_CALLS", str(tmp_path / "calls"))
    monkeypatch.setenv("FAKE_CANDIDATES", str(cands))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))   # never the real global memories
    (tmp_path / "tmp").mkdir()

    class World:
        pass

    w = World()
    w.tmp, w.fake, w.cands = tmp_path, fake, cands
    (tmp_path / "sessions").mkdir()
    w.transcript = transcript(tmp_path / "sessions" / "abc.jsonl")
    w.out = tmp_path / "results" / "deep" / "out.json"
    w.project = tmp_path / "project"
    w.project.mkdir()
    w.calls = lambda: [json.loads(x) for x in (tmp_path / "calls").read_text().splitlines()] \
        if (tmp_path / "calls").exists() else []
    return w


def run(w, *extra, mode="good", env=None, transcript_path=None):
    cmd = [sys.executable, "-I", str(CAPTURE), "run", "--transcript", str(transcript_path or w.transcript),
           "--out", str(w.out), "--project", str(w.project), "--claude", str(w.fake), *extra]
    return subprocess.run(cmd, env={**os.environ, "FAKE_MODE": mode, **(env or {})}, capture_output=True, text=True)


def result(w):
    return json.loads(w.out.read_text())


def test_run_writes_validated_candidates(world):
    done = run(world)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "mem-capture: 1 kept, 1 dropped, lines 1-6, cost 0.030\n"
    r = result(world)
    assert r["candidates"] == [{**GOOD}] and [d["reason"] for d in r["dropped"]] == ["evidence not in the transcript"]
    assert r["transcript"] == "abc.jsonl" and r["lines"] == [1, 6] and r["model"] == "haiku" and r["reason"] is None
    assert r["cost"] == pytest.approx(0.03)
    assert r["extract"]["parts"] == 1 and r["extract"]["cut"] is False and r["extract"]["lines"]["OWNER"] == 3
    assert (world.out.stat().st_mode & 0o777) == 0o600
    assert (world.out.parent.stat().st_mode & 0o777) == 0o700
    assert (world.out.parent.parent.stat().st_mode & 0o777) == 0o700


def test_the_session_gets_no_bash_and_no_hooks(world):
    assert run(world).returncode == 0
    assert run(world, "--model", "sonnet", "--budget", "0.75").returncode == 0
    first, second = world.calls()
    args = first["args"]
    work = first["cwd"]
    disallowed = args[args.index("--disallowedTools") + 1:args.index("--output-format")]
    assert {"Bash", "WebSearch", "WebFetch"} <= set(disallowed)
    allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
    assert [t.split("(")[0] for t in allowed] == ["Read", "Write", "Edit"] and all(work in t for t in allowed)
    assert json.loads(first["settings"])["disableAllHooks"] is True
    assert args[args.index("--model") + 1] == "haiku" and args[args.index("--max-budget-usd") + 1] == "0.2500"
    prompt = args[args.index("-p") + 1]
    assert f"Files in {work}:" in prompt and "{work}" not in prompt
    assert second["args"][second["args"].index("--model") + 1] == "sonnet"
    assert second["args"][second["args"].index("--max-budget-usd") + 1] == "0.7500"
    assert result(world)["model"] == "sonnet"


def test_a_long_extract_is_given_in_parts(world):
    transcript(world.transcript, [f"{i} " + "x" * 1900 for i in range(30)] + [OWNER])
    assert run(world).returncode == 0
    call = world.calls()[0]
    assert {"extract-1.txt", "extract-2.txt", "recorded.txt"} <= set(call["files"])
    assert result(world)["extract"]["parts"] == 2


def test_recorded_claims_reach_the_work_folder(world):
    claim = "Always run the validator before a commit."
    env = {**os.environ, "MEM_PROJECT": str(world.project)}
    done = subprocess.run([str(MEM), "remember", "--kind", "lesson", "--claim", claim], env=env, capture_output=True,
                          text=True, cwd=world.project)
    assert done.returncode == 0, done.stderr
    copy = world.tmp / "recorded-copy.txt"
    assert run(world, env={"FAKE_COPY_RECORDED": str(copy)}).returncode == 0
    assert copy.read_text().splitlines() == [claim]
    other = world.tmp / "other"
    other.mkdir()
    world.project = other
    assert run(world, env={"FAKE_COPY_RECORDED": str(copy)}).returncode == 0
    assert copy.read_text() == ""


def test_a_short_session_is_not_sent(world):
    transcript(world.transcript, [OWNER, "go on"])
    done = run(world, mode="never")
    assert done.returncode == 0, done.stderr
    r = result(world)
    assert r["reason"] == "too short" and r["candidates"] == [] and r["cost"] is None and world.calls() == []


@pytest.mark.parametrize("mode", ["nothing", "badjson", "exit1", "missing"])
def test_failures_write_a_reason(world, mode):
    path = world.tmp / "nope.jsonl" if mode == "missing" else None
    done = run(world, mode="good" if mode == "missing" else mode, transcript_path=path)
    assert done.returncode == 1 and len(done.stderr.splitlines()) == 1 and done.stdout == ""
    r = result(world)
    assert r["reason"] and r["candidates"] == [] and r["dropped"] == [] and (world.out.stat().st_mode & 0o777) == 0o600
    assert r["transcript"] == ("nope.jsonl" if mode == "missing" else "abc.jsonl")


def test_the_work_folder_is_removed(world):
    assert run(world).returncode == 0
    work = Path(world.calls()[0]["cwd"])
    assert not work.exists() and not work.parent.exists() and list((world.tmp / "tmp").iterdir()) == []
    assert run(world, "--keep-work").returncode == 0
    kept = Path(world.calls()[1]["cwd"])
    assert (kept / "candidates.json").is_file() and (kept.stat().st_mode & 0o777) == 0o700


def remember(w, *extra, claim):
    env = {**os.environ, "MEM_PROJECT": str(w.project)}
    done = subprocess.run([str(MEM), "remember", "--kind", "lesson", "--claim", claim, *extra], env=env,
                          capture_output=True, text=True, cwd=w.project)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_retired_memories_are_not_recorded_and_global_ones_are(world):
    live, gone, glob = ("Always run the validator before a commit.", "Never bump the version outside a release.",
                        "Briefs for subagents must carry their own acceptance criteria.")
    remember(world, claim=live)
    out = remember(world, claim=gone)
    handle = next(w for w in out.split() if w.startswith("m:")).strip(".,;:")
    env = {**os.environ, "MEM_PROJECT": str(world.project)}
    done = subprocess.run([str(MEM), "forget", handle, "--because", "no longer true"], env=env, capture_output=True,
                          text=True, cwd=world.project)
    assert done.returncode == 0, done.stderr
    remember(world, "--global", claim=glob)
    copy = world.tmp / "recorded-copy.txt"
    assert run(world, env={"FAKE_COPY_RECORDED": str(copy)}).returncode == 0
    assert sorted(copy.read_text().splitlines()) == sorted([live, glob])


def test_a_symlinked_out_is_refused_and_its_target_untouched(world):
    target = world.tmp / "precious.txt"
    target.write_text("keep me")
    world.out = world.tmp / "link.json"
    world.out.symlink_to(target)
    done = run(world)
    assert done.returncode == 1 and len(done.stderr.splitlines()) == 1 and done.stdout == ""
    assert target.read_text() == "keep me" and world.calls() == []


def test_an_existing_regular_out_is_replaced_with_mode_0600(world):
    world.out.parent.mkdir(parents=True)
    world.out.write_text("old")
    world.out.chmod(0o644)
    assert run(world).returncode == 0
    assert (world.out.stat().st_mode & 0o777) == 0o600 and result(world)["transcript"] == "abc.jsonl"


@pytest.mark.parametrize("claude", ["/nope/claude", "NOT-EXEC"])
def test_a_missing_or_non_executable_claude_writes_a_reason(world, claude):
    if claude == "NOT-EXEC":
        claude = world.tmp / "plain"
        claude.write_text("x")
        claude.chmod(0o644)
    world.fake = claude
    done = run(world)
    assert done.returncode == 1 and len(done.stderr.splitlines()) == 1 and "Traceback" not in done.stderr
    r = result(world)
    assert r["reason"] and r["candidates"] == [] and r["cost"] is None


def test_out_inside_a_repository_is_refused(world):
    (world.tmp / "repo" / ".git").mkdir(parents=True)
    world.out = world.tmp / "repo" / "sub" / "out.json"
    done = run(world)
    assert done.returncode == 1 and len(done.stderr.splitlines()) == 1 and done.stdout == ""
    assert not world.out.exists() and not world.out.parent.exists() and world.calls() == []


def test_a_large_candidates_file_is_not_read(world):
    world.cands.write_text(json.dumps([{**GOOD, "context": "x" * 1_000_001}]))
    done = run(world)
    assert done.returncode == 1 and len(done.stderr.splitlines()) == 1
    assert result(world)["reason"] == "candidates file too large"


@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1", "abc"])
def test_a_bad_budget_is_a_usage_error(world, value):
    done = run(world, "--budget", value, mode="never")
    assert done.returncode == 2 and world.calls() == [] and not world.out.exists()


def test_unprocessable_lines_are_counted(world):
    with world.transcript.open("a", encoding="utf-8") as f:
        f.write("[" * 100_000 + "\n")
    assert run(world).returncode == 0
    assert result(world)["extract"]["skipped"] == 1
