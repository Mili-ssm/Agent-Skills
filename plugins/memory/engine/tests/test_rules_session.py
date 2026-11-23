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
    if weight == "strong":   # a strong lesson needs three sessions
        args += ["--source", f"session c project {K1}"]
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


@pytest.mark.parametrize("setup", ["store", "list", "notice"])
def test_without_short_forms_the_text_is_unchanged_in_other_setups(project, gfolder, tmp_path, setup):
    store = None
    if setup == "store":
        store = tmp_path / "store"
        (store / "knowledge" / "d").mkdir(parents=True)
        (store / "knowledge" / "d" / "n.md").write_text("x", encoding="utf-8")
    if setup == "list":
        for i in range(4):
            assert mem.main(["remember", "--kind", "lesson", "--claim", f"Plain project memory {i}."]) == 0
    options = {"limit": 5} if setup == "list" else {}
    if setup == "notice":
        options["notice"] = "memory: the last curation run failed (test notice)."
    today, folder = datetime.date.today(), records.project_dir(project)
    plain = mem.session_index(store, folder, gfolder, today, **options)
    write("First lesson without a short form.")
    write("Second lesson without a short form.")
    with_lessons = mem.session_index(store, folder, gfolder, today, **options)
    # the head line holds the counts that the two records change ("Global memories: N"); everything after it must match
    assert with_lessons.split("\n")[0] != plain.split("\n")[0]
    assert with_lessons.split("\n")[1:] == plain.split("\n")[1:]
    assert rules.HEADER not in with_lessons and "more lesson" not in with_lessons
    if setup == "list":
        assert "Plain project memory" in with_lessons
    if setup == "notice":
        assert options["notice"] in with_lessons


def test_rules_block_and_more_line_are_in_the_text_in_order(project, gfolder, capsys):
    write("Run the checks lesson.", short="Run the checks before you report a change.", weight="strong")
    for i in range(rules.RULES_MAX):
        write(f"Other lesson {i}.", short=f"Other rule {i}.")
    out = run(capsys, "--list", "5")
    assert out.index("To remember:") < out.index(rules.HEADER) < out.index("- Run the checks") < out.index("1 more lesson")
    assert out.count("\n- Other rule") == rules.RULES_MAX - 1 and out.count("(the user vouched for it)") == rules.RULES_MAX


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
    assert out.split("\n") == [line for line in with_rules.split("\n") if line not in ("- A rule that loads. (the user vouched for it)", rules.HEADER)]


def test_an_unreadable_global_folder_keeps_the_text(project, gfolder, capsys):
    write("A lesson.", short="A rule that loads.")
    assert mem.main(["remember", "--kind", "lesson", "--claim", "A project memory."]) == 0
    gfolder.chmod(0)
    try:
        out = run(capsys)
    finally:
        gfolder.chmod(0o755)
    assert out.startswith(LINE1) and "To remember:" in out and rules.HEADER not in out
    assert "This project: 1 memories." in out  # a line only the full text has


def test_the_hook_log_counts_rules(project, gfolder, capsys, monkeypatch):
    for i in range(rules.RULES_MAX + 1):
        write(f"Lesson {i}.", short=f"Rule {i}.")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project), "source": "startup"})))
    out = run(capsys, "--hook")
    line = json.loads((Path(os.environ["MEM_DATA"]) / "hooks" / "log.jsonl").read_text().splitlines()[-1])
    assert line["rules"] == rules.RULES_MAX and line["rules_left"] == 1
    assert line["rules_chars"] == len("\n".join([*out.split("\n")[out.split("\n").index(rules.HEADER):]]).rstrip("\n"))
    assert all(isinstance(v, (int, str, type(None))) for v in line.values())
    assert "Rule" not in json.dumps(line)


def test_a_lesson_awaiting_triage_is_not_counted_in_the_line_or_the_log(project, gfolder, capsys):
    write("Ready lesson.", short="Ready rule.")
    write("Waiting lesson.", short="Waiting rule.", weight="strong", confirm=False)  # last: no triage accept follows
    folder = records.project_dir(project)
    stats = {}
    text = mem.session_index(None, folder, gfolder, datetime.date.today(), stats=stats)
    waiting = [m for m in records.load_memories(gfolder, "global") if m.triage == "pending"]
    assert waiting, "the setup must leave one lesson awaiting triage"
    assert "Triage: 1 general lesson awaits" in text and "more lesson" not in text
    assert stats["rules"] == 1 and stats["rules_left"] == 0


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
    assert rules.HEADER in out and "(the user vouched for it)" in out and "(held in 2 sessions)" in out
    assert "- Global rule for the hook. (the user vouched for it)" in out
    assert "- Project rule for the hook. (held in 2 sessions)" in out
    assert (store / "memories" / f"{handle}.md").is_file()


def test_the_option_off_removes_the_block_and_nothing_else(project, gfolder, capsys, monkeypatch):
    write("A lesson.", short="A rule that loads.")
    for i in range(rules.RULES_MAX):
        write(f"Other lesson {i}.", short=f"Other rule {i}.")
    on = run(capsys)
    assert rules.HEADER in on and "more lesson" in on
    monkeypatch.setenv("MEM_LOADED_RULES", "off")
    off = run(capsys)
    assert off.split("\n") == [x for x in on.split("\n")
                               if x != rules.HEADER and not x.startswith(("- A rule", "- Other rule", "1 more lesson"))]
    stats = {}
    mem.session_index(None, records.project_dir(project), gfolder, datetime.date.today(), stats=stats)
    assert stats == {"rules": 0, "rules_left": 0, "rules_chars": 0}


@pytest.mark.parametrize("value, loads", [("false", False), ("true", True), (None, True)])
def test_the_hook_exports_the_switch_only_for_false(tmp_path, value, loads):
    home, store, proj = tmp_path / "home", tmp_path / "store", tmp_path / "work" / "proj"
    for d in (home, store, proj):
        d.mkdir(parents=True)
    (store / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "MEM_STORE": str(store), "MEM_DATA": str(tmp_path / "data")}
    r = subprocess.run([str(PLUGIN / "bin" / "mem"), "remember", "--global", "--kind", "lesson", "--claim", "Global lesson.",
                        "--origin", "transcript", "--reach", "general", "--short", "Global rule for the hook.",
                        "--source", f"session a project {K1}", "--source", f"session b project {K2}"],
                       cwd=proj, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    handle = next(p.stem for p in (store / "memories").glob("*.md"))
    subprocess.run([str(PLUGIN / "bin" / "mem"), "confirm", f"m:{handle}", "--global", "--by-owner"],
                   cwd=proj, env=env, capture_output=True, text=True, check=True)
    if value is not None:
        env["CLAUDE_PLUGIN_OPTION_LOADED_RULES"] = value
    r = subprocess.run([str(PLUGIN / "hooks" / "session-index.sh")], input=json.dumps({"cwd": str(proj), "source": "startup"}),
                       env=env, capture_output=True, text=True)
    assert (rules.HEADER in r.stdout) is loads and ("Global rule for the hook." in r.stdout) is loads


def _lessons():
    for i in range(3):
        write(f"Lesson {i}.", short=f"Rule {i}.")


def test_session_start_uses_the_layout_variable(project, gfolder, capsys, monkeypatch):
    _lessons()
    monkeypatch.delenv("MEM_RULES_LAYOUT", raising=False)
    before = run(capsys)
    assert "other:" not in before
    monkeypatch.setenv("MEM_RULES_LAYOUT", "grouped")
    grouped = run(capsys)
    assert "other:\n- Rule" in grouped
    monkeypatch.delenv("MEM_RULES_LAYOUT")
    assert run(capsys) == before
    monkeypatch.setenv("MEM_RULES_LAYOUT", "nonsense")
    assert run(capsys) == before
    stats = {}
    monkeypatch.setenv("MEM_RULES_LAYOUT", "grouped")
    mem.session_index(None, records.project_dir(project), gfolder, datetime.date.today(), stats=stats)
    printed = rules.HEADER + grouped.split(rules.HEADER, 1)[1].rstrip("\n")
    assert stats["rules_chars"] == len(printed) and "other:" in printed


def test_rules_off_prints_no_block_in_either_layout(project, gfolder, capsys, monkeypatch):
    _lessons()
    monkeypatch.setenv("MEM_LOADED_RULES", "off")
    monkeypatch.delenv("MEM_RULES_LAYOUT", raising=False)
    flat = run(capsys)
    monkeypatch.setenv("MEM_RULES_LAYOUT", "grouped")
    assert run(capsys) == flat and rules.HEADER not in flat and "other:" not in flat


def test_plugin_json_has_the_layout_option():
    option = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["userConfig"]["rules_layout"]
    assert option["type"] == "string" and option["default"] == "flat"


@pytest.mark.parametrize("value, grouped", [("grouped", True), ("flat", False), (None, False), ("nonsense", False)])
def test_the_hook_passes_the_layout(tmp_path, value, grouped):
    home, store, proj = tmp_path / "home", tmp_path / "store", tmp_path / "work" / "proj"
    for d in (home, store, proj):
        d.mkdir(parents=True)
    (store / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "MEM_STORE": str(store), "MEM_DATA": str(tmp_path / "data")}
    r = subprocess.run([str(PLUGIN / "bin" / "mem"), "remember", "--global", "--kind", "lesson", "--claim", "Global lesson.",
                        "--origin", "transcript", "--reach", "general", "--short", "Global rule for the hook.",
                        "--source", f"session a project {K1}", "--source", f"session b project {K2}"],
                       cwd=proj, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    handle = next(p.stem for p in (store / "memories").glob("*.md"))
    subprocess.run([str(PLUGIN / "bin" / "mem"), "confirm", f"m:{handle}", "--global", "--by-owner"],
                   cwd=proj, env=env, capture_output=True, text=True, check=True)
    if value is not None:
        env["CLAUDE_PLUGIN_OPTION_RULES_LAYOUT"] = value
    r = subprocess.run([str(PLUGIN / "hooks" / "session-index.sh")], input=json.dumps({"cwd": str(proj), "source": "startup"}),
                       env=env, capture_output=True, text=True)
    assert "Global rule for the hook." in r.stdout
    assert ("other:\n- Global rule for the hook." in r.stdout) is grouped


@pytest.mark.parametrize("layout, exported", [("grouped", True), ("flat", False), (None, False)])
def test_session_env_exports_the_layout(tmp_path, layout, exported):
    envfile = tmp_path / "env"
    envfile.write_text("")
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "c"),
           "XDG_DATA_HOME": str(tmp_path / "d"), "CLAUDE_ENV_FILE": str(envfile)}
    if layout:
        env["CLAUDE_PLUGIN_OPTION_RULES_LAYOUT"] = layout
    done = subprocess.run([str(PLUGIN / "hooks" / "session-env.sh")], env=env, capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout == ""
    assert ("export MEM_RULES_LAYOUT=grouped" in envfile.read_text().splitlines()) is exported
