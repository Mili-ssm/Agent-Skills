import datetime
import os
import subprocess
from pathlib import Path

import pytest

import capture
import mem
import records
import rules

MEM = Path(__file__).resolve().parents[2] / "bin" / "mem"

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
    # the automatic fill runs `mem memory edit --short=... --topic=...`, without --user-read
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--short=Run the linter before the tests.",
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
    # the kept record's text loads after the merge, so it is the newest version
    assert got.versions == ["2026-11-20 First text.", "2026-11-22 Other text.",
                            f"{datetime.date.today().isoformat()} First text."]


def merge_pair(project, keep_versions, keep_short, drop_versions, drop_short):
    """Merge two lessons with the given versions (lists of (offset, text)) and shorts; returns the kept record."""
    def lesson(claim, session, versions, short):
        m = records.write_memory(project / ".memory", "project", kind="lesson", claim=claim, body="", today=D1,
                                 origin="transcript", sources=[records.sighting_entry(session, KEY)])
        if not short:
            return m
        m = records.update(m, D1, short=short)
        return records.update(m, D1, versions=[f"{day(n).isoformat()} {t}" for n, t in versions])
    keep = lesson("Run the linter before the tests soon.", "session s1", keep_versions, keep_short)
    drop = lesson("Run the linter before the tests too.", "session s9", drop_versions, drop_short)
    assert mem.main(["merge", f"m:{keep.handle}", f"m:{drop.handle}", "--force"]) == 0
    return next(x for x in records.load_memories(project / ".memory", "project") if x.handle == keep.handle)


def test_merge_keeps_the_wording_of_a_lesson_written_before_versions(project, capsys):
    got = merge_pair(project, [], "Old text.", [(1, "Other text.")], "Other text.")
    capsys.readouterr()
    today = datetime.date.today().isoformat()
    assert got.versions == [f"{D1.isoformat()} Old text.", f"{day(1).isoformat()} Other text.", f"{today} Old text."]
    assert got.short == "Old text."


def test_merge_of_two_versions_on_one_day_keeps_the_kept_text(project, capsys):
    got = merge_pair(project, [(0, "Kept text.")], "Kept text.", [(0, "Dropped text.")], "Dropped text.")
    capsys.readouterr()
    assert got.versions == [f"{D1.isoformat()} Kept text."]


def test_merge_without_any_short_form_writes_no_versions(project, capsys):
    got = merge_pair(project, [], None, [], None)
    capsys.readouterr()
    assert got.versions == [] and "versions" not in got.path.read_text()


def test_merge_when_the_kept_text_is_already_last_adds_nothing(project, capsys):
    got = merge_pair(project, [(0, "A text."), (5, "B text.")], "B text.", [(0, "A text.")], "A text.")
    capsys.readouterr()
    assert got.versions == [f"{D1.isoformat()} A text.", f"{day(5).isoformat()} B text."]


def test_restore_brings_versions_back(project, capsys):
    m = versioned(project, (0, "First text."))
    before = m.versions
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--short=Second text."]) == 0
    assert len(reload(m).versions) == 2
    assert mem.main(["restore", f"m:{m.handle}"]) == 0
    capsys.readouterr()
    assert reload(m).versions == before


def run_mem(project, *args):
    return subprocess.run([str(MEM), *args], capture_output=True, text=True, cwd=project,
                          env={**os.environ, "MEM_PROJECT": str(project)})


def test_every_signal_has_an_outcome():
    failed = {"owner_correction", "failed_then_passed", "verified_review_finding", "delegation_failed", "rework",
              "repeated_tool_error"}
    worked = {"owner_approval", "owner_request_paid_off", "effective_practice"}
    seen = {"plan_changed_by_review", "decision_with_reason"}
    assert failed | worked | seen == set(capture.SIGNALS)
    assert {s: capture.outcome(s) for s in capture.SIGNALS} == \
        {**dict.fromkeys(failed, "failed"), **dict.fromkeys(worked, "worked"), **dict.fromkeys(seen, "seen")}
    assert capture.outcome("other") == "seen"


def test_confirm_records_outcome_and_day(project):
    m = transcript(project)
    first = run_mem(project, "confirm", f"m:{m.handle}", "--source", "session s2", "--outcome", "failed",
                    "--seen-on", "2026-11-20")
    assert first.returncode == 0, first.stderr
    assert reload(m).log == ["2026-11-20 session s2 failed"]
    again = run_mem(project, "confirm", f"m:{m.handle}", "--source", "session s2", "--outcome", "worked",
                    "--seen-on", "2026-11-21")
    assert again.returncode == 0 and again.stdout == f"m:{m.handle}\tcase worked added\n"
    got = reload(m)
    assert got.log == ["2026-11-20 session s2 failed", "2026-11-21 session s2 worked"]
    assert f"observed {got.observed}" in first.stdout and got.observed == 2


def test_confirm_refuses_a_wrong_day(project):
    m = transcript(project)
    before = m.path.read_bytes()
    done = run_mem(project, "confirm", f"m:{m.handle}", "--source", "session s2", "--seen-on", "2026-13-40")
    assert done.returncode == 2
    assert m.path.read_bytes() == before


def test_remember_of_a_known_claim_passes_the_case(project):
    m = transcript(project)
    done = run_mem(project, "remember", "--kind=lesson", f"--claim={m.claim}", "--origin", "transcript",
                   "--source", "session s2", "--outcome", "failed", "--seen-on", "2026-11-22")
    assert done.returncode == 3 and "sighting" in done.stdout, done.stderr
    got = reload(m)
    assert "session s2" in " ".join(got.sources) and got.log == ["2026-11-22 session s2 failed"]


def test_confirm_adds_a_case_to_a_counted_session_and_says_so(project):
    m = transcript(project)
    m, _ = records.add_sighting(m, "session s1", D1, outcome="failed")
    first = run_mem(project, "confirm", f"m:{m.handle}", "--source", "session s1", "--outcome", "worked",
                    "--seen-on", "2026-11-21")
    assert first.returncode == 0, first.stderr
    assert first.stdout == f"m:{m.handle}\tcase worked added\n"
    got = reload(m)
    assert (got.observed, got.sources) == (m.observed, m.sources)
    assert got.log == ["2026-11-20 session s1 failed", "2026-11-21 session s1 worked"]
    logs = lambda: [p.read_bytes() for p in sorted(project.rglob(records.CURATION_LOG))]
    before, journal = got.path.read_bytes(), logs()
    assert journal   # the first call journaled its change
    again = run_mem(project, "confirm", f"m:{m.handle}", "--source", "session s1", "--outcome", "worked")
    assert again.returncode == 3 and "is already a source: nothing changed" in again.stdout
    assert got.path.read_bytes() == before and logs() == journal


def test_confirm_of_a_counted_session_without_outcome_changes_nothing(project):
    m = transcript(project)
    before = m.path.read_bytes()
    done = run_mem(project, "confirm", f"m:{m.handle}", "--source", "session s1")
    assert done.returncode == 3 and "is already a source: nothing changed" in done.stdout
    assert m.path.read_bytes() == before


def test_remember_of_a_known_claim_adds_a_case_to_a_counted_session(project):
    m = transcript(project)
    done = run_mem(project, "remember", "--kind=lesson", f"--claim={m.claim}", "--origin", "transcript",
                   "--source", "session s1", "--outcome", "failed", "--seen-on", "2026-11-22")
    assert done.returncode == 3, done.stderr
    assert "is already counted" in done.stderr and f"case failed added to m:{m.handle}." in done.stderr
    got = reload(m)
    assert got.observed == m.observed and got.log == ["2026-11-22 session s1 failed"]


# --- the record is shown (C69) ---

from test_rules_session import K1, gfolder, write  # noqa: E402,F401


def ago(n):
    return datetime.date.today() - datetime.timedelta(days=n)


def shown(capsys, *argv):
    capsys.readouterr()
    assert mem.main(list(argv)) == 0
    return capsys.readouterr().out


def global_lesson(claim, versions=(), log=()):
    """A loaded global lesson whose versions and log are set by hand: versions (days ago, text), log (days ago, outcome)."""
    write(claim, short="First text.")
    [m] = [x for x in records.load_memories(Path(os.environ["MEM_MEMORIES"]), "global") if x.claim == claim]
    changes = {"versions": [records.version_entry(ago(n), t) for n, t in versions] or None,
               "log": [records.case_entry(ago(n), f"session z{i}", o) for i, (n, o) in enumerate(log)] or None}
    return records.update(m, datetime.date.today(), **changes)


def test_show_prints_each_version_with_its_tally(project, capsys):
    m = versioned(project, (-30, "First text."), (-10, "Second text."))
    m = with_cases(m, (-20, "worked"), (-5, "failed"))
    out = shown(capsys, "show", f"m:{m.handle}")
    today = datetime.date.today()
    since1, since2 = day(-30), day(-10)
    lines = [x for x in out.splitlines() if x.startswith("version ")]
    assert lines == [
        f"version 1 since {since1} ({(since2 - since1).days} days): worked 1, failed 0: First text.",
        f"version 2 since {since2} ({(today - since2).days} days): worked 0, failed 1: Second text."]
    assert out.index("short: Second text.") < out.index(lines[0])
    plain = transcript(project, session="session other")
    assert "version " not in shown(capsys, "show", f"m:{plain.handle}")


def test_show_of_a_lesson_written_before_this_change(project, capsys):
    m = transcript(project)
    m = records.update(m, D1, short="Old text.", released=D1)
    m = records.update(m, D1, versions=None)
    out = shown(capsys, "show", f"m:{m.handle}")
    assert f"version 1 since {D1} (" in out and out.count("version 1 since") == 1
    assert out.splitlines()[[i for i, x in enumerate(out.splitlines()) if x.startswith("version 1")][0]].endswith(": Old text.")


def test_rules_names_a_lesson_that_failed_and_the_block_is_unchanged(project, gfolder, capsys):
    global_lesson("Plain lesson.")
    first = shown(capsys, "rules")
    global_lesson("Failing lesson.", versions=[(10, "First text.")], log=[(5, "worked"), (4, "failed"), (3, "failed")])
    [m] = [x for x in records.load_memories(gfolder, "global") if x.claim == "Failing lesson."]
    out = shown(capsys, "rules")
    head, tail = out.split("Failed after it loaded:\n")
    assert tail == f"m:{m.handle}\tversion 1: worked 1, failed 2\n"
    # the same store with an empty log prints the block alone
    records.update(m, datetime.date.today(), log=None)
    assert shown(capsys, "rules") == head
    assert first.splitlines()[0] in head


def test_rules_more_has_the_column(project, gfolder, capsys):
    for i in range(10):
        global_lesson(f"Lesson number {i}.", versions=[(10, "First text.")],
                      log=[(5, "failed" if i % 2 else "worked")])
    rows = [x.split("\t") for x in shown(capsys, "rules", "--more").splitlines() if x.startswith("m:")]
    assert len(rows) >= 2 and all(len(r) == 7 for r in rows)
    for r in rows:
        failing = int(r[0].rsplit("-", 1)[1]) % 2
        assert r[-1] == ("version 1: worked 0, failed 1" if failing else "-")
    assert {r[-1] for r in rows} == {"-", "version 1: worked 0, failed 1"}


def test_session_start_block_is_unchanged(project, gfolder, capsys):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    before = shown(capsys, "session-index")
    records.update(m, datetime.date.today(), log=[records.case_entry(ago(2), "session q", "failed"),
                                                 records.case_entry(ago(1), "session r", "failed")])
    after = shown(capsys, "session-index")
    sentence = " Got worse: 1 loaded lesson needs a decision (mem curate)."  # the one line C68 adds to the first line
    assert before == after.replace(sentence, "") and sentence in after
    assert "First text." in after and "Failed after" not in after


# --- the owner's queue (C68) ---

CATEGORY = "balance got worse after loading"
FAILS = [(5, "failed"), (4, "failed")]


def worse_lesson(claim, log=FAILS, versions=((10, "First text."),)):
    return global_lesson(claim, versions=list(versions), log=list(log))


def curated(capsys, *argv):
    return shown(capsys, "curate", *argv)


def queue(out):
    """The lines of the category: its heading and what follows until the next heading (an unindented line)."""
    lines = out.splitlines()
    start = next((i for i, x in enumerate(lines) if x.startswith(CATEGORY)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].startswith(" ")), len(lines))
    return lines[start:end]


def test_curate_lists_a_lesson_that_got_worse(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.", log=[(5, "failed")])
    assert queue(curated(capsys, "--global")) is None
    records.update(m, datetime.date.today(), log=[records.case_entry(ago(5), "session q", "failed"),
                                                 records.case_entry(ago(4), "session r", "failed")])
    out = queue(curated(capsys, "--global"))
    assert out[0] == (f"{CATEGORY} (decide: reword it or go back with mem memory edit <h> --short, drop it with "
                      "mem forget <h>, or keep the wording with mem triage accept <h>)")
    assert out[1] == f"  m:{m.handle}  loaded  Failing lesson."
    assert out[2:] == [f"    version 1 since {ago(10)} (10 days): worked 0, failed 2: First text."]
    assert reload(m).triage is None and "triage:" not in m.path.read_text()
    assert "First text." in shown(capsys, "rules")


def test_curate_shows_the_version_before(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.", versions=[(20, "First text."), (10, "Second text.")],
                     log=[(15, "worked"), (5, "failed"), (4, "failed")])
    out = queue(curated(capsys, "--global"))
    assert out[2:] == [f"    version 1 since {ago(20)} (10 days): worked 1, failed 0: First text.",
                       f"    version 2 since {ago(10)} (10 days): worked 0, failed 2: Second text."]


def test_curate_lists_a_project_lesson(project, gfolder, capsys):
    write("Project failing lesson.", short="First text.", scope="project")
    [m] = records.load_memories(project / ".memory", "project")
    records.update(m, datetime.date.today(), versions=[records.version_entry(ago(10), "First text.")],
                   log=[records.case_entry(ago(5), "session q", "failed"), records.case_entry(ago(4), "session r", "failed")])
    out = queue(curated(capsys))
    assert out[1] == f"  m:{m.handle}  loaded  Project failing lesson."
    assert queue(curated(capsys, "--global")) is None


def test_a_lesson_that_does_not_load_is_not_listed(project, gfolder, capsys):
    today = datetime.date.today()
    # written first: `write` accepts every lesson that awaits triage
    no, index, pending, held = (worse_lesson(c) for c in ("Lesson that never loads.", "Lesson that is index only.",
                                                         "Lesson that awaits triage.", "Lesson in quarantine."))
    records.update(no, today, load="no")
    records.update(index, today, load="index")
    records.update(pending, today, owner_confirmed=None, triage="pending")  # the owner's word would end the triage
    records.update(held, today, sources=[held.sources[0]], owner_confirmed=None)
    now = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert all(records.got_worse(now[m.handle]) for m in (no, index, pending, held))
    assert queue(curated(capsys, "--global")) is None
    assert records.quarantined(now[held.handle]) and now[pending.handle].triage == "pending"


def test_a_lesson_left_out_by_the_cap_is_listed_as_such(project, gfolder, capsys):
    for i in range(rules.RULES_MAX):
        write(f"Strong lesson number {i}.", short=f"Strong rule {i}.", weight="strong")
    m = worse_lesson("Failing lesson.")
    out = queue(curated(capsys, "--global"))
    assert out[1] == f"  m:{m.handle}  left out by the cap  Failing lesson."
    assert "Failing lesson" not in shown(capsys, "rules").split("Failed after")[0]


def test_session_start_counts_what_got_worse(project, gfolder, capsys):
    a = worse_lesson("First failing lesson.", log=[(5, "failed")])
    assert "Got worse" not in shown(capsys, "session-index")
    records.update(a, datetime.date.today(), log=[records.case_entry(ago(5), "session q", "failed"),
                                                 records.case_entry(ago(4), "session r", "failed")])
    assert "Got worse: 1 loaded lesson needs a decision (mem curate)." in shown(capsys, "session-index")
    worse_lesson("Second failing lesson.")
    out = shown(capsys, "session-index")
    assert "Got worse: 2 loaded lessons need a decision (mem curate)." in out
    assert len(out) <= mem._INDEX_LIMIT


def test_a_fault_in_the_count_leaves_the_rules_block(project, gfolder, capsys, monkeypatch):
    worse_lesson("Failing lesson.")
    plain = shown(capsys, "session-index").replace(
        " Got worse: 1 loaded lesson needs a decision (mem curate).", "")
    assert "Got worse" not in plain and "First text." in plain
    monkeypatch.setattr(records, "got_worse", lambda m: 1 / 0)
    assert shown(capsys, "session-index") == plain


def test_a_new_short_form_clears_the_listing(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.")
    assert queue(curated(capsys, "--global")) is not None
    shown(capsys, "memory", "edit", m.handle, "--global", "--short", "Better text.")
    assert queue(curated(capsys, "--global")) is None
    assert len([x for x in shown(capsys, "show", f"m:{m.handle}").splitlines() if x.startswith("version ")]) == 2
