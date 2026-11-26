import datetime
import os
import subprocess
from pathlib import Path

import capture
import mem
import pytest
import records
import rules
from test_rules_session import FIT, gfolder, pad, write

# re-exported: pytest finds the fixture in this module by its name
__all__ = ["gfolder"]

EXIT_USAGE = 2
EXIT_NOTHING = 3
TWO_VERSIONS = 2
THREE_VERSIONS = 3
OBSERVED_TWICE = 2
MIN_ROWS = 2
ROW_FIELDS = 7

MEM = Path(__file__).resolve().parents[2] / "bin" / "mem"

D1, D2 = datetime.date(2026, 11, 20), datetime.date(2026, 11, 25)
KEY = "0123456789ab"


def transcript(tmp_path, session="session s1", project: str | None = KEY, today=D1):
    return records.write_memory(
        tmp_path / ".memory",
        "project",
        kind="lesson",
        claim="Run the linter before the tests.",
        body="",
        today=today,
        origin="transcript",
        sources=[records.sighting_entry(session, project)],
    )


def reload(m):
    [loaded] = records.load_memories(m.path.parent, m.scope)
    return loaded


def test_case_round_trip():
    entry = records.case_entry(D1, "session abc", "failed")
    assert entry == "2026-11-20 session abc failed"
    assert records.case(entry) == records.Case(D1, "session abc", "failed")


def test_what_is_not_a_case():
    for text in (
        "2026-13-40 session abc failed",
        "2026-11-20 session abc",
        "2026-11-20 session abc broken",
        "session abc failed",
        "2026-11-20 a book failed",
        "",
    ):
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
        m, _ = records.add_case(
            m, s if s.startswith("session") else f"session {s}", d, "failed", D2
        )
    assert [c.session for c in records.cases(m)] == ["session s3", "session s4", "session s2"]


def test_a_new_transcript_record_starts_its_log(tmp_path):
    m = records.write_memory(
        tmp_path / ".memory",
        "project",
        kind="lesson",
        claim="One.",
        body="",
        today=D1,
        origin="transcript",
        sources=[f"session s1 project {KEY}"],
        outcome="failed",
    )
    assert m.log == ["2026-11-20 session s1 failed"] and reload(m).log == m.log
    n = records.write_memory(
        tmp_path / ".memory",
        "project",
        kind="lesson",
        claim="Two.",
        body="",
        today=D1,
        origin="transcript",
        sources=[f"session s1 project {KEY}"],
    )
    assert "log" not in n.path.read_text()


def test_a_wrong_log_value_reads_as_absent(tmp_path):
    for i, value in enumerate(("yes", '["2026-11-20 session a failed", "nonsense", 7]')):
        (tmp_path / f"m{i}.md").write_text(
            f"---\nkind: lesson\nclaim: Raw {i}.\nlog: {value}\n---\nbody\n"
        )
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
    assert (records.sessions(a), records.projects(a), records.standing(a)) == (
        records.sessions(b),
        records.projects(b),
        records.standing(b),
    )


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
    assert len(m.versions) == TWO_VERSIONS
    m = records.update(m, day(2), short=None)
    assert len(m.versions) == TWO_VERSIONS
    m = records.update(m, day(3), short="First text.")
    assert len(m.versions) == THREE_VERSIONS and m.versions[2].endswith(" First text.")


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
    m = records.write_memory(
        tmp_path / ".memory",
        "project",
        kind="lesson",
        claim="One.",
        body="",
        today=D1,
        short="Run the linter first.",
    )
    assert m.versions == ["2026-11-20 Run the linter first."] and reload(m).versions == m.versions


def test_a_wrong_versions_or_reviewed_value_reads_as_absent(tmp_path):
    for i, extra in enumerate((
        "versions: yes\nreviewed: soon",
        'versions: ["2026-11-20 text", "nonsense"]',
    )):
        (tmp_path / f"m{i}.md").write_text(
            f"---\nkind: lesson\nclaim: Raw {i}.\n{extra}\n---\nbody\n"
        )
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
    today = datetime.date.today()
    m = transcript(project)
    # the automatic fill runs `mem memory edit --short=... --topic=...`, without --user-read
    assert (
        mem.main([
            "memory",
            "edit",
            f"m:{m.handle}",
            "--short=Run the linter before the tests.",
            "--topic=testing",
        ])
        == 0
    )
    capsys.readouterr()
    got = reload(m)
    assert got.versions == [f"{today.isoformat()} Run the linter before the tests."]


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
    assert not records.got_worse(m) and not records.mark_words(m)


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
    today = datetime.date.today()
    keep = versioned(project, (0, "First text."))
    keep = with_cases(keep, (1, "failed"))
    drop = records.write_memory(
        project / ".memory",
        "project",
        kind="lesson",
        claim="Run the linter before the tests soon.",
        body="",
        today=D1,
        origin="transcript",
        sources=[records.sighting_entry("session s9", KEY)],
    )
    drop = records.update(drop, day(2), short="Other text.")
    drop, _ = records.add_case(drop, "session d1", day(2), "worked", day(2))
    drop, _ = records.add_case(
        drop, "session c0", day(1), "failed", day(2)
    )  # the same entry as keep's
    assert mem.main(["merge", f"m:{keep.handle}", f"m:{drop.handle}", "--force"]) == 0
    capsys.readouterr()
    got = next(
        x for x in records.load_memories(project / ".memory", "project") if x.handle == keep.handle
    )
    assert got.log == ["2026-11-21 session c0 failed", "2026-11-22 session d1 worked"]
    # the kept record's text loads after the merge, so it is the newest version
    assert got.versions == [
        "2026-11-20 First text.",
        "2026-11-22 Other text.",
        f"{today.isoformat()} First text.",
    ]


def merge_pair(project, keep_versions, keep_short, drop_versions, drop_short):
    """Merge two lessons with the given versions (lists of (offset, text)) and shorts; returns the kept record."""

    def lesson(claim, session, versions, short):
        m = records.write_memory(
            project / ".memory",
            "project",
            kind="lesson",
            claim=claim,
            body="",
            today=D1,
            origin="transcript",
            sources=[records.sighting_entry(session, KEY)],
        )
        if not short:
            return m
        m = records.update(m, D1, short=short)
        return records.update(m, D1, versions=[f"{day(n).isoformat()} {t}" for n, t in versions])

    keep = lesson("Run the linter before the tests soon.", "session s1", keep_versions, keep_short)
    drop = lesson("Run the linter before the tests too.", "session s9", drop_versions, drop_short)
    assert mem.main(["merge", f"m:{keep.handle}", f"m:{drop.handle}", "--force"]) == 0
    return next(
        x for x in records.load_memories(project / ".memory", "project") if x.handle == keep.handle
    )


def test_merge_keeps_the_wording_of_a_lesson_written_before_versions(project, capsys):
    today = datetime.date.today().isoformat()
    got = merge_pair(project, [], "Old text.", [(1, "Other text.")], "Other text.")
    capsys.readouterr()
    assert got.versions == [
        f"{D1.isoformat()} Old text.",
        f"{day(1).isoformat()} Other text.",
        f"{today} Old text.",
    ]
    assert got.short == "Old text."


def test_merge_of_two_versions_on_one_day_keeps_the_kept_text(project, capsys):
    got = merge_pair(
        project, [(0, "Kept text.")], "Kept text.", [(0, "Dropped text.")], "Dropped text."
    )
    capsys.readouterr()
    assert got.versions == [f"{D1.isoformat()} Kept text."]


def test_merge_without_any_short_form_writes_no_versions(project, capsys):
    got = merge_pair(project, [], None, [], None)
    capsys.readouterr()
    assert got.versions == [] and "versions" not in got.path.read_text()


def test_merge_when_the_kept_text_is_already_last_adds_nothing(project, capsys):
    got = merge_pair(
        project, [(0, "A text."), (5, "B text.")], "B text.", [(0, "A text.")], "A text."
    )
    capsys.readouterr()
    assert got.versions == [f"{D1.isoformat()} A text.", f"{day(5).isoformat()} B text."]


def test_restore_brings_versions_back(project, capsys):
    m = versioned(project, (0, "First text."))
    before = m.versions
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--short=Second text."]) == 0
    assert len(reload(m).versions) == TWO_VERSIONS
    assert mem.main(["restore", f"m:{m.handle}"]) == 0
    capsys.readouterr()
    assert reload(m).versions == before


def run_mem(project, *args):
    return subprocess.run(
        [str(MEM), *args],
        capture_output=True,
        text=True,
        cwd=project,
        env={**os.environ, "MEM_PROJECT": str(project)},
        check=False,
    )


def test_every_signal_has_an_outcome():
    failed = {
        "owner_correction",
        "failed_then_passed",
        "verified_review_finding",
        "delegation_failed",
        "rework",
        "repeated_tool_error",
    }
    worked = {"owner_approval", "owner_request_paid_off", "effective_practice"}
    seen = {"plan_changed_by_review", "decision_with_reason"}
    assert failed | worked | seen == set(capture.SIGNALS)
    assert {s: capture.outcome(s) for s in capture.SIGNALS} == {
        **dict.fromkeys(failed, "failed"),
        **dict.fromkeys(worked, "worked"),
        **dict.fromkeys(seen, "seen"),
    }
    assert capture.outcome("other") == "seen"


def test_confirm_records_outcome_and_day(project):
    m = transcript(project)
    first = run_mem(
        project,
        "confirm",
        f"m:{m.handle}",
        "--source",
        "session s2",
        "--outcome",
        "failed",
        "--seen-on",
        "2026-11-20",
    )
    assert first.returncode == 0, first.stderr
    assert reload(m).log == ["2026-11-20 session s2 failed"]
    again = run_mem(
        project,
        "confirm",
        f"m:{m.handle}",
        "--source",
        "session s2",
        "--outcome",
        "worked",
        "--seen-on",
        "2026-11-21",
    )
    assert again.returncode == 0 and again.stdout == f"m:{m.handle}\tcase worked added\n"
    got = reload(m)
    assert got.log == ["2026-11-20 session s2 failed", "2026-11-21 session s2 worked"]
    assert f"observed {got.observed}" in first.stdout and got.observed == OBSERVED_TWICE


def test_confirm_refuses_a_wrong_day(project):
    m = transcript(project)
    before = m.path.read_bytes()
    done = run_mem(
        project, "confirm", f"m:{m.handle}", "--source", "session s2", "--seen-on", "2026-13-40"
    )
    assert done.returncode == EXIT_USAGE
    assert m.path.read_bytes() == before


def test_remember_of_a_known_claim_passes_the_case(project):
    m = transcript(project)
    done = run_mem(
        project,
        "remember",
        "--kind=lesson",
        f"--claim={m.claim}",
        "--origin",
        "transcript",
        "--source",
        "session s2",
        "--outcome",
        "failed",
        "--seen-on",
        "2026-11-22",
    )
    assert done.returncode == EXIT_NOTHING and "sighting" in done.stdout, done.stderr
    got = reload(m)
    assert "session s2" in " ".join(got.sources) and got.log == ["2026-11-22 session s2 failed"]


def test_confirm_adds_a_case_to_a_counted_session_and_says_so(project):
    m = transcript(project)
    m, _ = records.add_sighting(m, "session s1", D1, outcome="failed")
    first = run_mem(
        project,
        "confirm",
        f"m:{m.handle}",
        "--source",
        "session s1",
        "--outcome",
        "worked",
        "--seen-on",
        "2026-11-21",
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout == f"m:{m.handle}\tcase worked added\n"
    got = reload(m)
    assert (got.observed, got.sources) == (m.observed, m.sources)
    assert got.log == ["2026-11-20 session s1 failed", "2026-11-21 session s1 worked"]
    logs = lambda: [p.read_bytes() for p in sorted(project.rglob(records.CURATION_LOG))]
    before, journal = got.path.read_bytes(), logs()
    assert journal  # the first call journaled its change
    again = run_mem(
        project, "confirm", f"m:{m.handle}", "--source", "session s1", "--outcome", "worked"
    )
    assert (
        again.returncode == EXIT_NOTHING and "is already a source: nothing changed" in again.stdout
    )
    assert got.path.read_bytes() == before and logs() == journal


def test_confirm_of_a_counted_session_without_outcome_changes_nothing(project):
    m = transcript(project)
    before = m.path.read_bytes()
    done = run_mem(project, "confirm", f"m:{m.handle}", "--source", "session s1")
    assert done.returncode == EXIT_NOTHING and "is already a source: nothing changed" in done.stdout
    assert m.path.read_bytes() == before


def test_remember_of_a_known_claim_adds_a_case_to_a_counted_session(project):
    m = transcript(project)
    done = run_mem(
        project,
        "remember",
        "--kind=lesson",
        f"--claim={m.claim}",
        "--origin",
        "transcript",
        "--source",
        "session s1",
        "--outcome",
        "failed",
        "--seen-on",
        "2026-11-22",
    )
    assert done.returncode == EXIT_NOTHING, done.stderr
    assert (
        "is already counted" in done.stderr and f"case failed added to m:{m.handle}." in done.stderr
    )
    got = reload(m)
    assert got.observed == m.observed and got.log == ["2026-11-22 session s1 failed"]


# --- the record is shown (C69) ---


TODAY = datetime.date.today()  # read once: the helpers below derive every date from it


def ago(n):
    return TODAY - datetime.timedelta(days=n)


def shown(capsys, *argv):
    capsys.readouterr()
    assert mem.main(list(argv)) == 0
    return capsys.readouterr().out


def global_lesson(claim, versions=(), log=(), short="First text."):
    """A loaded global lesson whose versions and log are set by hand: versions (days ago, text), log (days ago, outcome)."""
    write(claim, short=short)
    [m] = [
        x
        for x in records.load_memories(Path(os.environ["MEM_MEMORIES"]), "global")
        if x.claim == claim
    ]
    changes = {
        "versions": [records.version_entry(ago(n), t) for n, t in versions] or None,
        "log": [records.case_entry(ago(n), f"session z{i}", o) for i, (n, o) in enumerate(log)]
        or None,
    }
    return records.update(m, TODAY, **changes)


def test_show_prints_each_version_with_its_tally(project, capsys):
    today = datetime.date.today()
    m = versioned(project, (-30, "First text."), (-10, "Second text."))
    m = with_cases(m, (-20, "worked"), (-5, "failed"))
    out = shown(capsys, "show", f"m:{m.handle}")
    since1, since2 = day(-30), day(-10)
    lines = [x for x in out.splitlines() if x.startswith("version ")]
    assert lines == [
        f"version 1 since {since1} ({(since2 - since1).days} days): worked 1, failed 0: First text.",
        f"version 2 since {since2} ({(today - since2).days} days): worked 0, failed 1: Second text.",
    ]
    assert out.index("short: Second text.") < out.index(lines[0])
    plain = transcript(project, session="session other")
    assert "version " not in shown(capsys, "show", f"m:{plain.handle}")


def test_show_of_a_lesson_written_before_this_change(project, capsys):
    m = transcript(project)
    m = records.update(m, D1, short="Old text.", released=D1)
    m = records.update(m, D1, versions=None)
    out = shown(capsys, "show", f"m:{m.handle}")
    assert f"version 1 since {D1} (" in out and out.count("version 1 since") == 1
    lines = out.splitlines()
    assert lines[next(i for i, x in enumerate(lines) if x.startswith("version 1"))].endswith(
        ": Old text."
    )


def test_rules_names_a_lesson_that_failed_and_the_block_is_unchanged(project, gfolder, capsys):
    global_lesson("Plain lesson.")
    first = shown(capsys, "rules")
    global_lesson(
        "Failing lesson.",
        versions=[(10, "First text.")],
        log=[(5, "worked"), (4, "failed"), (3, "failed")],
    )
    [m] = [x for x in records.load_memories(gfolder, "global") if x.claim == "Failing lesson."]
    out = shown(capsys, "rules")
    head, tail = out.split("Failed after it loaded:\n")
    assert tail == f"m:{m.handle}\tversion 1: worked 1, failed 2\n"
    # the same store with an empty log prints the block alone
    records.update(m, TODAY, log=None)
    assert shown(capsys, "rules") == head
    assert first.splitlines()[0] in head


def test_rules_more_has_the_column(project, gfolder, capsys):
    for i in range(FIT + 4):
        global_lesson(
            f"Lesson number {i}.",
            versions=[(10, "First text.")],
            short=pad(f"Rule {i}."),
            log=[(5, "failed" if i % 2 else "worked")],
        )
    rows = [
        x.split("\t") for x in shown(capsys, "rules", "--more").splitlines() if x.startswith("m:")
    ]
    assert len(rows) >= MIN_ROWS and all(len(r) == ROW_FIELDS for r in rows)
    for r in rows:
        failing = int(r[0].rsplit("-", 1)[1]) % 2
        assert r[-1] == ("version 1: worked 0, failed 1" if failing else "-")
    assert {r[-1] for r in rows} == {"-", "version 1: worked 0, failed 1"}


def rules_block(text):
    """The rules block of the session start text: from its header line to the end of the rule lines and the more line."""
    lines = text.splitlines()
    return "\n".join(
        lines[next(i for i, x in enumerate(lines) if x.startswith("memory: lessons learned")) :]
    )


def test_session_start_block_is_unchanged(project, gfolder, capsys):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    before = shown(capsys, "session-index")
    records.update(
        m,
        TODAY,
        log=[
            records.case_entry(ago(2), "session q", "failed"),
            records.case_entry(ago(1), "session r", "failed"),
        ],
    )
    after = shown(capsys, "session-index")
    sentence = "Got worse: 1 loaded lesson needs a decision (mem curate)."  # what C68 adds to the first line
    assert sentence in after and sentence not in before
    assert rules_block(before) == rules_block(after) and "First text." in rules_block(after)
    assert "Failed after" not in after


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
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith(" ")), len(lines)
    )
    return lines[start:end]


def queued(out):
    """`queue`, for a category that must be present."""
    lines = queue(out)
    assert lines is not None
    return lines


def test_curate_lists_a_lesson_that_got_worse(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.", log=[(5, "failed")])
    assert queue(curated(capsys, "--global")) is None
    records.update(
        m,
        TODAY,
        log=[
            records.case_entry(ago(5), "session q", "failed"),
            records.case_entry(ago(4), "session r", "failed"),
        ],
    )
    out = queued(curated(capsys, "--global"))
    assert out[0] == (
        f"{CATEGORY} (decide: reword it or go back with mem memory edit <h> --short, drop it with "
        "mem forget <h>, or keep the wording with mem triage accept <h>)"
    )
    assert out[1] == f"  m:{m.handle}  loaded  Failing lesson."
    assert out[2:] == [f"    version 1 since {ago(10)} (10 days): worked 0, failed 2: First text."]
    assert reload(m).triage is None and "triage:" not in m.path.read_text()
    assert "First text." in shown(capsys, "rules")  # the rules output prints the short form


def test_curate_shows_the_version_before(project, gfolder, capsys):
    worse_lesson(
        "Failing lesson.",
        versions=[(20, "First text."), (10, "Second text.")],
        log=[(15, "worked"), (5, "failed"), (4, "failed")],
    )
    out = queued(curated(capsys, "--global"))
    assert out[2:] == [
        f"    version 1 since {ago(20)} (10 days): worked 1, failed 0: First text.",
        f"    version 2 since {ago(10)} (10 days): worked 0, failed 2: Second text.",
    ]


def test_curate_lists_a_project_lesson(project, gfolder, capsys):
    write("Project failing lesson.", short="First text.", scope="project")
    [m] = records.load_memories(project / ".memory", "project")
    records.update(
        m,
        TODAY,
        versions=[records.version_entry(ago(10), "First text.")],
        log=[
            records.case_entry(ago(5), "session q", "failed"),
            records.case_entry(ago(4), "session r", "failed"),
        ],
    )
    out = queued(curated(capsys))
    assert out[1] == f"  m:{m.handle}  loaded  Project failing lesson."
    assert queue(curated(capsys, "--global")) is None


def test_a_lesson_that_does_not_load_is_not_listed(project, gfolder, capsys):
    today = datetime.date.today()
    # written first: `write` accepts every lesson that awaits triage
    no, index, pending, held = (
        worse_lesson(c)
        for c in (
            "Lesson that never loads.",
            "Lesson that is index only.",
            "Lesson that awaits triage.",
            "Lesson in quarantine.",
        )
    )
    records.update(no, today, load="no")
    records.update(index, today, load="index")
    records.update(
        pending, today, owner_confirmed=None, triage="pending"
    )  # the owner's word would end the triage
    records.update(held, today, sources=[held.sources[0]], owner_confirmed=None)
    now = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert all(records.got_worse(now[m.handle]) for m in (no, index, pending, held))
    assert queue(curated(capsys, "--global")) is None
    assert records.quarantined(now[held.handle]) and now[pending.handle].triage == "pending"
    assert "First text." not in shown(
        capsys, "rules"
    )  # none of them loads; their short form is the one printed


def test_a_lesson_left_out_by_the_cap_is_listed_as_such(project, gfolder, capsys):
    for i in range(FIT):  # FIT lines of the same size leave less than one short line of room
        write(f"Strong lesson number {i}.", short=pad(f"Strong rule {i}."), weight="strong")
    m = worse_lesson("Failing lesson.")
    out = queued(curated(capsys, "--global"))
    assert out[1] == f"  m:{m.handle}  left out by the cap  Failing lesson."
    assert "First text." not in shown(capsys, "rules")  # the short form of the lesson left out


def test_session_start_counts_what_got_worse(project, gfolder, capsys):
    a = worse_lesson("First failing lesson.", log=[(5, "failed")])
    assert "Got worse" not in shown(capsys, "session-index")
    records.update(
        a,
        TODAY,
        log=[
            records.case_entry(ago(5), "session q", "failed"),
            records.case_entry(ago(4), "session r", "failed"),
        ],
    )
    assert "Got worse: 1 loaded lesson needs a decision (mem curate)." in shown(
        capsys, "session-index"
    )
    worse_lesson("Second failing lesson.")
    out = shown(capsys, "session-index")
    assert "Got worse: 2 loaded lessons need a decision (mem curate)." in out
    assert len(out) <= mem._INDEX_LIMIT


def test_a_fault_in_the_count_leaves_the_rules_block(project, gfolder, capsys, monkeypatch):
    worse_lesson("Failing lesson.")
    with_sentence = shown(capsys, "session-index")
    assert "Got worse: 1 loaded lesson needs a decision" in with_sentence
    [m] = records.load_memories(Path(os.environ["MEM_MEMORIES"]), "global")
    log = m.log
    records.update(m, TODAY, log=None)  # the same store without any case
    plain = shown(capsys, "session-index")
    assert "Got worse" not in plain and "First text." in plain
    records.update(m, TODAY, log=log)
    monkeypatch.setattr(records, "got_worse", lambda m: 1 / 0)
    assert shown(capsys, "session-index") == plain


def test_no_sentence_when_loaded_rules_are_off(project, gfolder, capsys, monkeypatch):
    m = worse_lesson("Failing lesson.")
    assert "Got worse" in shown(capsys, "session-index")
    monkeypatch.setenv("MEM_LOADED_RULES", "off")
    assert "Got worse" not in shown(capsys, "session-index")
    assert queued(curated(capsys, "--global"))[1] == f"  m:{m.handle}  rules off  Failing lesson."


def test_a_superseded_lesson_is_not_listed(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.")
    assert queue(curated(capsys, "--global")) is not None
    records.update(m, TODAY, superseded_by="other")
    assert queue(curated(capsys, "--global")) is None


def test_choose_runs_once_at_session_start(project, gfolder, capsys, monkeypatch):
    worse_lesson("Failing lesson.")
    calls = []
    real = rules.choose
    monkeypatch.setattr(rules, "choose", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert "Got worse" in shown(capsys, "session-index")
    assert len(calls) == 1


def test_the_sentence_fits_the_limit_with_the_project_list(project, gfolder, capsys):
    worse_lesson("Failing lesson.")
    for i in range(12):
        write(
            f"Project lesson number {i} with some words to make the row longer than a few characters.",
            short=f"Project rule {i}.",
            scope="project",
        )
    out = shown(capsys, "session-index", "--list", "8")
    assert "  m:" in out and "Got worse: 1 loaded lesson" in out
    lines = out.splitlines()
    start = lines.index(rules.HEADER)
    end = next(
        i
        for i in range(start, len(lines))
        if lines[i].startswith("  m:") or lines[i].startswith("  …")
    )
    assert (
        len("\n".join(lines[:start] + lines[end:])) <= mem._INDEX_LIMIT
    )  # the limit leaves the rules block out
    assert sum(x.startswith("  m:") for x in lines) >= 1


def test_a_new_short_form_clears_the_listing(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.")
    assert queue(curated(capsys, "--global")) is not None
    shown(capsys, "memory", "edit", m.handle, "--global", "--short", "Better text.")
    assert queue(curated(capsys, "--global")) is None
    assert (
        len([
            x
            for x in shown(capsys, "show", f"m:{m.handle}").splitlines()
            if x.startswith("version ")
        ])
        == TWO_VERSIONS
    )


# --- keeping the wording (C71) ---


def test_accept_keeps_the_wording(project, gfolder, capsys):
    today = datetime.date.today()
    m = worse_lesson("Failing lesson.")
    assert queue(curated(capsys, "--global")) and "Got worse:" in shown(capsys, "session-index")
    out = shown(capsys, "triage", "accept", f"m:{m.handle}")
    assert out.strip() == f"m:{m.handle}\tkept as worded"
    kept = reload(m)
    assert kept.reviewed == today and kept.triage is None
    assert queue(curated(capsys, "--global")) is None and "Got worse" not in shown(
        capsys, "session-index"
    )
    later = [
        records.case_entry(today + datetime.timedelta(days=1), "session u", "failed"),
        records.case_entry(today + datetime.timedelta(days=2), "session v", "failed"),
    ]
    records.update(kept, TODAY, log=[*kept.log, *later])
    assert queue(curated(capsys, "--global")) and "Got worse:" in shown(capsys, "session-index")


def test_accept_of_a_pending_lesson_is_as_before(project, gfolder, capsys):
    m = worse_lesson("Waiting lesson.")
    records.update(m, TODAY, owner_confirmed=None, triage="pending")
    out = shown(capsys, "triage", "accept", f"m:{m.handle}")
    assert out.strip() == f"m:{m.handle}\taccepted"
    after = reload(m)
    assert after.triage is None and after.reviewed is None and "reviewed" not in m.path.read_text()


def test_accept_of_a_lesson_that_is_neither_keeps_its_error(project, gfolder, capsys):
    m = global_lesson("Fine lesson.", versions=[(10, "First text.")], log=[(5, "failed")])
    capsys.readouterr()
    assert mem.main(["triage", "accept", f"m:{m.handle}"]) == EXIT_USAGE
    assert "was already accepted or never awaited triage" in capsys.readouterr().err
    assert reload(m).reviewed is None


def test_accept_on_a_project_lesson_needs_the_flag(project, gfolder, capsys):
    today = datetime.date.today()
    write("Project failing lesson.", short="First text.", scope="project")
    [m] = records.load_memories(project / ".memory", "project")
    records.update(
        m,
        TODAY,
        versions=[records.version_entry(ago(10), "First text.")],
        log=[
            records.case_entry(ago(5), "session q", "failed"),
            records.case_entry(ago(4), "session r", "failed"),
        ],
    )
    capsys.readouterr()
    assert mem.main(["triage", "accept", f"m:{m.handle}"]) == EXIT_USAGE
    assert f"no memory named m:{m.handle}" in capsys.readouterr().err
    out = shown(capsys, "triage", "accept", f"m:{m.handle}", "--project-scope")
    assert out.strip() == f"m:{m.handle}\tkept as worded"
    assert records.load_memories(project / ".memory", "project")[0].reviewed == today


def test_restore_undoes_the_accept(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.")
    shown(capsys, "triage", "accept", f"m:{m.handle}")
    assert reload(m).reviewed is not None
    shown(capsys, "restore", f"m:{m.handle}")
    assert reload(m).reviewed is None


# --- end-review fixes ---


def test_a_merged_log_has_one_entry_per_session_and_outcome(tmp_path):
    keep = records.replace(
        transcript(tmp_path), log=["2026-11-22 session s1 failed", "2026-11-22 session s2 seen"]
    )
    drop = records.replace(
        keep,
        log=[
            "2026-11-20 session s1 failed",
            "2026-11-21 session s2 failed",
            "2026-11-23 session s3 seen",
        ],
    )
    assert records.merged_log(keep, drop) == [
        "2026-11-20 session s1 failed",
        "2026-11-21 session s2 failed",
        "2026-11-23 session s3 seen",
    ]
    # the other way round: the earlier day still wins, and a `seen` goes when the session has another entry
    assert records.merged_log(drop, keep) == records.merged_log(keep, drop)


def test_merge_drops_a_seen_entry_beside_another_of_its_session(project, capsys):
    keep = records.update(transcript(project), D1, log=["2026-11-22 session s1 failed"])
    drop = records.write_memory(
        project / ".memory",
        "project",
        kind="lesson",
        claim="Run the linter before the tests soon.",
        body="",
        today=D1,
        origin="transcript",
        sources=[records.sighting_entry("session s9", KEY)],
    )
    drop = records.update(
        drop, D1, log=["2026-11-20 session s1 failed", "2026-11-21 session s1 seen"]
    )
    assert mem.main(["merge", f"m:{keep.handle}", f"m:{drop.handle}", "--force"]) == 0
    capsys.readouterr()
    kept = next(
        x for x in records.load_memories(project / ".memory", "project") if x.handle == keep.handle
    )
    assert kept.log == ["2026-11-20 session s1 failed"]


def test_confirm_needs_source_for_outcome_and_day(project):
    m = transcript(project)
    before = m.path.read_bytes()
    for extra in (
        ["--outcome", "failed"],
        ["--seen-on", "2026-11-20"],
        ["--outcome", "worked", "--seen-on", "2026-11-20"],
    ):
        done = run_mem(project, "confirm", f"m:{m.handle}", *extra)
        assert (
            done.returncode == EXIT_USAGE
            and "--source" in done.stderr
            and len(done.stderr.strip().splitlines()) == 1
        ), done.stderr
        assert not done.stdout and m.path.read_bytes() == before


def test_remember_needs_source_for_outcome_and_day(project):
    for extra in (["--outcome", "failed"], ["--seen-on", "2026-11-20"]):
        done = run_mem(project, "remember", "--kind=lesson", "--claim=Brand new lesson.", *extra)
        assert done.returncode == EXIT_USAGE and "--source" in done.stderr, done.stderr
    assert records.load_memories(project / ".memory", "project") == []


def test_a_case_cannot_be_dated_in_the_future(project):
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    m = transcript(project)
    before = m.path.read_bytes()
    done = run_mem(
        project,
        "confirm",
        f"m:{m.handle}",
        "--source",
        "session s2",
        "--outcome",
        "failed",
        "--seen-on",
        tomorrow,
    )
    assert (
        done.returncode == EXIT_USAGE
        and "--seen-on" in done.stderr
        and m.path.read_bytes() == before
    )
    done = run_mem(
        project,
        "remember",
        "--kind=lesson",
        f"--claim={m.claim}",
        "--origin",
        "transcript",
        "--source",
        "session s2",
        "--outcome",
        "failed",
        "--seen-on",
        tomorrow,
    )
    assert (
        done.returncode == EXIT_USAGE
        and "--seen-on" in done.stderr
        and m.path.read_bytes() == before
    )
    today = datetime.date.today().isoformat()
    assert (
        run_mem(
            project, "confirm", f"m:{m.handle}", "--source", "session s2", "--seen-on", today
        ).returncode
        == 0
    )


def test_confirm_with_a_new_case_and_until_says_both(project):
    m = transcript(project)
    m, _ = records.add_sighting(m, f"session s2 project {KEY}", D1, outcome="seen")
    until = "2099-01-01"
    first = run_mem(
        project,
        "confirm",
        f"m:{m.handle}",
        "--source",
        "session s2",
        "--outcome",
        "failed",
        "--until",
        until,
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout == f"m:{m.handle}\tcase failed added; valid until {until}\n"
    got = reload(m)
    assert got.valid_until == datetime.date(2099, 1, 1) and got.log[-1].endswith(
        "session s2 failed"
    )
    # no new case: the message and the exit code stay
    again = run_mem(
        project,
        "confirm",
        f"m:{m.handle}",
        "--source",
        "session s2",
        "--outcome",
        "failed",
        "--until",
        until,
    )
    assert (
        again.returncode == EXIT_NOTHING
        and again.stdout == f"m:{m.handle}\tsession s2 is already a source; valid until {until}\n"
    )


def test_failed_after_it_loaded_skips_what_never_loads(project, gfolder, capsys):
    no, index, pending, held = (
        worse_lesson(c)
        for c in (
            "Lesson that never loads.",
            "Lesson that is index only.",
            "Lesson that awaits triage.",
            "Lesson in quarantine.",
        )
    )
    records.update(no, TODAY, load="no")
    records.update(index, TODAY, load="index")
    records.update(pending, TODAY, owner_confirmed=None, triage="pending")
    records.update(held, TODAY, sources=[held.sources[0]], owner_confirmed=None)
    assert "Failed after it loaded" not in shown(capsys, "rules")


def test_failed_after_it_loaded_names_one_left_out_by_the_cap(project, gfolder, capsys):
    for i in range(FIT):  # FIT lines of the same size leave less than one short line of room
        write(f"Strong lesson number {i}.", short=pad(f"Strong rule {i}."), weight="strong")
    m = worse_lesson("Failing lesson.")
    out = shown(capsys, "rules")
    assert (
        out.split("Failed after it loaded:\n")[1]
        == f"m:{m.handle}\tversion 1: worked 0, failed 2\n"
    )


def test_curate_says_rules_off_instead_of_loaded(project, gfolder, capsys, monkeypatch):
    m = worse_lesson("Failing lesson.")
    monkeypatch.setenv("MEM_LOADED_RULES", "off")
    assert queued(curated(capsys, "--global"))[1] == f"  m:{m.handle}  rules off  Failing lesson."


def test_the_project_scope_flag_refuses_a_global_lesson(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.")
    capsys.readouterr()
    assert mem.main(["triage", "accept", f"m:{m.handle}", "--project-scope"]) == EXIT_USAGE
    assert f"no memory named m:{m.handle}" in capsys.readouterr().err
    assert reload(m).reviewed is None
    # the same handle in both scopes: the flag picks the project one
    write("Failing lesson.", short="First text.", scope="project")
    [mine] = records.load_memories(project / ".memory", "project")
    records.update(
        mine, TODAY, versions=[records.version_entry(ago(10), "First text.")], log=list(m.log)
    )
    assert (
        shown(capsys, "triage", "accept", f"m:{mine.handle}", "--project-scope")
        .strip()
        .endswith("kept as worded")
    )


def test_a_second_accept_on_the_same_day_is_refused(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.")
    shown(capsys, "triage", "accept", f"m:{m.handle}")
    capsys.readouterr()
    assert mem.main(["triage", "accept", f"m:{m.handle}"]) == EXIT_USAGE
    assert "was already accepted or never awaited triage" in capsys.readouterr().err


def test_add_sighting_of_a_counted_session_with_the_same_outcome_writes_nothing(tmp_path):
    m, _ = records.add_sighting(transcript(tmp_path), "session s2", D1, outcome="failed")
    before = m.path.read_bytes()
    got, new = records.add_sighting(reload(m), "session s2", D2, outcome="failed")
    assert not new and got.path.read_bytes() == before


def test_a_counted_session_that_gains_a_project_keeps_its_log(tmp_path, monkeypatch):
    m = transcript(tmp_path, project=None)
    m, _ = records.add_case(m, "session s1", D1, "failed", D1)
    writes = []
    real = records.update
    monkeypatch.setattr(records, "update", lambda *a, **k: writes.append(1) or real(*a, **k))
    got, new = records.add_sighting(m, f"session s1 project {KEY}", D2, outcome="failed")
    assert new and len(writes) == 1
    assert got.sources == [f"session s1 project {KEY}"] and got.log == [
        "2026-11-20 session s1 failed"
    ]
