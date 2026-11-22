"""The line of due reminders in the session start text, and the count of showings it raises."""
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

import mem
import records
import reminders
import session_count
from reminder_fixtures import gfolder, project  # noqa: F401  (pytest fixtures)

ROOT = Path(__file__).resolve().parents[2]


def data_folder():
    return Path(os.environ["MEM_DATA"])


def remind(topic, *extra):
    assert mem.main(["remind", topic, "--body", "b", *extra]) == 0


def start(monkeypatch, capsys, project_root, source="startup", session="s1", *extra):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(project_root), "source": source,
                                                              "session_id": session})))
    assert mem.main(["session-index", "--hook", *extra]) == 0
    return capsys.readouterr().out


def shown(name):
    return session_count.read(data_folder())["shown"].get(name, {}).get("n", 0)


def key_of(project_root, handle):
    return f"project:{records.project_key(project_root)}:{handle}"


def test_no_due_reminder_adds_no_line(project, capsys):
    remind("later", "--in-sessions", "5")
    capsys.readouterr()
    assert mem.main(["session-index"]) == 0
    out = capsys.readouterr().out
    assert "Reminders:" not in out and "memory: the mem command" in out


def test_line_names_topics_sessions_and_waiting(project, monkeypatch, capsys):
    remind("old one", "--in-sessions", "1")
    remind("review the docs")
    remind("not yet", "--in-sessions", "50")
    capsys.readouterr()
    for n in range(2):  # two counted starts, then the one that prints
        session_count.bump(data_folder(), records.project_key(project))
    out = start(monkeypatch, capsys, project)
    assert "Reminders: 2 due (" in out and "3 sessions" in out
    assert "; 1 waiting. After the current task: mem reminders." in out


def test_the_fifth_showing_asks_the_owner(project, monkeypatch, capsys):
    remind("tidy up")
    capsys.readouterr()
    outs = [start(monkeypatch, capsys, project, session=f"s{n}") for n in range(5)]
    assert all("ask the owner" not in o for o in outs[:4])
    assert "ask the owner: keep or close" in outs[4]
    assert shown(key_of(project, "tidy-up")) == 5


def test_compactions_of_one_session_do_not_bring_the_question_forward(project, monkeypatch, capsys):
    remind("tidy up")
    capsys.readouterr()
    outs = [start(monkeypatch, capsys, project, "startup")]
    outs += [start(monkeypatch, capsys, project, "compact") for _ in range(6)]
    assert all("ask the owner" not in o for o in outs)
    assert "6 sessions" in outs[5] and "7 sessions" in outs[6]
    assert shown(key_of(project, "tidy-up")) == 1


def test_showings_rise_only_on_counted_hook_starts(project, monkeypatch, capsys):
    remind("tidy up")
    capsys.readouterr()
    name = key_of(project, "tidy-up")
    assert mem.main(["session-index"]) == 0
    assert "Reminders: 1 due" in capsys.readouterr().out and shown(name) == 0
    start(monkeypatch, capsys, project, "resume")
    assert shown(name) == 0 and session_count.read(data_folder())["total"] == 0
    start(monkeypatch, capsys, project, "startup")
    assert shown(name) == 1 and session_count.read(data_folder())["total"] == 1


def test_line_stays_within_300_characters_with_ten_due_long_topics(project, capsys):
    for n in range(10):
        remind(f"{n} " + "long topic words " * 2)
    capsys.readouterr()
    assert mem.main(["session-index"]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if x.startswith("Reminders:"))
    assert len(line) <= reminders.LINE_LIMIT and "+" in line and "more)" in line
    assert line.startswith("Reminders: 10 due (")


def test_showings_rise_only_for_the_reminders_the_line_named(project, monkeypatch, capsys):
    for n in range(6):
        remind(f"topic {n}")
    capsys.readouterr()
    out = start(monkeypatch, capsys, project)
    assert "+2 more" in out
    named = [h for h in (f"topic-{n}" for n in range(6)) if f"topic {h[-1]}," in out or f"topic {h[-1]};" in out
             or f"topic {h[-1]})" in out]
    assert len(named) == 4
    for n in range(6):
        handle = f"topic-{n}"
        assert shown(key_of(project, handle)) == (1 if handle in named else 0)


def test_a_zero_session_reminder_prints_its_topic_without_a_count(project, monkeypatch, capsys):
    remind("review the docs")
    capsys.readouterr()
    assert "(review the docs)" in start(monkeypatch, capsys, project, source="resume")
    out = start(monkeypatch, capsys, project, session="s9")
    assert "(review the docs, 1 session)" in out


def test_no_showing_is_counted_when_the_text_falls_back_to_the_rules(project, monkeypatch, capsys):
    remind("tidy up")
    capsys.readouterr()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(mem, "session_index", boom)
    out = start(monkeypatch, capsys, project)
    assert "Reminders:" not in out
    state = session_count.read(data_folder())
    assert state["total"] == 1 and state["shown"] == {}


@pytest.mark.parametrize("failing", ["project", "global"])
def test_one_scope_failing_keeps_the_other_scopes_reminders(failing, project, gfolder, monkeypatch, capsys):
    remind("project one")
    remind("global one", "--global")
    capsys.readouterr()
    real = reminders.load

    def load(root, scope):
        if scope == failing:
            raise OSError("boom")
        return real(root, scope)

    monkeypatch.setattr(reminders, "load", load)
    out = start(monkeypatch, capsys, project)
    other = "global one" if failing == "project" else "project one"
    assert "Reminders: 1 due (" + other in out


def test_the_text_prints_when_the_reminders_folder_cannot_be_read(project, monkeypatch, capsys):
    remind("tidy up")
    capsys.readouterr()
    folder = project / ".memory" / "reminders"
    folder.chmod(0)
    try:
        out = start(monkeypatch, capsys, project)
    finally:
        folder.chmod(0o755)
    assert "memory: the mem command" in out and "Reminders:" not in out


def test_the_line_survives_the_text_limit(project, capsys):
    folder = project / ".memory"
    folder.mkdir(exist_ok=True)
    for n in range(60):
        (folder / f"m{n:02d}.md").write_text(
            f"---\nkind: lesson\nclaim: {'claim words ' * 12}{n}\ncreated: 2026-11-01\nobserved: 1\nstatus: active\n---\n",
            encoding="utf-8")
    remind("tidy up")
    capsys.readouterr()
    assert mem.main(["session-index", "--list", "50"]) == 0
    out = capsys.readouterr().out
    assert "Reminders:" in out and len(out) <= 1500 and "m:m" in out


def test_a_broken_reminder_or_an_unreadable_data_folder_keeps_the_text(project, monkeypatch, capsys):
    remind("tidy up")
    remind("waits", "--in-sessions", "2")
    folder = project / ".memory" / "reminders"
    (folder / "broken.md").write_text("---\ntopic: [\n---\n", encoding="utf-8")
    capsys.readouterr()
    out = start(monkeypatch, capsys, project)
    assert "Reminders: 1 due (tidy up" in out and "; 1 waiting." in out and "memory: the mem command" in out
    (data_folder() / "sessions.json").write_text("{not json")  # unreadable count
    out = start(monkeypatch, capsys, project, session="s2")
    assert "Reminders: 1 due (tidy up" in out and "; 1 waiting." in out and "memory: the mem command" in out
    assert (data_folder() / "sessions.json").read_text() == "{not json"
    monkeypatch.setattr(reminders, "load", lambda *a: 1 / 0)  # any failure: no line, the rest unchanged
    out = start(monkeypatch, capsys, project, session="s3")
    assert "Reminders:" not in out and "memory: the mem command" in out and "- To remember:" in out


def test_done_resets_the_showings(project, monkeypatch, capsys):
    remind("recurring", "--every", "1s")
    capsys.readouterr()
    name = key_of(project, "recurring")
    for n in range(3):
        start(monkeypatch, capsys, project, session=f"s{n}")
    assert shown(name) == 3
    assert mem.main(["reminder", "done", "recurring", "--note", "did it"]) == 0
    capsys.readouterr()
    assert shown(name) == 0
    out = start(monkeypatch, capsys, project, session="s9")
    assert "Reminders: 1 due (recurring, 1 session)" in out and shown(name) == 1


def test_the_real_hook_script_with_only_mem_store(tmp_path):
    home, store, data = tmp_path / "home", tmp_path / "store", tmp_path / "data"
    proj = tmp_path / "work"
    for d in (home, store, proj):
        d.mkdir()
    (store / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True, capture_output=True)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "MEM_STORE": str(store), "MEM_DATA": str(data)}
    for args in (["remind", "project one", "--body", "b"], ["remind", "global one", "--body", "b", "--global"]):
        done = subprocess.run([str(ROOT / "bin" / "mem"), *args], cwd=proj, env=env,
                              capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr
    payload = json.dumps({"cwd": str(proj), "source": "compact"})
    run = subprocess.run(["bash", str(ROOT / "hooks" / "session-index.sh")], input=payload, env=env, cwd=tmp_path,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and "Reminders: 2 due" in run.stdout, run.stdout + run.stderr
    assert "project one" in run.stdout and "global one" in run.stdout
    assert list((store / "memories" / "reminders").glob("*.md"))
    last = (data / "hooks" / "log.jsonl").read_text().splitlines()[-1]
    assert json.loads(last)["due"] == 2
