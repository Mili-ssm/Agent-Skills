import datetime

import mem
import records
from test_case_log import (CATEGORY, TODAY, ago, curated, global_lesson, queue, reload, shown,  # noqa: F401
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
