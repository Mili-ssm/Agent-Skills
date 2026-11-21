import json
import os
import subprocess
import time
from pathlib import Path

import pytest

MEM = Path(__file__).resolve().parents[2] / "bin" / "mem"

BLOCK = "Earlier text\nnot yet recorded: the cache key ignores the locale\nHANDOFF\ntask: add the retry\nstate: tests written\nnext: implement backoff\nverified: unit tests pass\nunverified: staging\nplan: docs/plans/p.md\n"


def run_compact(tmp_path, data, stdin=None):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "MEM_DATA": str(tmp_path / "d"),
           "XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(tmp_path / "share")}
    payload = stdin if stdin is not None else json.dumps(data)
    return subprocess.run([str(MEM), "compact-log", "--hook"], input=payload, env=env, capture_output=True, text=True)


def last_log(tmp_path):
    raw = (tmp_path / "d" / "hooks" / "log.jsonl").read_text().splitlines()[-1]
    return raw, json.loads(raw)


def project(tmp_path, plan=True):
    proj = tmp_path / "proj"
    (proj / "docs" / "plans").mkdir(parents=True)
    if plan:
        (proj / "docs" / "plans" / "p.md").write_text("- [ ] a\n")
    return proj


def test_logs_one_line_without_text(tmp_path):
    proj = project(tmp_path)
    r = run_compact(tmp_path, {"session_id": "abc-123", "trigger": "auto", "cwd": str(proj), "compact_summary": BLOCK})
    assert r.returncode == 0 and r.stdout == ""
    raw, entry = last_log(tmp_path)
    entry.pop("t"), entry.pop("ms")
    assert entry == {"hook": "post-compact", "trigger": "auto", "session": "abc-123", "chars": len(BLOCK), "marker": True,
                     "handoff": ["task", "state", "next", "verified", "unverified", "plan"], "plan_named": True,
                     "unrecorded": 1, "mismatches": 0}
    assert "retry" not in raw and "docs/plans" not in raw


def test_a_mismatch_is_printed(tmp_path):
    proj = project(tmp_path, plan=False)
    r = run_compact(tmp_path, {"session_id": "abc-123", "trigger": "auto", "cwd": str(proj), "compact_summary": BLOCK})
    out = r.stdout.strip("\n")
    assert r.returncode == 0 and "\n" not in out and "does not exist" in out and len(out) < 300
    assert last_log(tmp_path)[1]["mismatches"] == 1


@pytest.mark.parametrize("stdin", ["", "not json", "{}", '{"compact_summary": 5}'])
def test_bad_input_is_silent(tmp_path, stdin):
    r = run_compact(tmp_path, None, stdin=stdin)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    data = tmp_path / "d"
    assert not data.exists() or all(p.relative_to(data).parts[0] == "hooks" for p in data.rglob("*") if p.is_file())


def test_an_unsafe_session_id_is_logged_as_null(tmp_path):
    run_compact(tmp_path, {"session_id": "../x", "trigger": "manual", "cwd": str(project(tmp_path)), "compact_summary": BLOCK})
    assert last_log(tmp_path)[1]["session"] is None


def test_a_large_summary_stays_fast(tmp_path):
    started = time.monotonic()
    r = run_compact(tmp_path, {"session_id": "s", "cwd": str(project(tmp_path)), "compact_summary": "x" * 5_000_000})
    assert r.returncode == 0 and time.monotonic() - started < 2
    assert last_log(tmp_path)[1]["chars"] == 5_000_000


def test_free_text_in_the_trigger_is_not_logged(tmp_path):
    run_compact(tmp_path, {"session_id": "s", "trigger": "Keep the key sk-EXAMPLE here", "cwd": str(project(tmp_path)),
                           "compact_summary": BLOCK})
    raw, entry = last_log(tmp_path)
    assert entry["trigger"] is None and "sk-EXAMPLE" not in raw


def test_a_session_id_with_a_trailing_newline_is_logged_as_null(tmp_path):
    run_compact(tmp_path, {"session_id": "abc\n", "trigger": "manual", "cwd": str(project(tmp_path)), "compact_summary": BLOCK})
    assert last_log(tmp_path)[1]["session"] is None


def test_a_summary_without_a_block_prints_the_request(tmp_path):
    r = run_compact(tmp_path, {"session_id": "s", "trigger": "manual", "cwd": str(project(tmp_path)),
                               "compact_summary": "We fixed the parser and moved on."})
    assert r.returncode == 0 and r.stdout.count("\n") == 1 and "The summary has no handoff block" in r.stdout
    entry = last_log(tmp_path)[1]
    assert entry["handoff"] == [] and entry["mismatches"] == 1 and entry["marker"] is False
