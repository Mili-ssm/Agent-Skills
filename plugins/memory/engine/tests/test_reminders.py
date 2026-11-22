import datetime
import json

import pytest

import reminders

T = datetime.date(2026, 11, 22)
DAY = datetime.timedelta(days=1)


def test_written_with_no_condition_is_due_at_once(tmp_path):
    r = reminders.write(tmp_path, "project", topic="review the docs", body="Check links.", today=T, count=7)
    assert r.handle == "review-the-docs" and r.armed_count == 7 and reminders.is_due(r, T, 7)
    assert reminders.load(tmp_path, "project")[0].topic == "review the docs"
    assert not list(tmp_path.glob("*.md"))          # nothing in the memory folder itself


def test_a_clash_gets_a_suffix(tmp_path):
    a = reminders.write(tmp_path, "project", topic="same", body="b", today=T, count=0)
    b = reminders.write(tmp_path, "project", topic="same", body="b", today=T, count=0)
    assert (a.handle, b.handle) == ("same", "same-2")


def test_waits_for_sessions_then_is_due(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=7, in_sessions=3)
    assert not reminders.is_due(r, T, 9) and reminders.is_due(r, T, 10) and reminders.sessions_since(r, 10) == 3


def test_a_count_lower_than_armed_counts_from_the_reset(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=50, in_sessions=2)
    assert reminders.sessions_since(r, 1) == 1 and not reminders.is_due(r, T, 1) and reminders.is_due(r, T, 2)


def test_snooze_to_a_date_waits_and_keeps_the_end_date(tmp_path):
    end = T + 30 * DAY
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0, until=end)
    later = reminders.snooze(r, T, 3, 4, after=T + 7 * DAY)
    assert later.until == end and later.shown_before == [4] and not reminders.is_due(later, T, 3)
    assert reminders.is_due(later, T + 7 * DAY, 3)
    with pytest.raises(ValueError):
        reminders.snooze(r, T, 3, 0, after=end + DAY)


def test_waits_for_a_date_and_lapses_after_until(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0, after=T + 2 * DAY, until=T + 5 * DAY)
    assert not reminders.is_due(r, T, 0) and reminders.is_due(r, T + 2 * DAY, 0)
    assert not reminders.is_live(r, T + 6 * DAY)


def test_done_ends_a_single_one_and_rearms_a_recurring_one(tmp_path):
    one = reminders.write(tmp_path, "project", topic="once", body="b", today=T, count=1)
    ended = reminders.done(one, T, 4, "Fixed the links.", 2)
    assert ended.status == "done" and ended.ended == T and ended.shown_at_end == 2 and ended.done_note == "Fixed the links."
    rec = reminders.write(tmp_path, "project", topic="studies", body="b", today=T, count=1, every="30d")
    again = reminders.done(rec, T, 4, "Nothing new.", 1)
    assert again.status == "active" and again.after == T + 30 * DAY and again.times_done == 1
    assert again.in_sessions is None and again.shown_before == [1] and again.armed_count == 4
    by_sessions = reminders.done(reminders.write(tmp_path, "project", topic="s", body="b", today=T, count=1, every="10s"), T, 4, "n", 0)
    assert by_sessions.in_sessions == 10 and by_sessions.armed_count == 4 and by_sessions.after is None


def test_close_and_unknown_shown(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0)
    c = reminders.close(r, T, "not needed", None)
    assert (c.status, c.ended, c.closed_reason, c.shown_at_end) == ("closed", T, "not needed", None)
    assert not reminders.is_live(c, T)
    s = reminders.snooze(reminders.write(tmp_path, "project", topic="u", body="b", today=T, count=0), T, 1, None, sessions=2)
    assert s.shown_before == [] and s.in_sessions == 2
    assert reminders.load(tmp_path, "project")[0].shown_at_end is None


def test_every_change_is_logged_before(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0)
    log = reminders.folder_of(tmp_path) / ".curation-log"
    assert not log.exists()
    r = reminders.snooze(r, T, 1, 0, sessions=2)
    r = reminders.snooze(r, T, 2, 1, after=T + DAY)
    reminders.close(r, T, "done with it", 2)
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [e["action"] for e in entries] == ["snooze", "snooze", "close"]
    assert all(e["handle"] == "t" for e in entries)
    assert "status: active" in entries[0]["before"] and "in_sessions: 2" in entries[1]["before"]
    assert not list(tmp_path.glob("*.md")) and not list(tmp_path.glob(".curation-log"))


@pytest.mark.parametrize("bad", [dict(topic=""), dict(topic="x" * 41), dict(body=""), dict(effort="huge"), dict(risk="none"),
                                 dict(every="0d"), dict(every="3w"), dict(in_sessions=0), dict(in_sessions=1000),
                                 dict(until=T - DAY), dict(after=T + 3 * DAY, until=T + DAY)])
def test_write_refuses(bad, tmp_path):
    args = dict(topic="t", body="b", today=T, count=0) | bad
    with pytest.raises(ValueError):
        reminders.write(tmp_path, "project", **args)
    assert reminders.load(tmp_path, "project") == []
    assert not list(reminders.folder_of(tmp_path).glob("*.md"))


def test_parse_every():
    assert reminders.parse_every("30d") == (30, "d") and reminders.parse_every("999s") == (999, "s")
    for bad in ("", "d", "1000d", "30", "30D", "-3d"):
        with pytest.raises(ValueError):
            reminders.parse_every(bad)


def test_a_broken_file_loads_with_its_error_and_hides_nothing(tmp_path):
    good = reminders.write(tmp_path, "project", topic="good", body="b", today=T, count=0)
    folder = reminders.folder_of(tmp_path)
    (folder / "a-no-front.md").write_text("just text\n", encoding="utf-8")
    (folder / "b-bad-yaml.md").write_text("---\ntopic: [unclosed\n---\nb\n", encoding="utf-8")
    (folder / "c-bad-status.md").write_text("---\ntopic: x\nstatus: maybe\n---\nb\n", encoding="utf-8")
    found = {r.handle: r for r in reminders.load(tmp_path, "project")}
    assert set(found) == {"good", "a-no-front", "b-bad-yaml", "c-bad-status"}
    assert found["good"].error is None and reminders.is_due(found["good"], T, 0)
    for h in ("a-no-front", "b-bad-yaml", "c-bad-status"):
        assert found[h].error and not reminders.is_live(found[h], T) and not reminders.is_due(found[h], T, 99)
    assert "unknown status" in found["c-bad-status"].error
    assert good.path.exists()
    assert reminders.load(None, "project") == [] and reminders.load(tmp_path / "missing", "project") == []


def test_snooze_takes_exactly_one_condition(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0, after=T + DAY, in_sessions=None)
    with pytest.raises(ValueError):
        reminders.snooze(r, T, 1, 0)
    with pytest.raises(ValueError):
        reminders.snooze(r, T, 1, 0, sessions=2, after=T + 2 * DAY)
    with pytest.raises(ValueError):
        reminders.snooze(r, T, 1, 0, sessions=0)
    by_sessions = reminders.snooze(r, T, 5, 1, sessions=3)
    assert by_sessions.in_sessions == 3 and by_sessions.after is None and by_sessions.armed_count == 5
    by_date = reminders.snooze(by_sessions, T, 6, 2, after=T + 9 * DAY)
    assert by_date.after == T + 9 * DAY and by_date.in_sessions is None and by_date.shown_before == [1, 2]
    again = reminders.load(tmp_path, "project")[0]
    assert (again.after, again.in_sessions, again.armed_count) == (T + 9 * DAY, None, 6)


def test_unknown_front_matter_keys_survive_a_rewrite(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="Body text.", today=T, count=0)
    text = r.path.read_text(encoding="utf-8").replace("times_done: 0\n", "times_done: 0\nowner_hint: keep me\n")
    r.path.write_text(text, encoding="utf-8")
    loaded = reminders.load(tmp_path, "project")[0]
    reminders.snooze(loaded, T, 1, 0, sessions=2)
    after = reminders.load(tmp_path, "project")[0]
    assert after.extra == {"owner_hint": "keep me"} and after.in_sessions == 2 and after.body == "Body text.\n"


def _broken_with_body(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="Body text.", today=T, count=0)
    text = r.path.read_text(encoding="utf-8").replace("status: active", "status: maybe") + "tail\n"
    r.path.write_text(text, encoding="utf-8")
    return reminders.load(tmp_path, "project")[0], text


@pytest.mark.parametrize("act", [lambda r: reminders.done(r, T, 1, "n", None), lambda r: reminders.close(r, T, "x", None),
                                 lambda r: reminders.snooze(r, T, 1, None, sessions=2)])
def test_a_broken_record_is_refused_untouched(act, tmp_path):
    r, text = _broken_with_body(tmp_path)
    with pytest.raises(ValueError, match=r"^r:t cannot be read \(.*unknown status.*\): repair the file or restore it$"):
        act(r)
    assert r.path.read_text(encoding="utf-8") == text
    assert not (reminders.folder_of(tmp_path) / ".curation-log").exists()


def test_a_file_that_is_not_utf8_is_refused_without_a_crash(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0)
    r.path.write_bytes(b"---\ntopic: \xff\xfe\n---\nb\n")
    broken = reminders.load(tmp_path, "project")[0]
    assert broken.error
    with pytest.raises(ValueError, match="cannot be read"):
        reminders.close(broken, T, "x", None)


@pytest.mark.parametrize("act", [lambda r: reminders.done(r, T, 1, "n", None), lambda r: reminders.close(r, T, "x", None),
                                 lambda r: reminders.snooze(r, T, 1, None, sessions=2)])
@pytest.mark.parametrize("first", ["done", "close"])
def test_transitions_refuse_a_record_that_is_not_active(act, first, tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0)
    ended = reminders.done(r, T, 1, "n", None) if first == "done" else reminders.close(r, T, "x", None)
    text = ended.path.read_text(encoding="utf-8")
    log = reminders.folder_of(tmp_path) / ".curation-log"
    entries = log.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match=rf"^r:t is already {ended.status}: mem reminder restore t brings it back$"):
        act(ended)
    assert ended.path.read_text(encoding="utf-8") == text and log.read_text(encoding="utf-8") == entries


def test_an_ended_but_active_reminder_may_be_done_or_closed_not_snoozed(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0, until=T + DAY)
    later = T + 3 * DAY
    with pytest.raises(ValueError, match="after is later than until"):
        reminders.snooze(r, later, 1, None, after=later)
    with pytest.raises(ValueError, match=rf"^r:t ended on {r.until}: close it or write a new one$"):
        reminders.snooze(r, later, 1, None, sessions=2)
    assert reminders.close(r, later, "x", None).status == "closed"
    assert reminders.done(r, later, 1, "n", None).status == "done"


def test_done_ends_a_day_repeat_that_would_pass_its_end_date(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0, every="30d", until=T + 10 * DAY)
    ended = reminders.done(r, T, 4, "fine", 2)
    assert (ended.status, ended.ended, ended.done_note, ended.shown_at_end) == ("done", T, "fine", 2)
    fits = reminders.write(tmp_path, "project", topic="u", body="b", today=T, count=0, every="10d", until=T + 10 * DAY)
    assert reminders.done(fits, T, 4, "n", None).status == "active"
    by_sessions = reminders.write(tmp_path, "project", topic="v", body="b", today=T, count=0, every="5s", until=T + 2 * DAY)
    assert reminders.done(by_sessions, T, 4, "n", None).status == "active"


def test_a_render_failure_changes_nothing(tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0)
    text = r.path.read_text(encoding="utf-8")
    bad = reminders.replace(r, extra={"x": object()})
    with pytest.raises(Exception):
        reminders.close(bad, T, "x", None)
    assert r.path.read_text(encoding="utf-8") == text
    assert not (reminders.folder_of(tmp_path) / ".curation-log").exists()


def test_write_renders_before_it_creates_the_file(tmp_path, monkeypatch):
    def boom(_):
        raise RuntimeError("render failed")
    monkeypatch.setattr(reminders, "_render", boom)
    with pytest.raises(RuntimeError):
        reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0)
    assert not list(reminders.folder_of(tmp_path).glob("*"))


@pytest.mark.parametrize("value, ok", [("", True), ("shown_before: null\n", True), ("shown_before: []\n", True),
                                       ("shown_before: [1, 2]\n", True), ("shown_before: 0\n", False),
                                       ("shown_before: ''\n", False), ("shown_before: false\n", False),
                                       ("shown_before: [-1]\n", False), ("shown_before: [true]\n", False),
                                       ("in_sessions: 1000\n", False), ("in_sessions: 999\n", True)])
def test_shown_before_and_in_sessions_are_validated_on_load(value, ok, tmp_path):
    r = reminders.write(tmp_path, "project", topic="t", body="b", today=T, count=0)
    r.path.write_text(f"---\ntopic: t\n{value}---\nb\n", encoding="utf-8")
    loaded = reminders.load(tmp_path, "project")[0]
    assert (loaded.error is None) is ok
