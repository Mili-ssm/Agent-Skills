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
if os.environ.get("FAKE_COPY_RULES"):
    shutil.copy("rules.txt", os.environ["FAKE_COPY_RULES"])
if os.environ.get("FAKE_DELETE"):
    os.remove(os.environ["FAKE_DELETE"])
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
        "weight": "medium", "form": "recommendation",
        "claim": "Do not mock the database in this project's tests: a mock hid a broken migration.",
        "context": "when writing tests that touch storage", "evidence": "never mock the database in these tests", "same_as": None}
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
    monkeypatch.setenv("HOME", str(tmp_path / "home"))               # no real instruction file is ever read
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
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
    # the suite's conftest sets MEM_PROJECT to an isolated folder; mem-capture resolves --project like mem does, so drop it
    base = {k: v for k, v in os.environ.items() if k != "MEM_PROJECT"}
    return subprocess.run(cmd, env={**base, "FAKE_MODE": mode, **(env or {})}, capture_output=True, text=True)


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
    assert [l.split("\t") for l in copy.read_text().splitlines()][0][1] == claim
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
    rows = [l.split("\t") for l in copy.read_text().splitlines()]
    assert sorted(r[1] for r in rows) == sorted([live, glob])
    assert [r[0] for r in rows if r[1] == glob] == ["(general)"] and [r[0] for r in rows if r[1] == live][0].startswith("m:")
    assert all(not r[0].startswith("m:") or r[1] != gone for r in rows)


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


def lapsed_memory(w, claim, days_ago, origin="transcript"):
    import datetime
    import records
    today = datetime.date.today() - datetime.timedelta(days=days_ago + 30)
    m = records.write_memory(records.project_dir(w.project), "project", kind="lesson", claim=claim, body="b\n", today=today,
                             origin=origin, reach="project", weight="medium", sources=["session aaa"])
    return m


def recorded_of(w, *extra, env=None):
    copy = w.tmp / "recorded-copy.txt"
    assert run(w, *extra, env={"FAKE_COPY_RECORDED": str(copy), **(env or {})}).returncode == 0
    return copy.read_text()


def test_recorded_lines_hold_handles_for_the_project_only(world):
    handle = next(w for w in remember(world, claim="Always run the validator before a commit.").split()
                  if w.startswith("m:")).strip(".,;:")
    remember(world, "--global", claim="Briefs for subagents must carry their own acceptance criteria.")
    lines = recorded_of(world).splitlines()
    assert f"{handle}\tAlways run the validator before a commit." in lines
    assert "(general)\tBriefs for subagents must carry their own acceptance criteria." in lines


def test_a_lapsed_unconfirmed_transcript_memory_is_listed_and_an_old_one_is_not(world):
    m = lapsed_memory(world, "Pin the tool version in the lockfile before a release.", 10)
    old = lapsed_memory(world, "Rotate the log files on the weekly schedule here.", 200)
    assert m.valid_until is not None and old.valid_until is not None
    text = recorded_of(world)
    assert f"m:{m.handle}\tPin the tool version in the lockfile before a release." in text
    assert "Rotate the log files" not in text


def test_a_refuted_memory_is_not_listed_and_the_lapse_window_is_60_days(world):
    refuted = lapsed_memory(world, "Pin the tool version in the lockfile before a release.", 10)
    refuted.path.write_text(refuted.path.read_text().replace("status: active", "status: refuted"))
    recent = lapsed_memory(world, "Rotate the log files on the weekly schedule here.", 59)
    old = lapsed_memory(world, "Name the feature flags after their owner team.", 61)
    text = recorded_of(world)
    assert "Pin the tool version" not in text and "Name the feature flags" not in text
    assert f"m:{recent.handle}\tRotate the log files on the weekly schedule here." in text


def test_a_missing_project_folder_is_a_usage_error(world):
    world.project = world.tmp / "nowhere"
    done = run(world, mode="never")
    assert done.returncode == 2 and world.calls() == [] and len(done.stderr.splitlines()) == 1
    assert not world.out.exists()


def test_the_project_flag_wins_over_mem_project_and_only_its_name_is_recorded(world):
    other = world.tmp / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    subprocess.run(["git", "init", "-q", str(world.project)], check=True)
    remember(world, claim="Always run the validator before a commit.")
    base = {k: v for k, v in os.environ.items() if k != "MEM_PROJECT"}
    copy = world.tmp / "recorded-copy.txt"
    cmd = [sys.executable, "-I", str(CAPTURE), "run", "--transcript", str(world.transcript), "--out", str(world.out),
           "--project", str(world.project), "--claude", str(world.fake)]
    done = subprocess.run(cmd, env={**base, "MEM_PROJECT": str(other), "FAKE_MODE": "good",
                                    "FAKE_COPY_RECORDED": str(copy)}, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "Always run the validator" in copy.read_text()
    assert result(world)["project"] == "project"


def test_a_huge_instruction_file_is_read_only_up_to_the_cap(world, monkeypatch):
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("mem_capture_bin", str(CAPTURE))
    spec = importlib.util.spec_from_loader("mem_capture_bin", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    (world.project / "CLAUDE.md").write_text("x" * 100_000)
    seen = []
    real = Path.open
    def spy(self, *a, **k):
        f = real(self, *a, **k)
        if self.name == "CLAUDE.md":
            inner = f.read
            f.read = lambda n=-1: seen.append(n) or inner(n)
        return f
    monkeypatch.setattr(Path, "open", spy)
    text, cut = module.rules_text(world.project)
    assert cut and seen and all(0 < n <= module.RULES_LIMIT + 1 for n in seen)
    assert text.count("x") == module.RULES_LIMIT


def test_rules_hold_the_project_and_the_config_instruction_files(world):
    (world.project / "CLAUDE.md").write_text("Project rule: keep the changelog current.\n")
    (world.tmp / "config").mkdir()
    (world.tmp / "config" / "CLAUDE.md").write_text("Owner rule: answer in Spanish.\n")
    copy = world.tmp / "rules-copy.txt"
    assert run(world, env={"FAKE_COPY_RULES": str(copy)}).returncode == 0
    text = copy.read_text()
    assert text.index("## CLAUDE.md\nProject rule: keep the changelog current.") < text.index("## CLAUDE.md\nOwner rule: answer in Spanish.")
    r = result(world)["extract"]
    assert r["rules_chars"] == len(text) and r["rules_cut"] is False


def test_no_rules_leaves_the_file_empty_and_none_found_too(world):
    (world.project / "CLAUDE.md").write_text("Project rule: keep the changelog current.\n")
    copy = world.tmp / "rules-copy.txt"
    assert run(world, "--no-rules", env={"FAKE_COPY_RULES": str(copy)}).returncode == 0
    assert copy.read_text() == "" and result(world)["extract"]["rules_chars"] == 0
    (world.project / "CLAUDE.md").unlink()
    assert run(world, env={"FAKE_COPY_RULES": str(copy)}).returncode == 0
    assert copy.read_text() == ""


def test_a_huge_rules_file_is_cut(world):
    (world.project / "CLAUDE.md").write_text("x" * 100_000)
    copy = world.tmp / "rules-copy.txt"
    assert run(world, env={"FAKE_COPY_RULES": str(copy)}).returncode == 0
    text = copy.read_text()
    assert text.startswith("## CLAUDE.md\n") and text.rstrip("\n").endswith("\n[...] cut")
    assert text.count("x") == 30_000
    r = result(world)["extract"]
    assert r["rules_cut"] is True and r["rules_chars"] == len(text)


def test_a_subfolder_of_a_git_project_reads_that_projects_memories(world):
    subprocess.run(["git", "init", "-q", str(world.project)], check=True)
    sub = world.project / "src" / "deep"
    sub.mkdir(parents=True)
    remember(world, claim="Always run the validator before a commit.")
    world.project = sub
    assert "Always run the validator" in recorded_of(world)


def test_same_as_reaches_the_result_and_the_brief_names_the_files(world):
    claim = "Do not mock the database in this project's tests: a mock hid a broken migration."
    handle = next(w for w in remember(world, claim=claim).split() if w.startswith("m:")).strip(".,;:")
    world.cands.write_text(json.dumps([{**GOOD, "same_as": handle}]))
    assert run(world).returncode == 0
    assert result(world)["candidates"][0]["same_as"] == handle
    prompt = world.calls()[0]["args"][world.calls()[0]["args"].index("-p") + 1]
    assert "rules.txt" in prompt and '"same_as"' in prompt


# --- --write: code applies the kept candidates to the project's memory through bin/mem ---

CLAIM2 = "Pin the tool version in the lockfile: in one session an unpinned update broke the build."
OWNER2 = "Please pin the tool version in the lockfile, an unpinned update broke the build yesterday."
TWO = (OWNER, OWNER2, "run the suite again")
SECOND = {**GOOD, "claim": CLAIM2, "evidence": "pin the tool version in the lockfile", "context": "before a release"}
TOKEN = "ghp_" + "a" * 36   # built from parts: obviously fake


def go(w, cands, *extra, **kw):
    w.cands.write_text(json.dumps(cands))
    return run(w, "--write", *extra, **kw)


def mem(w, *args, stdin=None):
    env = {**os.environ, "MEM_PROJECT": str(w.project)}
    return subprocess.run([str(MEM), *args], env=env, capture_output=True, text=True, cwd=w.project, input=stdin)


def handle_of(out):
    return next(x for x in out.split() if x.startswith("m:")).strip(".,;:")


def written(w):
    return result(w)["written"]


def files(w):
    return sorted((w.project / ".memory").glob("*.md")) if (w.project / ".memory").is_dir() else []


def other_session(w, claim, origin=("--origin", "transcript"), weight="medium"):
    done = mem(w, "remember", "--kind=lesson", f"--claim={claim}", *origin, "--reach", "project", "--weight", weight,
               "--source", "session other", "--body-file", "-", stdin="Signal: x\n")
    assert done.returncode == 0, done.stderr
    return handle_of(done.stdout)


def test_a_new_lesson_is_written_with_its_fields(world):
    done = go(world, [GOOD])
    assert done.returncode == 0, done.stderr
    w = written(world)
    assert len(w) == 1 and w[0]["outcome"] == "remembered" and w[0]["reason"] is None
    assert w[0]["claim"] == GOOD["claim"][:80]
    listed = mem(world, "memories").stdout
    assert f"{w[0]['handle']}\t" in listed and "from transcript, unconfirmed" in listed and GOOD["claim"] in listed
    (path,) = files(world)
    text = path.read_text()
    assert "reach: project" in text and "weight: medium" in text and "session abc" in text
    assert "Signal: owner_correction\nForm: recommendation\nEvidence: “never mock the database in these tests”" in text
    assert done.stdout == "mem-capture: 1 kept, 0 dropped, lines 1-6, cost 0.030, written 1 new, 0 sightings, 0 skipped\n"


def test_same_as_adds_this_session_and_establishes_a_medium_record(world):
    handle = other_session(world, GOOD["claim"])
    before = files(world)
    done = go(world, [{**GOOD, "same_as": handle}])
    assert done.returncode == 0, done.stderr
    assert written(world) == [{"claim": GOOD["claim"][:80], "outcome": "sighting", "handle": handle, "reason": None}]
    assert files(world) == before
    text = before[0].read_text()
    assert "session abc" in text and "session other" in text and "Seen again (owner_correction)" in text
    assert "from transcript, unconfirmed" not in mem(world, "memories").stdout
    assert "written 0 new, 1 sightings, 0 skipped" in done.stdout


def test_a_second_run_counts_nothing_twice(world):
    first = go(world, [GOOD, SECOND], transcript_path=transcript(world.tmp / "sessions" / "abc.jsonl", TWO))
    assert first.returncode == 0, first.stderr
    handles = [x["handle"] for x in written(world)]
    assert [x["outcome"] for x in written(world)] == ["remembered", "remembered"]
    snapshot = {p.name: p.read_text() for p in files(world)}
    same_as = [{**GOOD, "same_as": handles[0]}, {**SECOND, "same_as": handles[1]}]
    for cands in (same_as, [GOOD, SECOND]):
        again = go(world, cands, transcript_path=world.transcript)
        assert again.returncode == 0, again.stderr
        assert [(x["outcome"], x["reason"]) for x in written(world)] == [("skipped", "this session already counted")] * 2
        assert {p.name: p.read_text() for p in files(world)} == snapshot
        assert "written 0 new, 0 sightings, 2 skipped" in again.stdout


def test_two_candidates_with_one_claim_count_once(world):
    assert go(world, [GOOD, {**GOOD}]).returncode == 0
    assert [(x["outcome"], x["reason"]) for x in written(world)] == \
        [("remembered", None), ("skipped", "this session already counted")]
    assert len(files(world)) == 1


def test_a_claim_the_owners_agent_wrote_by_hand_gains_this_session_once(world):
    remember(world, claim=GOOD["claim"])
    assert go(world, [GOOD]).returncode == 0
    assert [(x["outcome"], x["reason"]) for x in written(world)] == [("sighting", None)]
    after = files(world)[0].read_text()
    assert after.count("session abc") == 1
    assert go(world, [GOOD]).returncode == 0
    assert [(x["outcome"], x["reason"]) for x in written(world)] == [("skipped", "this session already counted")]
    assert files(world)[0].read_text() == after


def test_the_same_claim_from_another_session_without_same_as_is_a_sighting(world):
    handle = other_session(world, GOOD["claim"], weight="strong")
    assert go(world, [GOOD]).returncode == 0
    assert [(x["outcome"], x["handle"]) for x in written(world)] == [("sighting", handle)]
    assert "session abc" in files(world)[0].read_text() and len(files(world)) == 1


def test_a_secret_is_refused_and_the_next_candidate_is_still_written(world):
    secret = {**GOOD, "claim": f"Do not paste {TOKEN} into a test: it was leaked once in a log of this project."}
    done = go(world, [secret, SECOND], transcript_path=transcript(world.tmp / "sessions" / "abc.jsonl", TWO))
    assert done.returncode == 0, done.stderr
    r = result(world)
    if not r["candidates"] or r["candidates"][0]["claim"] != secret["claim"]:
        pytest.skip("capture.validate drops the token before it reaches --write")
    assert [(x["outcome"], x["reason"]) for x in written(world)] == \
        [("skipped", "refused: a secret"), ("remembered", None)]
    assert len(files(world)) == 1 and TOKEN not in files(world)[0].read_text()


def test_a_claim_starting_with_a_dash_is_written(world):
    dashed = {**GOOD, "claim": "- Do not mock the database in this project's tests: a mock hid a broken migration."}
    assert go(world, [dashed]).returncode == 0
    assert written(world)[0]["outcome"] == "remembered", written(world)


def test_a_subfolder_writes_into_the_project_roots_memory(world):
    subprocess.run(["git", "init", "-q", str(world.project)], check=True)
    sub = world.project / "src" / "deep"
    sub.mkdir(parents=True)
    root = world.project
    world.project = sub
    assert go(world, [GOOD]).returncode == 0
    assert written(world)[0]["outcome"] == "remembered"
    assert len(list((root / ".memory").glob("*.md"))) == 1 and not (sub / ".memory").exists()


def test_without_write_nothing_is_stored(world):
    done = run(world)
    assert done.returncode == 0, done.stderr
    assert "written" not in result(world) and files(world) == [] and "written" not in done.stdout


def test_a_failing_mem_is_a_skipped_outcome_and_not_a_failed_run(world):
    (world.project / ".memory").write_text("a file where the memory folder should be")
    done = go(world, [GOOD, SECOND], transcript_path=transcript(world.tmp / "sessions" / "abc.jsonl", TWO))
    assert done.returncode == 0, done.stderr
    assert [(x["outcome"], x["handle"]) for x in written(world)] == [("skipped", None)] * 2
    assert all(x["reason"].startswith("mem failed (") for x in written(world))
    assert "written 0 new, 0 sightings, 2 skipped" in done.stdout


def test_a_sighting_never_lands_on_a_global_record(world):
    remember(world, claim=GOOD["claim"])
    (project_file,) = files(world)
    gmem = Path(os.environ["MEM_MEMORIES"])
    import records
    import datetime
    g = records.write_memory(gmem, "global", kind="lesson", claim=GOOD["claim"], body="", today=datetime.date.today())
    assert g.handle == project_file.stem
    before = g.path.read_text()
    done = go(world, [GOOD], env={"FAKE_DELETE": str(project_file)})   # the record leaves the project after validation
    assert done.returncode == 0, done.stderr
    assert [(x["outcome"], x["reason"]) for x in written(world)] == \
        [("skipped", "not a memory of this project any more")]
    assert g.path.read_text() == before and files(world) == []


def test_one_odd_candidate_does_not_stop_the_run(world):
    third = {**GOOD, "claim": "Keep the fixtures small: a huge one made the suite crawl for a week.",
             "evidence": "keep the fixtures small, they were slow", "context": "slow suite"}
    odd = {**SECOND, "claim": CLAIM2 + " \ud800"}
    owners = (OWNER, OWNER2, "Also keep the fixtures small, they were slow last week.")
    done = go(world, [GOOD, odd, third], transcript_path=transcript(world.tmp / "sessions" / "abc.jsonl", owners))
    assert done.returncode == 0, done.stderr
    assert [x["outcome"] for x in written(world)] == ["remembered", "remembered", "remembered"]
    assert len(files(world)) == 3
