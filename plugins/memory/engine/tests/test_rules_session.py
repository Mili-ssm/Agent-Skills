import datetime
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import mem
import records
import rules

PLUGIN = Path(__file__).resolve().parents[2]
K1, K2 = "0123456789ab", "ba9876543210"
LINE1 = "memory: the mem command searches notes and memories (skill: memory)."


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root


def write(claim, *, short=None, weight="light", scope="global", confirm=True):
    """A transcript lesson; a global one is confirmed by the owner and accepted, so it loads when it has a short form."""
    args = ["remember", "--kind", "lesson", "--claim", claim, "--origin", "transcript", "--weight", weight,
            "--reach", "general", "--source", f"session a project {K1}", "--source", f"session b project {K2}"]
    if scope == "global":
        args.append("--global")
    if short:
        args += ["--short", short]
    assert mem.main(args) == 0
    if scope != "global" or not confirm:
        return
    folder = Path(os.environ["MEM_MEMORIES"])
    for m in records.load_memories(folder, "global"):
        if m.claim == claim:
            assert mem.main(["confirm", f"m:{m.handle}", "--global", "--by-owner"]) == 0
    for m in records.load_memories(folder, "global"):
        if m.triage == "pending":
            assert mem.main(["triage", "accept", m.handle]) == 0


def run(capsys, *argv):
    capsys.readouterr()
    assert mem.main(["session-index", *argv]) == 0
    return capsys.readouterr().out


def test_with_no_short_form_anywhere_the_text_is_byte_for_byte_what_it_was(project, gfolder, capsys):
    write("First lesson without a short form.")
    write("Second lesson without a short form.")
    out = run(capsys)
    expected = [LINE1 + " Global memories: 2."] + mem._INDEX_RULES.split("\n")[1:]
    assert out == "\n".join(expected) + "\n"


def test_rules_block_and_more_line_are_in_the_text_in_order(project, gfolder, capsys):
    write("Run the checks lesson.", short="Run the checks before you report a change.", weight="strong")
    for i in range(6):
        write(f"Other lesson {i}.", short=f"Other rule {i}.")
    out = run(capsys, "--list", "5")
    assert out.index("To remember:") < out.index(rules.HEADER) < out.index("- Run the checks") < out.index("1 more recommendation")
    assert out.count("\n- Other rule") == 5 and out.count("(confirmed by the owner)") == 6


def test_project_rows_keep_their_own_limit(project, gfolder, capsys):
    write("Project one.", short="Project rule one.", scope="project")
    for i in range(40):
        assert mem.main(["remember", "--kind", "lesson", "--claim", f"Project memory {i} " + "word " * 25]) == 0
    stats = {}
    folder = records.project_dir(project)
    text = mem.session_index(None, folder, gfolder, datetime.date.today(), limit=50, stats=stats)
    assert stats["rules"] == 1
    block = "\n".join([*rules.block(rules.choose(records.load_memories(folder, "project"), [], datetime.date.today()))])
    assert block in text and "  m:" in text
    assert len(text.replace(block + "\n", "")) <= mem._INDEX_LIMIT


def test_a_failure_while_choosing_changes_nothing_else(project, gfolder, capsys, monkeypatch):
    write("A lesson.", short="A rule that loads.")
    with_rules = run(capsys)
    assert rules.HEADER in with_rules

    def boom(*a, **k):
        raise RuntimeError("no")
    monkeypatch.setattr(rules, "choose", boom)
    out = run(capsys)
    assert rules.HEADER not in out
    assert out.split("\n") == [line for line in with_rules.split("\n") if line not in ("- A rule that loads. (confirmed by the owner)", rules.HEADER)]


def test_an_unreadable_global_folder_keeps_the_text(project, gfolder, capsys):
    write("A lesson.", short="A rule that loads.")
    gfolder.chmod(0)
    try:
        out = run(capsys)
    finally:
        gfolder.chmod(0o755)
    assert out.startswith(LINE1) and "To remember:" in out and rules.HEADER not in out


def test_the_hook_log_counts_rules(project, gfolder, capsys, monkeypatch):
    for i in range(7):
        write(f"Lesson {i}.", short=f"Rule {i}.")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project), "source": "startup"})))
    out = run(capsys, "--hook")
    line = json.loads((Path(os.environ["MEM_DATA"]) / "hooks" / "log.jsonl").read_text().splitlines()[-1])
    assert line["rules"] == 6 and line["rules_left"] == 1
    assert line["rules_chars"] == len("\n".join([*out.split("\n")[out.split("\n").index(rules.HEADER):]]).rstrip("\n"))
    assert all(isinstance(v, (int, str, type(None))) for v in line.values())
    assert "Rule" not in json.dumps(line)


def test_the_folders_are_read_once(project, gfolder, capsys, monkeypatch):
    write("A lesson.", short="A rule that loads.")
    write("Project lesson.", short="A project rule.", scope="project")
    calls = []
    real = records.load_memories

    def counting(folder, scope, *a, **k):
        calls.append(scope)
        return real(folder, scope, *a, **k)
    monkeypatch.setattr(records, "load_memories", counting)
    out = run(capsys)
    assert rules.HEADER in out and "A project rule." in out
    assert calls.count("global") == 1 and calls.count("project") == 1


def test_the_real_hook_script_with_only_mem_store(tmp_path):
    home, store, proj = tmp_path / "home", tmp_path / "store", tmp_path / "work" / "proj"
    for d in (home, store, proj):
        d.mkdir(parents=True)
    (store / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "MEM_STORE": str(store), "MEM_DATA": str(tmp_path / "data")}

    def mem_cmd(*args):
        r = subprocess.run([str(PLUGIN / "bin" / "mem"), *args], cwd=proj, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout

    mem_cmd("remember", "--global", "--kind", "lesson", "--claim", "Global lesson for the hook.", "--origin", "transcript",
            "--reach", "general", "--short", "Global rule for the hook.",
            "--source", f"session a project {K1}", "--source", f"session b project {K2}")
    handle = next(p.stem for p in (store / "memories").glob("*.md"))
    mem_cmd("confirm", f"m:{handle}", "--global", "--by-owner")
    mem_cmd("remember", "--kind", "lesson", "--claim", "Project lesson for the hook.", "--origin", "transcript",
            "--short", "Project rule for the hook.",
            "--source", f"session c project {K1}", "--source", f"session d project {K1}")
    r = subprocess.run([str(PLUGIN / "hooks" / "session-index.sh")], input=json.dumps({"cwd": str(proj), "source": "startup"}),
                       env=env, capture_output=True, text=True)
    out = r.stdout
    assert rules.HEADER in out and "(confirmed by the owner)" in out and "(held in 2 sessions)" in out
