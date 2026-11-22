import datetime
import os
from pathlib import Path

import pytest

import mem
import records
import reminders
import session_count
from reminder_fixtures import gfolder, project  # noqa: F401  (pytest fixtures)

TODAY = datetime.date.today()


def folder(root):
    return root / ".memory" / "reminders"


def load_one(root, handle):
    return next(r for r in reminders.load(root / ".memory", "project") if r.handle == handle)


def key(root, handle):
    return f"project:{records.project_key(root)}:{handle}"


def data():
    return Path(os.environ["MEM_DATA"])


def set_shown(root, handle, n):
    session_count.bump(data(), records.project_key(root), [key(root, handle)])
    for _ in range(n - 1):
        session_count.bump(data(), None, [key(root, handle)])


def rewrite(root, handle, **fields):
    """Edit front matter through the record's own renderer."""
    r = load_one(root, handle)
    for name, value in fields.items():
        setattr(r, name, value)
    r.path.write_text(reminders._render(r), encoding="utf-8")


def test_done_needs_a_note_and_ends_it(project, capsys):
    mem.main(["remind", "tidy up", "--body", "Tidy."])
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        mem.main(["reminder", "done", "tidy-up"])
    assert exc.value.code == 2
    capsys.readouterr()
    assert mem.main(["reminder", "done", "r:tidy-up", "--note", "tidied"]) == 0
    r = load_one(project, "tidy-up")
    assert r.status == "done" and r.done_note == "tidied" and r.ended == TODAY and r.shown_at_end == 0
    capsys.readouterr()
    mem.main(["reminders"])
    assert capsys.readouterr().out == "No reminders.\n"
    assert mem.main(["reminder", "done", "tidy-up", "--note", "again"]) == 2
    assert "is already done" in capsys.readouterr().err


def test_done_on_a_recurring_one_keeps_it_waiting_and_keeps_its_showings(project, capsys):
    mem.main(["remind", "weekly", "--body", "b", "--every", "7d"])
    set_shown(project, "weekly", 3)
    capsys.readouterr()
    assert mem.main(["reminder", "done", "weekly", "--note", "ok"]) == 0
    r = load_one(project, "weekly")
    assert r.status == "active" and r.times_done == 1 and r.shown_before == [3]
    assert r.after == TODAY + datetime.timedelta(days=7)
    assert session_count.showings(session_count.read(data()), key(project, "weekly")) == 0


def test_close_then_restore_brings_it_back(project, capsys):
    mem.main(["remind", "drop me", "--body", "b"])
    capsys.readouterr()
    assert mem.main(["reminder", "close", "drop-me", "--reason", "not needed"]) == 0
    r = load_one(project, "drop-me")
    assert r.status == "closed" and r.closed_reason == "not needed"
    capsys.readouterr()
    assert mem.main(["reminder", "restore", "drop-me"]) == 0
    assert "r:drop-me\trestored to before close of" in capsys.readouterr().out
    assert load_one(project, "drop-me").status == "active"
    assert mem.main(["reminder", "restore", "drop-me"]) == 2
    assert "nothing to restore" in capsys.readouterr().err


def test_snooze_by_sessions_days_and_date_resets_the_showings(project, capsys):
    mem.main(["remind", "later", "--body", "b", "--until", (TODAY + datetime.timedelta(days=100)).isoformat()])
    set_shown(project, "later", 2)
    capsys.readouterr()
    assert mem.main(["reminder", "snooze", "later", "--sessions", "3"]) == 0
    r = load_one(project, "later")
    assert r.in_sessions == 3 and r.after is None and r.shown_before == [2]
    assert r.until == TODAY + datetime.timedelta(days=100)
    assert session_count.showings(session_count.read(data()), key(project, "later")) == 0
    assert mem.main(["reminder", "snooze", "later", "--days", "4"]) == 0
    r = load_one(project, "later")
    assert r.after == TODAY + datetime.timedelta(days=4) and r.in_sessions is None and r.shown_before == [2, 0]
    target = TODAY + datetime.timedelta(days=9)
    assert mem.main(["reminder", "snooze", "later", "--to", target.isoformat()]) == 0
    assert load_one(project, "later").after == target
    capsys.readouterr()
    late = (TODAY + datetime.timedelta(days=200)).isoformat()
    assert mem.main(["reminder", "snooze", "later", "--to", late]) == 2
    assert "later than until" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        mem.main(["reminder", "snooze", "later"])
    with pytest.raises(SystemExit):
        mem.main(["reminder", "snooze", "later", "--days", "1", "--sessions", "1"])


def test_a_note_with_a_secret_is_refused_and_nothing_changes(project, capsys):
    mem.main(["remind", "secretive", "--body", "b"])
    set_shown(project, "secretive", 2)
    before = load_one(project, "secretive").path.read_text()
    capsys.readouterr()
    assert mem.main(["reminder", "done", "secretive", "--note", "token AKIAIOSFODNN7EXAMPLE"]) == 4
    assert mem.main(["reminder", "close", "secretive", "--reason", "token AKIAIOSFODNN7EXAMPLE"]) == 4
    assert load_one(project, "secretive").path.read_text() == before
    assert session_count.showings(session_count.read(data()), key(project, "secretive")) == 2
    assert not (folder(project) / ".curation-log").exists()


def test_showings_are_absent_not_zero_when_the_count_cannot_be_read(project, capsys, monkeypatch):
    mem.main(["remind", "one", "--body", "b"])
    mem.main(["remind", "two", "--body", "b"])
    mem.main(["remind", "three", "--body", "b"])
    capsys.readouterr()
    counts = data()
    counts.mkdir(parents=True, exist_ok=True)
    (counts / session_count.COUNT_NAME).write_text("{not json", encoding="utf-8")
    assert mem.main(["reminder", "close", "one", "--reason", "r"]) == 0
    assert load_one(project, "one").shown_at_end is None
    assert (counts / session_count.COUNT_NAME).read_text() == "{not json"
    monkeypatch.delenv("MEM_DATA")
    monkeypatch.setenv("HOME", "")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert mem.data_dir(os.environ) is None
    assert mem.main(["reminder", "close", "two", "--reason", "r"]) == 0
    assert load_one(project, "two").shown_at_end is None
    monkeypatch.setenv("MEM_DATA", str(counts.parent / "fresh"))
    assert mem.main(["reminder", "close", "three", "--reason", "r"]) == 0
    assert load_one(project, "three").shown_at_end == 0


def test_stats_reports_each_kind_with_its_median(project, capsys):
    for name in ("a1", "a2", "a3", "a4", "c1", "p1", "l1", "live1"):
        mem.main(["remind", name, "--body", "b"])
    for name, n in (("a1", 1), ("a2", 1), ("a3", 3), ("a4", 0)):
        set_shown(project, name, n) if n else None
        mem.main(["reminder", "done", name, "--note", "n"])
    set_shown(project, "c1", 5)
    mem.main(["reminder", "close", "c1", "--reason", "r"])
    rewrite(project, "p1", shown_before=[1, 2, 7])
    rewrite(project, "l1", until=TODAY - datetime.timedelta(days=1))
    capsys.readouterr()
    assert mem.main(["reminders", "--stats"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "live 2", "done 4 (median 1 showing)", "closed 1 (median 5 showings)", "put off 3 (median 2 showings)",
        "lapsed 1"]


def test_stats_with_nothing_prints_counts_only(project, capsys):
    assert mem.main(["reminders", "--stats"]) == 0
    assert capsys.readouterr().out.splitlines() == ["live 0", "done 0", "closed 0", "put off 0", "lapsed 0"]


def test_all_lists_ended_lapsed_and_broken(project, capsys):
    for name in ("alive", "finished", "shut", "expired", "broken"):
        mem.main(["remind", name, "--body", "b"])
    mem.main(["reminder", "done", "finished", "--note", "n"])
    mem.main(["reminder", "close", "shut", "--reason", "r"])
    rewrite(project, "expired", until=TODAY - datetime.timedelta(days=1))
    (folder(project) / "broken.md").write_text("---\nstatus: nope\n---\nb\n", encoding="utf-8")
    capsys.readouterr()
    mem.main(["reminders"])
    assert capsys.readouterr().out.count("r:") == 1
    mem.main(["reminders", "--all"])
    out = capsys.readouterr().out
    assert "r:alive" in out
    assert "r:finished\tproject\tfinished\tdone" in out
    assert "r:shut\tproject\tshut\tclosed" in out
    assert "r:expired\tproject\texpired\tlapsed" in out
    assert "r:broken\tproject\tbroken" in out and "cannot be read" in out and "topic is missing" in out


def test_show_accepts_the_r_prefix_through_mem_show(project, capsys):
    mem.main(["remind", "look", "--body", "The body text.", "--in-sessions", "2"])
    capsys.readouterr()
    assert mem.main(["reminder", "show", "look"]) == 0
    direct = capsys.readouterr().out
    assert "r:look" in direct and "The body text." in direct and "waits for 2 sessions" in direct
    assert mem.main(["show", "r:look"]) == 0
    assert capsys.readouterr().out.strip() == direct.strip()
    assert mem.main(["show", "r:nothing"]) == 1
    assert "no reminder r:nothing" in capsys.readouterr().err


def test_unknown_handle(capsys, project):
    for argv in (["show", "nothing"], ["done", "nothing", "--note", "n"], ["close", "nothing", "--reason", "r"],
                 ["snooze", "nothing", "--days", "1"], ["restore", "nothing"]):
        assert mem.main(["reminder", *argv]) == 2
        assert "no reminder r:nothing" in capsys.readouterr().err


def test_global_reminders_work_the_same_way(project, gfolder, capsys):
    mem.main(["remind", "everywhere", "--body", "b", "--global"])
    capsys.readouterr()
    assert mem.main(["reminder", "done", "everywhere", "--note", "n", "--global"]) == 0
    r = reminders.load(gfolder, "global")[0]
    assert r.status == "done" and r.shown_at_end == 0
    capsys.readouterr()
    assert mem.main(["reminder", "restore", "everywhere", "--global"]) == 0


def test_reminders_do_not_reach_search_memories_or_curate(project, gfolder, capsys):
    mem.main(["remind", "zebra migration", "--body", "zebra"]); mem.main(["remind", "zebra global", "--body", "zebra", "--global"])
    capsys.readouterr()
    for argv in (["search", "--scope", "memories", "zebra"], ["memories"], ["memories", "--global"], ["curate"], ["curate", "--global"]):
        mem.main(argv); assert "zebra" not in capsys.readouterr().out


def test_check_accepts_a_store_whose_memories_hold_a_reminder_with_a_link_in_its_body(hub_root, monkeypatch, capsys):
    before = mem.main(["--root", str(hub_root), "check"])
    capsys.readouterr()
    monkeypatch.delenv("MEM_MEMORIES", raising=False)
    memories = hub_root / "memories"
    reminders.write(memories, "global", topic="linked", body="See [the note](../some-note.md) and [[wiki]].",
                    today=TODAY, count=0)
    assert (memories / "reminders" / "linked.md").is_file()
    assert mem.main(["--root", str(hub_root), "check"]) == before
    assert capsys.readouterr().out == ""


def test_global_reminders_are_found_when_only_mem_store_names_the_store(project, hub_root, monkeypatch, capsys):
    monkeypatch.delenv("MEM_MEMORIES", raising=False)
    monkeypatch.setenv("MEM_STORE", str(hub_root))
    assert mem.main(["remind", "x", "--body", "b", "--global"]) == 0
    assert (hub_root / "memories" / "reminders" / "x.md").is_file()
    capsys.readouterr()
    assert mem.main(["reminders", "--global"]) == 0
    assert "r:x" in capsys.readouterr().out
    assert mem.main(["reminder", "show", "x", "--global"]) == 0
    assert "r:x" in capsys.readouterr().out
    assert mem.main(["show", "r:x"]) == 0
    assert "r:x" in capsys.readouterr().out
    assert mem.main(["reminder", "done", "x", "--note", "n", "--global"]) == 0
    capsys.readouterr()


def unreadable_count(monkeypatch, tmp_path):
    counts = tmp_path / "bad-data"
    counts.mkdir()
    (counts / session_count.COUNT_NAME).write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("MEM_DATA", str(counts))
    return counts


@pytest.mark.parametrize("argv", [["remind", "w", "--body", "b", "--in-sessions", "2"],
                                  ["remind", "w", "--body", "b", "--every", "3s"]])
def test_arming_by_sessions_is_refused_when_the_count_cannot_be_read(argv, project, monkeypatch, tmp_path, capsys):
    counts = unreadable_count(monkeypatch, tmp_path)
    assert mem.main(argv) == 2
    assert capsys.readouterr().err == (f"mem: the session count cannot be read ({counts / 'sessions.json'}): "
                                       "use a date, or repair that file\n")
    assert not folder(project).exists() or not list(folder(project).glob("*.md"))


def test_snooze_by_sessions_and_done_on_a_session_repeat_are_refused_when_the_count_cannot_be_read(
        project, monkeypatch, tmp_path, capsys):
    mem.main(["remind", "w", "--body", "b", "--every", "3s"])
    mem.main(["remind", "plain", "--body", "b"])
    counts = unreadable_count(monkeypatch, tmp_path)
    capsys.readouterr()
    before = load_one(project, "w").path.read_text()
    assert mem.main(["reminder", "snooze", "w", "--sessions", "2"]) == 2
    assert mem.main(["reminder", "done", "w", "--note", "n"]) == 2
    assert f"the session count cannot be read ({counts / 'sessions.json'})" in capsys.readouterr().err
    assert load_one(project, "w").path.read_text() == before
    assert mem.main(["reminder", "snooze", "plain", "--days", "2"]) == 0  # a date needs no count
    assert mem.main(["reminder", "done", "plain", "--note", "n"]) == 0


def test_a_missing_count_file_is_readable():
    assert session_count.readable(Path(os.environ["MEM_DATA"])) is True


def test_an_unreadable_reminders_folder_is_not_no_reminders(project, capsys):
    mem.main(["remind", "kept", "--body", "b"])
    capsys.readouterr()
    folder(project).chmod(0)
    try:
        assert mem.main(["reminders"]) == 2
        captured = capsys.readouterr()
        assert "mem: cannot read project reminders:" in captured.err and "No reminders." not in captured.out
        assert mem.main(["remind", "more", "--body", "b"]) == 2
        assert "mem: cannot read project reminders:" in capsys.readouterr().err
    finally:
        folder(project).chmod(0o700)


def test_an_unreadable_scope_still_lists_the_other(project, gfolder, capsys):
    mem.main(["remind", "kept", "--body", "b"])
    mem.main(["remind", "world", "--body", "b", "--global"])
    capsys.readouterr()
    folder(project).chmod(0)
    try:
        assert mem.main(["reminders"]) == 2
        captured = capsys.readouterr()
        assert "r:world" in captured.out and "cannot read project reminders" in captured.err
    finally:
        folder(project).chmod(0o700)


def test_broken_files_get_a_hint_and_count_toward_the_limit(project, capsys):
    mem.main(["remind", "ok", "--body", "b"])
    for n in range(2):
        (folder(project) / f"bad{n}.md").write_text("---\nstatus: nope\n---\nb\n", encoding="utf-8")
    capsys.readouterr()
    assert mem.main(["reminders"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "2 reminder file(s) cannot be read: mem reminders --all"
    mem.main(["reminders", "--all"])
    assert "reminder file(s) cannot be read" not in capsys.readouterr().out
    for n in range(7):
        assert mem.main(["remind", f"n{n}", "--body", "b"]) == 0
    assert mem.main(["remind", "over", "--body", "b"]) == 2


def test_done_counts_every_time_and_ends_a_lapsed_repeat(project, capsys):
    mem.main(["remind", "d", "--body", "b", "--every", "30d", "--until", (TODAY + datetime.timedelta(days=10)).isoformat()])
    capsys.readouterr()
    assert mem.main(["reminder", "done", "d", "--note", "n"]) == 0
    r = load_one(project, "d")
    assert r.status == "done" and r.times_done == 1
    mem.main(["remind", "s", "--body", "b", "--every", "2s"])
    rewrite(project, "s", until=TODAY - datetime.timedelta(days=1))
    assert mem.main(["reminder", "done", "s", "--note", "n"]) == 0
    assert load_one(project, "s").status == "done"


def test_snooze_by_a_date_refuses_an_ended_reminder(project, capsys):
    mem.main(["remind", "e", "--body", "b"])
    rewrite(project, "e", until=TODAY - datetime.timedelta(days=1))
    capsys.readouterr()
    assert mem.main(["reminder", "snooze", "e", "--days", "1"]) == 2
    assert "ended on" in capsys.readouterr().err
