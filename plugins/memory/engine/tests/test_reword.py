import datetime

import pytest

import corroborate
import mem
import records
import rules
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
    worse("Kept by the owner.", reviewed=ago(1))
    global_lesson("Did not get worse.", versions=[(10, "First text.")], log=[(5, "worked"), (4, "failed")])
    # last: the helpers accept a lesson awaiting triage
    pending = worse("Pending.")
    pending.path.write_text(pending.path.read_text().replace("\n---\n", "\ntriage: pending\n---\n", 1))
    assert [x.triage for x in records.load_memories(os_gmem(), "global") if x.handle == pending.handle] == ["pending"]
    assert candidates() == ["Takes."]


def test_a_strong_lesson_is_a_candidate(project, gfolder):
    worse("Strong one.", weight="strong")
    assert candidates() == ["Strong one."]


def owner_version(m, days_ago, **changes):
    """The lesson with a version of the owner's at `days_ago`, after its first one, that failed twice since."""
    return records.update(reload(m), TODAY, versions=[records.version_entry(ago(10), "First text."),
                                                      records.version_entry(ago(days_ago), "By hand.")],
                          log=[records.case_entry(ago(days_ago - 1), "session a", "failed"),
                               records.case_entry(ago(days_ago - 2), "session b", "failed")], **changes)


def test_the_pass_does_not_reword_its_own_rewording(project, gfolder):
    worse("Own.", reworded=ago(10))   # `reworded` is the date of the present version
    assert candidates() == []


def test_a_wording_the_owner_wrote_after_a_rewording_gets_one_attempt(project, gfolder):
    m = worse("Reworded.", reworded=ago(10))
    m = owner_version(m, 5)   # the owner wrote a newer version, which got worse
    assert candidates() == ["Reworded."]
    state, _ = corroborate.reword_state_after(NONE_YET, [("g:a", m)], {"g:a": "written"}, TODAY)
    assert entry_of(state, m) == {"version": ago(5).isoformat(), "count": 0, "spent": True}
    # the pass wrote its version today and marked it
    m = records.update(reload(m), TODAY, reworded=TODAY, versions=[*reload(m).versions, records.version_entry(TODAY, "New.")])
    assert candidates(state) == [] and candidates() == []


def test_a_kept_wording_is_not_reworded_but_a_later_one_is(project, gfolder):
    m = worse("Kept.", reviewed=ago(10))   # kept on the day of its version
    assert candidates() == []
    records.update(reload(m), TODAY, reviewed=ago(7))
    assert candidates() == []
    m = owner_version(m, 5)   # a newer version after the keep, which got worse
    assert candidates() == ["Kept."]


def test_spent_is_per_version(project, gfolder):
    m = worse("Spent.")
    key = corroborate.reword_key(None, m.handle)
    here = {"lessons": {key: {"version": ago(10).isoformat(), "count": 0, "spent": True}}, "failures": {}}
    earlier = {"lessons": {key: {"version": ago(40).isoformat(), "count": 0, "spent": True}}, "failures": {}}
    assert candidates(here) == [] and candidates(earlier) == ["Spent."]


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
    worse("Reworded.", reworded=ago(10))
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


# --- Task 3: what the step decides from the two answers ---

def proposals(items, *shorts):
    return corroborate.validate_reword({"items": [{"id": i, "short": s} for (i, _), s in zip(items, shorts)]}, items)




def three():
    a, b, c = worse("Lesson a."), worse("Lesson b."), global_lesson("Maybe lesson c.", versions=[(10, "Maybe first.")],
                                                                      log=FAILS)
    return [("g:a", a), ("g:b", b), ("g:c", c)]


def test_survivors_and_refusals(project, gfolder):
    items = three()
    got = proposals(items, "A new wording.", "first text", "Always a new wording.")
    kept, refused = corroborate.reword_survivors(got, items)
    assert kept == [("g:a", items[0][1], "A new wording.")]
    assert refused == {"g:b": "same_text", "g:c": "refused_code"}


def test_outcome_words(project, gfolder):
    items = three() + [("g:d", worse("Lesson d.")), ("g:e", worse("Lesson e."))]
    got = proposals(items[:4], "A new wording.", "first text", "Always a new wording.", "Another wording.")
    out = corroborate.reword_outcome(items, got, {"g:a"})
    assert out == {"g:a": "written", "g:b": "same_text", "g:c": "refused_code", "g:d": "refused_check",
                   "g:e": "no_proposal"}   # no_proposal: the writer's answer has no item for the lesson


def entry_of(state, m, project=None):
    return state["lessons"][corroborate.reword_key(project, m.handle)]


def test_a_written_lesson_is_spent(project, gfolder):
    m = worse("Lesson a.")
    state, giveup = corroborate.reword_state_after(NONE_YET, [("g:a", m)], {"g:a": "written"}, TODAY)
    assert entry_of(state, m) == {"version": ago(10).isoformat(), "count": 0, "spent": True} and giveup == []
    assert candidates(state) == []  # the record carries no `reworded`, as after an undo
    assert candidates(NONE_YET) == ["Lesson a."]


def test_two_refusals_for_one_version_give_up(project, gfolder):
    m = worse("Lesson a.")
    items = [("g:a", m)]
    once, giveup = corroborate.reword_state_after(NONE_YET, items, {"g:a": "refused_check"}, TODAY)
    assert entry_of(once, m)["count"] == 1 and entry_of(once, m)["spent"] is False and giveup == []
    assert NONE_YET == {"lessons": {}, "failures": {}}
    twice, giveup = corroborate.reword_state_after(once, items, {"g:a": "same_text"}, TODAY)
    assert entry_of(twice, m)["count"] == 2 and giveup == ["g:a"] and entry_of(once, m)["count"] == 1


def test_a_refusal_for_a_new_version_starts_again(project, gfolder):
    m = worse("Lesson a.")
    key = corroborate.reword_key(None, m.handle)
    old = {"lessons": {key: {"version": ago(40).isoformat(), "count": 1, "spent": False}}, "failures": {"x": 1}}
    state, giveup = corroborate.reword_state_after(old, [("g:a", m)], {"g:a": "refused_code"}, TODAY)
    assert state["lessons"][key] == {"version": ago(10).isoformat(), "count": 1, "spent": False}
    assert state["failures"] == {"x": 1} and giveup == []


def test_a_project_lesson_has_the_key_of_its_project(project):
    import records as r
    m = r.write_memory(r.project_dir(project), "project", kind="lesson", claim="Project lesson.", body="", today=TODAY,
                       origin="transcript", sources=[r.sighting_entry("session s1", "k")])
    m = r.update(m, TODAY, short="First text.")
    state, _ = corroborate.reword_state_after(NONE_YET, [("p1:" + m.handle, m)], {"p1:" + m.handle: "written"}, TODAY)
    assert list(state["lessons"]) == [corroborate.reword_key(project, m.handle)]


def test_a_missing_proposal_counts_an_attempt(project, gfolder):
    m = worse("Lesson a.")
    items = [("g:a", m)]
    once, giveup = corroborate.reword_state_after(NONE_YET, items, {"g:a": "no_proposal"}, TODAY)
    assert entry_of(once, m) == {"version": ago(10).isoformat(), "count": 1, "spent": False} and giveup == []
    twice, giveup = corroborate.reword_state_after(once, items, {"g:a": "no_proposal"}, TODAY)
    assert entry_of(twice, m)["count"] == 2 and giveup == ["g:a"]


@pytest.mark.parametrize("word", ["changed", "failed_edit"])
def test_a_changed_lesson_and_a_failed_edit_count_nothing(project, gfolder, word):
    m = worse("Lesson a.")
    before = {"lessons": {"k": {"version": "2026-01-01", "count": 1, "spent": False}}, "failures": {}}
    state, giveup = corroborate.reword_state_after(before, [("g:a", m)], {"g:a": word}, TODAY)
    assert state == before and giveup == []


def test_a_lesson_cut_only_by_the_cap_is_a_candidate(project, gfolder):
    for n in range(rules.RULES_MAX):   # these rank first: the vouched-for strong lessons
        m = global_lesson(f"Filler lesson number {n}.", versions=[(10, "First text.")])
        records.update(m, TODAY, weight="strong")
    late = worse("Late lesson.")
    glob = [m for m in records.load_memories(os_gmem(), "global")]
    choice = rules.choose([], glob, TODAY)
    assert [m.claim for m, why in choice.left if why == rules.OVER] == ["Late lesson."] and len(choice.loaded) == rules.RULES_MAX
    assert candidates() == ["Late lesson."] and late.claim == "Late lesson."


def test_reworded_refuses_an_empty_short_form(project, gfolder):
    m = global_lesson("Failing lesson.", versions=[(10, "First text.")])
    before = m.path.read_bytes()
    assert edit(f"m:{m.handle}", "--short", "", "--reworded") == 2
    assert m.path.read_bytes() == before
