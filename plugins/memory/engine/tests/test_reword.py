import datetime

import corroborate
import mem
import records
from test_case_log import (CATEGORY, FAILS, TODAY, ago, curated, global_lesson, queue, reload, shown,  # noqa: F401
                           worse_lesson)
from test_case_log import project  # noqa: F401  (fixtures)
from test_rules_session import gfolder  # noqa: F401


def edit(*argv):
    return mem.main(["memory", "edit", *argv])


def test_reworded_marks_the_lesson(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    assert edit(f"m:{m.handle}", "--short", "Second text.", "--reworded") == 0
    got = reload(m)
    assert got.reworded == TODAY and got.short_by == "model" and got.short == "Second text."
    assert len(got.versions) == 2


def test_a_short_form_written_by_hand_keeps_the_mark(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    assert edit(f"m:{m.handle}", "--short", "Second text.", "--reworded") == 0
    got = reload(m)
    records.update(got, TODAY, reworded=ago(1))  # the rewording was made yesterday
    got = reload(m)
    records.update(got, TODAY, versions=[records.version_entry(ago(10), "First text."),
                                         records.version_entry(ago(1), "Second text.")])
    assert edit(f"m:{m.handle}", "--short", "Third text.", "--user-read") == 0
    got = reload(m)
    assert got.reworded == ago(1) and got.short_by is None
    assert records.reword_note(got) == f"an automatic rewording was made on {ago(1)}; this wording is the owner's"


def test_reworded_needs_a_short_form_and_no_user_read(project, gfolder, capsys):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    before = m.path.read_bytes()
    assert edit(f"m:{m.handle}", "--topic", "lint", "--reworded") == 2
    assert edit(f"m:{m.handle}", "--short", "Second text.", "--reworded", "--user-read") == 2
    assert m.path.read_bytes() == before


def test_reword_failed_names_the_version_it_gave_up_on(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    assert edit(f"m:{m.handle}", "--reword-failed") == 0
    got = reload(m)
    assert got.reword_failed == ago(10) and got.short == m.short
    assert records.reword_note(got) == "an automatic rewording could not be written"
    assert edit(f"m:{m.handle}", "--short", "Second text.", "--user-read") == 0
    got = reload(m)
    assert records.reword_note(got) == "" and got.reword_failed == ago(10)


def test_reword_failed_stands_alone(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    before = m.path.read_bytes()
    assert edit(f"m:{m.handle}", "--reword-failed", "--topic", "lint") == 2
    assert edit(f"m:{m.handle}", "--reword-failed", "--short", "Second text.") == 2
    assert m.path.read_bytes() == before


def test_wrong_values_read_as_absent(project, gfolder):
    m = global_lesson("Failing lesson.")
    text = m.path.read_text().replace("\n---\n", "\nreworded: soon\nreword_failed: 7\n---\n", 1)
    m.path.write_text(text)
    got = reload(m)
    assert got.reworded is None and got.reword_failed is None


def test_curate_row_says_what_was_tried(project, gfolder, capsys):
    m = worse_lesson("Failing lesson.")
    plain = queue(curated(capsys, "--global"))
    assert plain[1] == f"  m:{m.handle}  loaded  Failing lesson."
    records.update(m, TODAY, reword_failed=ago(10))
    row = queue(curated(capsys, "--global"))[1]
    assert row == f"  m:{m.handle}  loaded; an automatic rewording could not be written  Failing lesson."
    records.update(reload(m), TODAY, reword_failed=None, reworded=ago(10))
    row = queue(curated(capsys, "--global"))[1]
    assert row == f"  m:{m.handle}  loaded; the automatic rewording of {ago(10)} got worse too  Failing lesson."
    records.update(reload(m), TODAY, reworded=ago(11))
    row = queue(curated(capsys, "--global"))[1]
    assert row == (f"  m:{m.handle}  loaded; an automatic rewording was made on {ago(11)}; this wording is the "
                   "owner's  Failing lesson.")
    records.update(reload(m), TODAY, reworded=None)
    assert queue(curated(capsys, "--global")) == plain


def test_restore_undoes_reworded(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    assert edit(f"m:{m.handle}", "--short", "Second text.", "--reworded") == 0
    assert mem.main(["restore", f"m:{m.handle}"]) == 0
    got = reload(m)
    assert got.short == "First text." and got.reworded is None


def test_reword_failed_is_journaled(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    assert edit(f"m:{m.handle}", "--reword-failed") == 0
    assert mem.main(["restore", f"m:{m.handle}"]) == 0
    assert reload(m).reword_failed is None


# --- Task 2: the candidates and what the writer reads ---

NONE_YET = {"lessons": {}, "failures": {}}


def worse(claim, fails=FAILS, **changes):
    m = worse_lesson(claim, log=fails)
    return records.update(m, TODAY, **changes) if changes else m


def os_gmem():
    import os
    from pathlib import Path
    return Path(os.environ["MEM_MEMORIES"])


def candidates(state=NONE_YET, **kw):
    return [m.claim for _, m in corroborate.reword_candidates([], os_gmem(), TODAY, state, **kw)]


def test_candidates_are_loading_lessons_that_got_worse(project, gfolder):
    worse("Takes.")
    worse("Index only.", load="index")
    worse("Never loads.", load="no")
    worse("Strong one.", weight="strong")
    worse("Kept by the owner.", reviewed=ago(1))
    global_lesson("Did not get worse.", versions=[(10, "First text.")], log=[(5, "worked"), (4, "failed")])
    # last: the helpers accept a lesson awaiting triage
    pending = worse("Pending.")
    pending.path.write_text(pending.path.read_text().replace("\n---\n", "\ntriage: pending\n---\n", 1))
    assert [x.triage for x in records.load_memories(os_gmem(), "global") if x.handle == pending.handle] == ["pending"]
    assert candidates() == ["Takes."]


def test_a_reworded_lesson_is_never_taken_again(project, gfolder):
    m = worse("Reworded.", reworded=ago(30))
    assert candidates() == []
    records.update(reload(m), TODAY, versions=[records.version_entry(ago(10), "First text."),
                                               records.version_entry(ago(3), "By hand.")],
                   log=[records.case_entry(ago(2), "session a", "failed"), records.case_entry(ago(1), "session b", "failed")])
    assert records.got_worse(reload(m)) and candidates() == []


def test_a_given_up_version_and_a_spent_lesson_are_skipped(project, gfolder):
    gave_up = worse("Gave up.", reword_failed=ago(10))
    spent = worse("Spent.")
    twice = worse("Twice.")
    earlier = worse("Earlier count.")
    key = lambda m: corroborate.reword_key(None, m.handle)
    state = {"lessons": {key(spent): {"version": ago(10).isoformat(), "count": 0, "spent": True},
                         key(twice): {"version": ago(10).isoformat(), "count": 2, "spent": False},
                         key(earlier): {"version": ago(40).isoformat(), "count": 2, "spent": False}},
             "failures": {}}
    assert candidates(state) == ["Earlier count."]
    assert gave_up.reword_failed == ago(10)


def test_cap_and_order(project, gfolder):
    for n in range(7):
        worse(f"Lesson {n}.", fails=[(5, "failed"), (4, "failed")] + [(3, "failed")] * n)
    got = candidates()
    assert got == ["Lesson 6.", "Lesson 5.", "Lesson 4.", "Lesson 3.", "Lesson 2."]
    assert len(got) == corroborate.REWORD_CAP


def test_every_takes_lessons_that_did_not_get_worse(project, gfolder):
    global_lesson("Did not get worse.", versions=[(10, "First text.")], log=[(5, "worked")])
    worse("Strong one.", weight="strong")
    worse("Reworded.", reworded=ago(30))
    assert candidates() == []
    assert candidates(every=True) == ["Did not get worse."]


def test_the_block_shows_versions_tallies_and_failure_signals(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text."), (6, "Second text.")],
                      log=[(8, "worked"), (4, "failed")])
    m = records.update(m, TODAY, body='Seen again (rework): "x"\nSeen again (effective_practice).\n'
                                      'Seen again (owner_correction).\nSeen again (rework).\n')
    block = corroborate.reword_blocks([("g:" + m.handle, m)])
    assert block == (f"id: g:{m.handle}\nclaim: Failing lesson.\n"
                     "version 1 (worked 1, failed 0): First text.\n"
                     "version 2 (worked 0, failed 1): Second text. (present)\n"
                     "failed after it loaded: rework, owner_correction\n")
    assert "x" not in block.split("failed after it loaded:")[1].replace("rework", "").replace("owner_correction", "")
    bare = global_lesson("No signals.", versions=[(10, "First text.")])
    assert "failed after it loaded: not recorded" in corroborate.reword_blocks([("g:b", bare)])


def test_same_text():
    assert corroborate.same_text("Check the data first.", "check  the data first")
    assert not corroborate.same_text("Check the data first.", "Check the real data first.")


def test_reword_problem(project, gfolder):
    m = worse("Failing lesson.")
    assert corroborate.reword_problem("x" * 121, m)
    assert corroborate.reword_problem("", m)
    assert corroborate.reword_problem("first text", m) == "same as an earlier wording"
    assert corroborate.reword_problem("A new wording.", m) is None


def test_validate_reword(project, gfolder):
    a, b = worse("Lesson a."), worse("Lesson b.")
    items = [("g:a", a), ("g:b", b)]
    got = corroborate.validate_reword({"items": [{"id": "g:a", "short": "A new wording."},
                                                 {"id": "g:a", "short": "Second."}, {"id": "zz", "short": "y"}]}, items)
    assert got == {"g:a": {"short": "A new wording.", "problem": None}}
    bad = corroborate.validate_reword({"items": [{"id": "g:b", "short": 5}]}, items)
    assert bad["g:b"]["short"] == "" and bad["g:b"]["problem"]
    import pytest
    with pytest.raises(ValueError):
        corroborate.validate_reword({"items": "no"}, items)
