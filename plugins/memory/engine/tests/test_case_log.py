import datetime
import subprocess

import pytest

import mem
import records

D1, D2 = datetime.date(2026, 11, 20), datetime.date(2026, 11, 25)
KEY = "0123456789ab"


def transcript(tmp_path, session="session s1", project=KEY, today=D1):
    return records.write_memory(tmp_path / ".memory", "project", kind="lesson", claim="Run the linter before the tests.",
                                body="", today=today, origin="transcript",
                                sources=[records.sighting_entry(session, project)])


def reload(m):
    [loaded] = records.load_memories(m.path.parent, m.scope)
    return loaded


def test_case_round_trip():
    entry = records.case_entry(D1, "session abc", "failed")
    assert entry == "2026-11-20 session abc failed"
    assert records.case(entry) == records.Case(D1, "session abc", "failed")


def test_what_is_not_a_case():
    for text in ("2026-13-40 session abc failed", "2026-11-20 session abc", "2026-11-20 session abc broken",
                 "session abc failed", "2026-11-20 a book failed", ""):
        assert records.case(text) is None


def test_add_sighting_records_the_case_of_a_new_session(tmp_path, monkeypatch):
    m = transcript(tmp_path)
    writes = []
    real = records.update
    monkeypatch.setattr(records, "update", lambda *a, **k: writes.append(1) or real(*a, **k))
    got, new = records.add_sighting(m, f"session s2 project {KEY}", D2, outcome="failed")
    assert new and len(writes) == 1
    assert got.sources == [f"session s1 project {KEY}", f"session s2 project {KEY}"]
    assert got.log == ["2026-11-25 session s2 failed"]


def test_the_day_of_the_session_wins_over_today(tmp_path):
    m = transcript(tmp_path)
    got, _ = records.add_sighting(m, "session s2", D2, outcome="worked", on=D1)
    assert got.log == ["2026-11-20 session s2 worked"] and got.last_observed == D2


def test_a_counted_session_still_gets_its_case(tmp_path):
    m = transcript(tmp_path)
    m, _ = records.add_sighting(m, "session s2", D1, outcome="failed")
    before = (m.observed, list(m.sources))
    got, new = records.add_sighting(m, "session s2", D2, outcome="worked")
    assert not new and (got.observed, got.sources) == before
    assert got.log == ["2026-11-20 session s2 failed", "2026-11-25 session s2 worked"]


def test_one_session_gives_one_case_per_outcome(tmp_path):
    m = transcript(tmp_path)
    m, _ = records.add_sighting(m, "session s2", D1, outcome="failed")
    m, _ = records.add_sighting(m, "session s2", D2, outcome="failed")
    assert m.log == ["2026-11-20 session s2 failed"]
    m, _ = records.add_sighting(m, "session s2", D2, outcome="seen")
    assert m.log == ["2026-11-20 session s2 failed"]
    m, _ = records.add_sighting(m, "session s3", D1, outcome="seen")
    m, _ = records.add_sighting(m, "session s3", D2, outcome="failed")
    assert m.log[1:] == ["2026-11-20 session s3 seen", "2026-11-25 session s3 failed"]


def test_add_case_refuses_what_is_not_a_case(tmp_path):
    m = transcript(tmp_path)
    with pytest.raises(ValueError):
        records.add_case(m, "a book", D1, "failed", D2)
    with pytest.raises(ValueError):
        records.add_case(m, "session s1", D1, "broken", D2)


def test_cases_are_sorted_by_date_keeping_file_order(tmp_path):
    m = transcript(tmp_path)
    for s, d in (("s2", D2), ("s3", D1), ("s4", D1)):
        m, _ = records.add_case(m, s if s.startswith("session") else f"session {s}", d, "failed", D2)
    assert [c.session for c in records.cases(m)] == ["session s3", "session s4", "session s2"]


def test_a_new_transcript_record_starts_its_log(tmp_path):
    m = records.write_memory(tmp_path / ".memory", "project", kind="lesson", claim="One.", body="", today=D1,
                             origin="transcript", sources=[f"session s1 project {KEY}"], outcome="failed")
    assert m.log == ["2026-11-20 session s1 failed"] and reload(m).log == m.log
    n = records.write_memory(tmp_path / ".memory", "project", kind="lesson", claim="Two.", body="", today=D1,
                             origin="transcript", sources=[f"session s1 project {KEY}"])
    assert "log" not in n.path.read_text()


def test_a_wrong_log_value_reads_as_absent(tmp_path):
    for i, value in enumerate(("yes", '["2026-11-20 session a failed", "nonsense", 7]')):
        (tmp_path / f"m{i}.md").write_text(f"---\nkind: lesson\nclaim: Raw {i}.\nlog: {value}\n---\nbody\n")
    first, second = records.load_memories(tmp_path, "project")
    assert first.error is None and first.log == []
    assert second.error is None and second.log == ["2026-11-20 session a failed"]


def test_an_old_file_is_not_rewritten_by_a_read(tmp_path):
    m = transcript(tmp_path)
    text = m.path.read_text()
    assert "log" not in text
    [loaded] = records.load_memories(m.path.parent, "project")
    assert m.path.read_text() == text and records.cases(loaded) == []


def test_sources_and_standing_ignore_the_log(tmp_path):
    m = transcript(tmp_path)
    a = records.replace(m, log=[])
    b = records.replace(m, log=["2026-11-20 session s1 failed"])
    assert (records.sessions(a), records.projects(a), records.standing(a)) == \
        (records.sessions(b), records.projects(b), records.standing(b))


# versions of the short form, their tallies and "got worse"

def day(n):
    return D1 + datetime.timedelta(days=n)


@pytest.fixture
def project(tmp_path, monkeypatch):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(tmp_path))
    return tmp_path


def with_cases(m, *specs):
    """specs: (day offset from D1, outcome); one session per case."""
    for n, outcome in specs:
        m, _ = records.add_case(m, f"session c{len(m.log)}", day(n), outcome, day(n))
    return m


def versioned(tmp_path, *texts_on):
    """A transcript lesson whose short form changed on the given day offsets: (offset, text)."""
    m = transcript(tmp_path)
    for n, text in texts_on:
        m = records.update(m, day(n), short=text)
    return m


def test_versions_grow_with_each_different_short_form(tmp_path):
    m = transcript(tmp_path)
    m = records.update(m, D1, short="First text.")
    assert len(m.versions) == 1
    m = records.update(m, day(1), short="Second text.")
    assert len(m.versions) == 2
    m = records.update(m, day(2), short=None)
    assert len(m.versions) == 2
    m = records.update(m, day(3), short="First text.")
    assert len(m.versions) == 3 and m.versions[2].endswith(" First text.")


def test_two_changes_on_one_day_are_one_version_with_the_later_text(tmp_path):
    m = transcript(tmp_path)
    m = records.update(m, D1, short="First text.")
    m = records.update(m, D1, short="Second text.")
    assert m.versions == ["2026-11-20 Second text."]


def test_the_same_short_form_written_again_adds_no_version(tmp_path):
    m = versioned(tmp_path, (0, "First text."))
    again = records.update(m, day(2), short=m.short)
    assert again.versions == m.versions


def test_a_short_form_with_odd_characters_round_trips(tmp_path):
    odd = '2026-01-01: check "real" data first'
    m = versioned(tmp_path, (0, odd))
    assert records.version_list(reload(m)) == [(D1, odd)]


def test_remember_with_a_short_form_starts_the_list(tmp_path):
    m = records.write_memory(tmp_path / ".memory", "project", kind="lesson", claim="One.", body="", today=D1,
                             short="Run the linter first.")
    assert m.versions == ["2026-11-20 Run the linter first."] and reload(m).versions == m.versions


def test_a_wrong_versions_or_reviewed_value_reads_as_absent(tmp_path):
    for i, extra in enumerate(("versions: yes\nreviewed: soon", 'versions: ["2026-11-20 text", "nonsense"]')):
        (tmp_path / f"m{i}.md").write_text(f"---\nkind: lesson\nclaim: Raw {i}.\n{extra}\n---\nbody\n")
    first, second = records.load_memories(tmp_path, "project")
    assert first.error is None and first.versions == [] and first.reviewed is None
    assert second.error is None and second.versions == ["2026-11-20 text"]


def test_a_lesson_written_before_reads_as_one_version(tmp_path):
    m = transcript(tmp_path)
    m = records.update(m, D1, short="Old text.", released=D1)
    records.update(m, D1, versions=None)
    old = reload(m)
    raw = old.path.read_bytes()
    assert old.versions == [] and records.version_list(old) == [(D1, "Old text.")]
    assert old.path.read_bytes() == raw
    unreleased = records.replace(old, released=None, created=D2)
    assert records.version_list(unreleased) == [(D2, "Old text.")]
    assert records.version_list(records.replace(old, short=None)) == []


def test_the_first_change_of_an_old_lesson_keeps_its_old_wording(tmp_path):
    m = transcript(tmp_path)
    m = records.update(m, D1, short="Old text.", released=D1)
    m = records.update(m, D1, versions=None)
    got = records.update(reload(m), D2, short="new text")
    assert got.versions == ["2026-11-20 Old text.", "2026-11-25 new text"]


def test_the_fill_pass_adds_a_version(project, capsys):
    m = transcript(project)
    # the apply step of the fill runs `mem memory edit --short=... --user-read --topic=...`
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--short=Run the linter before the tests.", "--user-read",
                     "--topic=testing"]) == 0
    capsys.readouterr()
    got = reload(m)
    assert got.versions == [f"{datetime.date.today().isoformat()} Run the linter before the tests."]


def test_a_case_counts_for_the_version_before_it(tmp_path):
    m = versioned(tmp_path, (0, "First text."))
    m = with_cases(m, (-1, "failed"), (0, "worked"), (1, "failed"), (2, "worked"), (2, "seen"))
    [t] = records.tallies(m)
    assert (t.worked, t.failed, t.number, t.since, t.text) == (1, 1, 1, D1, "First text.")
    m = records.update(m, day(5), short="Second text.")
    m = with_cases(m, (6, "failed"))
    one, two = records.tallies(m)
    assert (one.worked, one.failed) == (1, 1) and (two.worked, two.failed) == (0, 1)


def test_marked_at_one_failure_not_listed(tmp_path):
    m = with_cases(versioned(tmp_path, (0, "First text.")), (1, "failed"))
    assert records.mark_words(m) == "version 1: worked 0, failed 1" and not records.got_worse(m)


def test_listed_when_failures_outnumber_the_good_cases(tmp_path):
    base = versioned(tmp_path, (0, "First text."))
    assert not records.got_worse(with_cases(base, *[(1, "worked")] * 3, *[(1, "failed")] * 2))


def test_listed_when_failures_outnumber_the_good_cases_by_the_count(tmp_path):
    base = versioned(tmp_path, (0, "First text."))
    assert records.got_worse(with_cases(base, (1, "worked"), (1, "failed"), (1, "failed")))


def test_listed_when_the_balance_is_below_the_version_before(tmp_path):
    def two(w2, f2, name):
        sub = tmp_path / name
        sub.mkdir()
        m = versioned(sub, (0, "First text."))
        m = with_cases(m, *[(1, "worked")] * 4, (1, "failed"))
        m = records.update(m, day(5), short="Second text.")
        specs = [(6, "worked")] * w2 + [(6, "failed")] * f2
        return with_cases(m, *specs)
    assert records.got_worse(two(3, 2, "a")) and not records.got_worse(two(5, 2, "b"))


def test_a_new_version_clears_the_listing(tmp_path):
    m = with_cases(versioned(tmp_path, (0, "First text.")), (1, "failed"), (2, "failed"))
    assert records.got_worse(m)
    m = records.update(m, day(3), short="Better text.")
    assert not records.got_worse(m) and records.mark_words(m) == ""


def test_reviewed_asks_for_two_more_failures(tmp_path):
    m = with_cases(versioned(tmp_path, (0, "First text.")), (1, "failed"), (2, "failed"))
    assert records.got_worse(m)
    m = records.update(m, day(3), reviewed=day(2))
    m = reload(m)
    assert m.reviewed == day(2) and not records.got_worse(m)
    assert records.mark_words(m) == "version 1: worked 0, failed 2"
    m = with_cases(m, (4, "failed"))
    assert not records.got_worse(reload(m))
    m = with_cases(reload(m), (5, "failed"))
    assert records.got_worse(reload(m))


def test_merge_joins_log_and_versions(project, capsys):
    keep = versioned(project, (0, "First text."))
    keep = with_cases(keep, (1, "failed"))
    drop = records.write_memory(project / ".memory", "project", kind="lesson", claim="Run the linter before the tests soon.",
                                body="", today=D1, origin="transcript", sources=[records.sighting_entry("session s9", KEY)])
    drop = records.update(drop, day(2), short="Other text.")
    drop, _ = records.add_case(drop, "session d1", day(2), "worked", day(2))
    drop, _ = records.add_case(drop, "session c0", day(1), "failed", day(2))   # the same entry as keep's
    assert mem.main(["merge", f"m:{keep.handle}", f"m:{drop.handle}", "--force"]) == 0
    capsys.readouterr()
    got = next(x for x in records.load_memories(project / ".memory", "project") if x.handle == keep.handle)
    assert got.log == ["2026-11-21 session c0 failed", "2026-11-22 session d1 worked"]
    assert got.versions == ["2026-11-20 First text.", "2026-11-22 Other text."]


def test_restore_brings_versions_back(project, capsys):
    m = versioned(project, (0, "First text."))
    before = m.versions
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--short=Second text."]) == 0
    assert len(reload(m).versions) == 2
    assert mem.main(["restore", f"m:{m.handle}"]) == 0
    capsys.readouterr()
    assert reload(m).versions == before
