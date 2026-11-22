"""`bin/mem-capture auto` and `ack`: the background capture, with a fake `claude` and invented transcripts."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import auto_state
import capture
import capture_state
from test_mem_capture import FAKE, GOOD, OWNER, entry

PLUGIN = Path(__file__).resolve().parents[2]
CAPTURE = PLUGIN / "bin" / "mem-capture"
MEM = PLUGIN / "bin" / "mem"

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")

SECOND = {**GOOD, "claim": "Keep the fixtures small: the large ones made the suite slow last week.",
          "evidence": "the large ones are slow"}


def lines_for(spec, start=0, pad=0):
    """One JSONL line per letter: O is an owner line (`pad` characters longer), A an assistant line."""
    out = []
    for i, kind in enumerate(spec, start):
        if kind == "O":
            out.append(entry("user", (OWNER if i == 0 else f"{OWNER} (point {i})") + " x" * (pad // 2)))
        else:
            out.append(entry("assistant", [{"type": "text", "text": f"Working on item {i}."}]))
    return "".join(json.dumps(x) + "\n" for x in out)


def build(path, spec):
    path.write_text(lines_for(spec), encoding="utf-8")
    return path


def append(path, spec):
    with path.open("a", encoding="utf-8") as f:
        f.write(lines_for(spec, len(path.read_text().splitlines())))


@pytest.fixture
def world(tmp_path, monkeypatch):
    fake = tmp_path / "fake-claude"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps([GOOD]))
    monkeypatch.setenv("FAKE_CALLS", str(tmp_path / "calls"))
    monkeypatch.setenv("FAKE_CANDIDATES", str(cands))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MEM_CAPTURE_DELAY", "0")
    (tmp_path / "tmp").mkdir()

    class World:
        pass

    w = World()
    w.tmp, w.fake, w.cands = tmp_path, fake, cands
    w.data = Path(os.environ["MEM_DATA"])
    w.cdir = capture_state.capture_dir(w.data)
    w.project = tmp_path / "project"
    w.project.mkdir()
    subprocess.run(["git", "init", "-q", str(w.project)], check=True)
    mem(w, "remember", "--kind", "lesson", "--claim", "Always run the validator before a commit.")
    (tmp_path / "sessions").mkdir()
    w.transcript = build(tmp_path / "sessions" / "abc.jsonl", "OAOAOAOAOAAA")   # 12 lines, 4 owner lines
    w.calls = lambda: [json.loads(x) for x in (tmp_path / "calls").read_text().splitlines()] \
        if (tmp_path / "calls").exists() else []
    return w


def env_of(w, option="true", mode="good", extra=None, project=True):
    base = {k: v for k, v in os.environ.items() if k not in ("MEM_PROJECT", capture_state.OPTION)}
    if option is not None:
        base[capture_state.OPTION] = option
    return {**base, "FAKE_MODE": mode, **(extra or {})}


def mem(w, *args, env=None):
    done = subprocess.run([str(MEM), *args], env={**os.environ, "MEM_PROJECT": str(w.project), **(env or {})},
                          capture_output=True, text=True, cwd=w.project)
    assert done.returncode == 0, done.stderr
    return done.stdout


def hook(w, cwd=None, transcript=None):
    return json.dumps({"transcript_path": str(transcript or w.transcript), "cwd": str(cwd or w.project)})


def auto(w, trigger="session-end", stdin=None, python=(sys.executable, "-I"), **kw):
    cmd = [*python, str(CAPTURE), "auto", "--trigger", trigger, "--claude", str(w.fake)]
    return subprocess.run(cmd, input=hook(w) if stdin is None else stdin, env=env_of(w, **kw), capture_output=True,
                          text=True, timeout=120)


def status(w):
    return auto_state.read_json(w.cdir / "status.json")


def log_lines(w):
    path = w.cdir / "log.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def offset_of(w, transcript=None):
    return capture_state.read_session(w.data, (transcript or w.transcript).stem)["offset"]


def window(w, n=1):
    return json.loads((Path(status(w)["log"]) / f"window-{n}.json").read_text())


def set_cands(w, items):
    w.cands.write_text(json.dumps(items))


def test_off_by_default(world):
    done = auto(world, option=None)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    assert not world.cdir.exists() and world.calls() == []
    assert auto(world, option="yes").returncode == 0 and not world.cdir.exists()


def test_first_run_writes_and_saves_offset(world):
    done = auto(world)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    listing = mem(world, "memories")
    assert GOOD["claim"] in listing and "from transcript, unconfirmed" in listing
    assert offset_of(world) == 12 and status(world)["state"] == "ok"
    (line,) = log_lines(world)
    assert line["windows"] == 1 and line["written"]["remembered"] == 1 and line["trigger"] == "session-end"
    assert (world.cdir.stat().st_mode & 0o777) == 0o700 and ((world.cdir / "status.json").stat().st_mode & 0o777) == 0o600
    assert (Path(status(world)["log"]) / "log.txt").is_file()


def test_second_run_reads_only_new_lines(world):
    assert auto(world).returncode == 0
    append(world.transcript, "OAOAOA")
    assert auto(world).returncode == 0
    assert window(world)["lines"] == [13, 18] and len(world.calls()) == 2 and offset_of(world) == 18


def test_same_session_twice_adds_no_sighting(world):
    assert auto(world).returncode == 0
    handle = window(world)["written"][0]["handle"]
    append(world.transcript, "OAOAOA")
    set_cands(world, [{**GOOD, "same_as": handle}])
    assert auto(world).returncode == 0
    assert len(world.calls()) == 2
    shown = mem(world, "show", handle)
    assert shown.count("session abc") == 1, shown


def test_short_remainder_keeps_offset(world):
    assert auto(world).returncode == 0
    append(world.transcript, "OA")
    assert auto(world).returncode == 0
    assert offset_of(world) == 12 and len(world.calls()) == 1
    append(world.transcript, "OAOAOA")
    assert auto(world).returncode == 0
    assert window(world)["lines"] == [13, 20] and len(world.calls()) == 2 and offset_of(world) == 20


def test_long_stretch_stops_at_max_windows(world):
    world.transcript.write_text(lines_for("O" * 220, pad=1900))
    set_cands(world, [])
    assert auto(world).returncode == 0
    assert len(world.calls()) == 3
    assert offset_of(world) == window(world, 3)["lines"][1] < 220
    assert log_lines(world)[-1]["more"] is True and log_lines(world)[-1]["windows"] == 3
    stopped = offset_of(world)
    assert auto(world).returncode == 0
    assert len(world.calls()) > 3 and window(world)["lines"][0] == stopped + 1


def test_stops_after_five_new_records(world):
    world.transcript.write_text(lines_for("O" * 220, pad=1900))
    words = ["alpha", "bravo", "charlie", "delta", "echo"]
    set_cands(world, [{**GOOD, "claim": f"Never mock the {w} database layer in tests, a mock hid a broken migration.",
                       "evidence": "never mock the database in these tests"} for w in words])
    assert auto(world).returncode == 0
    assert len(world.calls()) == 1
    line = log_lines(world)[-1]
    assert line["written"]["remembered"] == 5 and line["more"] is True


def test_full_window_without_owner_lines_advances(world):
    text = "".join(json.dumps(entry("assistant", [{"type": "text", "text": f"{i} " + "y" * 1900}])) + "\n"
             for i in range(100))
    world.transcript.write_text(text)
    first = capture.extract(world.transcript, 0, True)[1]
    assert first < 100
    with world.transcript.open("a") as f:
        f.write(lines_for("OAOAOA", 100))
    set_cands(world, [])
    assert auto(world).returncode == 0
    assert len(world.calls()) == 1 and window(world, 2)["lines"][0] == first + 1


def test_failure_leaves_a_line_and_keeps_offset(world):
    done = auto(world, mode="exit1")
    assert done.returncode == 0
    saved = capture_state.read_session(world.data, "abc")
    assert saved == {"offset": 0, "attempts": 1}
    assert status(world)["state"] == "failed"
    assert capture_state.failure_line(world.data, time.time()).startswith("Automatic capture failed on")
    ack = subprocess.run([sys.executable, "-I", str(CAPTURE), "ack"], env=env_of(world), capture_output=True, text=True)
    assert ack.returncode == 0 and capture_state.failure_line(world.data, time.time()) is None


def test_second_failure_skips_the_window(world):
    assert auto(world, mode="badjson").returncode == 0
    assert auto(world, mode="badjson").returncode == 0
    assert capture_state.read_session(world.data, "abc") == {"offset": 12, "attempts": 0}
    assert log_lines(world)[-1]["given_up"] == 1
    append(world.transcript, "OAOAOA")
    assert auto(world).returncode == 0
    assert window(world)["lines"] == [13, 18]


def test_mem_failure_is_a_failed_window(world):
    shims = world.tmp / "shims"   # everything the run needs except uv, so `bin/mem` exits 127
    shims.mkdir()
    for tool in ("bash", "env", "python3", "git", "dirname", "readlink"):
        (shims / tool).symlink_to(shutil.which(tool))
    done = auto(world, extra={"PATH": str(shims)})
    assert done.returncode == 0
    assert offset_of(world) == 0 and capture_state.read_session(world.data, "abc")["attempts"] == 1
    assert capture_state.failure_line(world.data, time.time()).startswith("Automatic capture failed on")


def test_no_memory_folder_skips(world):
    other = world.tmp / "bare"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    done = auto(world, stdin=hook(world, cwd=other))
    assert done.returncode == 0 and world.calls() == [] and not (other / ".memory").exists()
    assert log_lines(world)[-1]["skipped"] == "the project has no memory folder"
    assert capture_state.failure_line(world.data, time.time()) is None


def test_cwd_outside_a_project_skips(world):
    plain = world.tmp / "plain"
    plain.mkdir()
    done = auto(world, stdin=hook(world, cwd=plain))
    assert done.returncode == 0 and world.calls() == []
    assert log_lines(world)[-1]["skipped"] == "the project has no memory folder"
    assert capture_state.failure_line(world.data, time.time()) is None


@pytest.mark.parametrize("stdin", ["", "[]", "not json"])
def test_bad_input_is_quiet(world, stdin):
    done = auto(world, stdin=stdin)
    assert done.returncode == 0 and done.stdout == "" and not world.cdir.exists()


def test_a_missing_transcript_is_quiet(world):
    done = auto(world, stdin=hook(world, transcript=world.tmp / "nope.jsonl"))
    assert done.returncode == 0 and not world.cdir.exists() and world.calls() == []


def test_shrunk_transcript_resets_offset(world):
    capture_state.save_session(world.data, "abc", 50, 1)
    assert auto(world).returncode == 0
    assert window(world)["lines"] == [1, 12] and offset_of(world) == 12


def test_lock_wait_gives_up(world):
    fd = auto_state.take_run_lock(world.cdir)
    try:
        done = auto(world, extra={"MEM_CAPTURE_LOCK_WAIT": "1"})
    finally:
        os.close(fd)
    assert done.returncode == 0 and world.calls() == []
    assert log_lines(world)[-1]["skipped"] == "another capture is running"


def test_waits_for_the_lock_then_continues(world):
    fd = auto_state.take_run_lock(world.cdir)
    cmd = [sys.executable, "-I", str(CAPTURE), "auto", "--trigger", "session-end", "--claude", str(world.fake)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, env=env_of(world, extra={"MEM_CAPTURE_LOCK_WAIT": "20"}),
                            text=True)
    proc.stdin.write(hook(world))
    proc.stdin.close()
    time.sleep(2)
    os.close(fd)
    assert proc.wait(timeout=60) == 0
    assert offset_of(world) == 12 and len(world.calls()) == 1


def test_pre_compact_waits_before_reading(world):
    cmd = [sys.executable, "-I", str(CAPTURE), "auto", "--trigger", "pre-compact", "--claude", str(world.fake)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, env=env_of(world, extra={"MEM_CAPTURE_DELAY": "4"}), text=True)
    proc.stdin.write(hook(world))
    proc.stdin.close()
    mem(world, "remember", "--kind", "lesson", "--claim", GOOD["claim"])
    assert proc.wait(timeout=60) == 0
    # the memory written during the wait was read: the identical claim is a sighting of it, not a second record
    assert [c["same_as"] for c in window(world)["candidates"]] == ["m:do-not-mock-the-database-in-this-project"]
    assert log_lines(world)[-1]["trigger"] == "pre-compact" and log_lines(world)[-1]["written"]["remembered"] == 0


def test_engine_import_failure_is_reported(world):
    shadow = world.tmp / "shadow"
    shadow.mkdir()
    (shadow / "yaml.py").write_text("raise ImportError('shadowed for the test')\n")
    done = subprocess.run([sys.executable, str(CAPTURE), "auto", "--trigger", "session-end", "--claude", str(world.fake)],
                          input=hook(world), env={**env_of(world), "PYTHONPATH": str(shadow)}, capture_output=True,
                          text=True)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    assert "cannot load the engine" in capture_state.failure_line(world.data, time.time())
    assert status(world)["state"] == "failed"
    run = subprocess.run([sys.executable, str(CAPTURE), "run", "--transcript", str(world.transcript), "--out",
                          str(world.tmp / "o.json")], env={**env_of(world), "PYTHONPATH": str(shadow)},
                         capture_output=True, text=True)
    assert run.returncode == 1 and "cannot load the engine" in run.stderr


def test_data_folder_inside_a_repository_works(world, monkeypatch):
    repo = world.tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("MEM_DATA", str(repo / "data"))
    world.data = repo / "data"
    world.cdir = capture_state.capture_dir(world.data)
    assert auto(world).returncode == 0
    assert status(world)["state"] == "ok" and window(world)["reason"] is None and offset_of(world) == 12


def test_log_line_has_no_text(world):
    assert auto(world).returncode == 0
    raw = (world.cdir / "log.jsonl").read_text()
    assert GOOD["claim"][:30] not in raw and "never mock" not in raw and str(world.tmp) not in raw


def test_session_index_shows_the_failure_line(world):
    assert auto(world, mode="exit1").returncode == 0
    assert "Automatic capture failed on" in mem(world, "session-index")
    ack = subprocess.run([sys.executable, "-I", str(CAPTURE), "ack"], env=env_of(world), capture_output=True, text=True)
    assert ack.returncode == 0
    assert "Automatic capture failed on" not in mem(world, "session-index")
