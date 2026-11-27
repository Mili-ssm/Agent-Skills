"""`bin/mem-corroborate`: reword_auto: lessons reworded."""

import datetime
import json
import os
import subprocess

import pytest
from core import jobs
from corroborate import reword as corroborate_reword
from corroborate import run as corroborate_run
from corroborate_world import (
    GCLAIM,
    MEM,
    NARROW,
    NEW_WORDING,
    OLD_WORDING,
    TODAY,
    ago,
    by_claim,
    calls,
    candidate_ids,
    globals_,
    reword,
    reword_answers,
    reword_state,
    run,
    snapshot,
    w,
    worse_one,
)
from memories import records

__all__ = ["w"]  # re-exported: pytest finds the fixture in this module by its name

WRITER_AND_CHECKER_CALLS = 2
ASKED_ALL = 3
ASKED_EVERY = 4
LIMIT = 2
ATTEMPTS_TO_GIVE_UP = 2
USAGE_ERROR = 2
KEPT_FINGERPRINT = 3
SECOND_CLAIM = "Keep a failing command's output in a file, as it may help when it is long."


def reword_runs(w):
    return (
        sorted(p for p in (w.cdir / "runs").iterdir() if p.name.endswith("-reword"))
        if (w.cdir / "runs").exists()
        else []
    )


def mem_curate(w):
    env = {**os.environ, "MEM_PROJECT": str(w.pa)}
    return subprocess.run(
        [str(MEM), "curate"],
        env=env,
        capture_output=True,
        text=True,
        cwd=w.pa,
        timeout=120,
        check=False,
    ).stdout


NOTHING = {
    "asked": 0,
    "written": 0,
    "refused_code": 0,
    "refused_check": 0,
    "same_text": 0,
    "no_proposal": 0,
    "gave_up": 0,
    "changed": 0,
    "failed_edits": 0,
    "cost": 0.0,
    "stopped": None,
}


def test_reword_applies_an_accepted_wording(w, monkeypatch):
    worse_one(w)
    found = candidate_ids(w)
    answer = json.dumps({
        "items": [
            {"id": i, "short": NEW_WORDING, "topic": "other-topic"}
            for ids in found.values()
            for i in ids
        ]
    })
    reword_answers(w, monkeypatch, writer=answer)
    topic_before = by_claim(w, NARROW).topic
    assert reword(w) == {**NOTHING, "asked": 1, "written": 1, "cost": 0.06}
    assert calls(w) == WRITER_AND_CHECKER_CALLS
    m = by_claim(w, NARROW)
    assert (m.short, m.reworded, m.short_by) == (NEW_WORDING, TODAY, "model")
    assert m.topic == topic_before and m.topic != "other-topic"
    assert [t for _, t in records.version_list(m)] == [OLD_WORDING, NEW_WORDING]
    assert not records.got_worse(m)


def test_reword_applies_an_answer_with_no_topic(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)  # the default answer has no `topic`
    assert reword(w)["written"] == 1 and by_claim(w, NARROW).short == NEW_WORDING


def test_reword_applies_to_a_global_lesson(w, monkeypatch):
    worse_one(w, claim=GCLAIM, scope="global")
    reword_answers(
        w,
        monkeypatch,
        shorts={GCLAIM: "Reading the whole failing test output before changing code may help."},
    )
    got = reword(w)
    assert got["written"] == 1, got
    (g,) = globals_(w)
    assert g.reworded == TODAY and (g.short or "").startswith("Reading the whole")


def test_two_refusals_give_up_and_mark_the_lesson(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, checker=False)
    first = reword(w)
    assert (first["refused_check"], first["gave_up"], first["written"]) == (1, 0, 0)
    assert by_claim(w, NARROW).reword_failed is None
    second = reword(w)
    assert (second["refused_check"], second["gave_up"]) == (1, 1)
    m = by_claim(w, NARROW)
    assert m.reword_failed == ago(10) and m.short == OLD_WORDING and m.reworded is None
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before


def test_a_refusal_by_code_and_a_repeat_are_counted_and_the_checker_is_not_paid(w, monkeypatch):
    worse_one(w)
    worse_one(w, claim=SECOND_CLAIM)
    reword_answers(
        w,
        monkeypatch,
        shorts={
            NARROW: "Run the narrowest covering test before the whole suite.",  # the hedge is gone
            SECOND_CLAIM: OLD_WORDING,
        },
    )  # an earlier wording
    result = reword(w)
    assert (result["refused_code"], result["same_text"], result["written"]) == (1, 1, 0)
    assert calls(w) == 1


def test_an_unusable_answer_changes_no_lesson_and_three_in_a_row_wait(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, writer="this is not json")
    for n in (1, 2, 3):
        result = reword(w)
        assert result["stopped"] and result["written"] == 0
        assert reword_state(w) == {
            "lessons": {},
            "failures": {"count": n, "fingerprint": reword_state(w)["failures"]["fingerprint"]},
        }
    assert by_claim(w, NARROW).short == OLD_WORDING
    before = calls(w)
    waiting = reword(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]
    worse_one(w, claim=SECOND_CLAIM)  # the candidates changed
    assert reword(w)["stopped"] != waiting["stopped"] and calls(w) == before + 1


def test_a_checker_that_gives_no_usable_answer_is_a_failed_session(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, checker="none")  # "none": the checker writes no usable answer
    result = reword(w)
    assert result["stopped"] and result["written"] == 0
    assert reword_state(w)["lessons"] == {} and reword_state(w)["failures"]["count"] == 1
    assert by_claim(w, NARROW).short == OLD_WORDING


def test_undo_still_does_not_bring_a_second_rewording(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    jobs.private_dir(w.cdir)
    seen_file = w.cdir / "seen.json"
    seen_file.write_text(json.dumps({"fingerprint": "kept", "refused": {}}))
    assert reword(w)["written"] == 1
    (run_dir,) = reword_runs(w)
    assert (run_dir / "fill").exists() and (run_dir / "journal.jsonl").exists()
    assert run(w, run_dir.name, cmd="undo", claude=False).returncode == 0
    m = by_claim(w, NARROW)
    assert (m.short, m.reworded) == (OLD_WORDING, None) and m.short_by == "model"
    assert reword_state(w)["lessons"][next(iter(reword_state(w)["lessons"]))] == {
        "version": ago(10).isoformat(),
        "count": 0,
        "spent": True,
    }  # spent for the version it was written from
    assert (
        json.loads(seen_file.read_text())["fingerprint"] == "kept"
    )  # not taken for a corroboration run
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before
    assert m.handle in mem_curate(w)


def test_a_reworded_version_that_got_worse_stays_with_the_owner(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    assert reword(w)["written"] == 1
    m = by_claim(w, NARROW)
    records.update(
        m,
        TODAY,
        log=[
            *m.log,
            records.case_entry(TODAY + datetime.timedelta(days=1), "session q", "failed"),
            records.case_entry(TODAY + datetime.timedelta(days=2), "session r", "failed"),
        ],
    )
    assert records.got_worse(by_claim(w, NARROW))
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before
    shown = mem_curate(w)
    assert m.handle in shown and "got worse too" in shown


def test_dry_run_writes_the_sheet_and_nothing_else(w, monkeypatch):
    worse_one(w)
    worse_one(w, claim=SECOND_CLAIM)
    worse_one(w, claim=GCLAIM, failed=())  # loaded, never failed: only `--every` takes it
    reword_answers(
        w,
        monkeypatch,
        shorts={SECOND_CLAIM: "Keeping a long failing command's output in a file may help."},
        checker=True,
    )
    before = snapshot(w)
    sheet = w.tmp / "sheet.md"
    done = run(w, "--every", "--dry-run", "--sheet", str(sheet), cmd="reword")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["asked"] == ASKED_ALL
    assert (
        snapshot(w) == before
        and not (w.cdir / "reword-attempts.json").exists()
        and not reword_runs(w)
    )
    rows = [x for x in sheet.read_text().splitlines() if x.startswith("| ") and "---" not in x][1:]
    assert len(rows) == ASKED_ALL and sum("the checker's reason" in x for x in rows) >= 1
    assert any(NEW_WORDING in x for x in rows) and any(NARROW in x for x in rows)


def test_without_a_sheet_nothing_is_written_beside_the_records(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    before = snapshot(w)
    result = reword(w, apply=False)
    assert result["asked"] == 1 and result["written"] == 0 and snapshot(w) == before
    assert not (w.cdir / "reword-attempts.json").exists()


def test_every_and_limit_pass_through(w, monkeypatch):
    for claim in (NARROW, SECOND_CLAIM, GCLAIM):
        worse_one(w, claim=claim)
    worse_one(
        w,
        claim="Read the build log from the top before guessing at a cause, as it may help.",
        failed=(),
    )
    reword_answers(w, monkeypatch, checker=False)
    assert reword(w, every=True, limit=LIMIT, apply=False)["asked"] == LIMIT
    assert reword(w, every=True, apply=False)["asked"] == ASKED_EVERY
    assert reword(w, apply=False)["asked"] == ASKED_ALL


def test_reword_respects_the_lock(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    lock = jobs.take_run_lock(w.cdir)
    assert lock is not None
    try:
        result = reword(w)
    finally:
        os.close(lock)
    assert "run is going" in result["stopped"] and result["written"] == 0 and calls(w) == 0
    assert (
        not (w.cdir / "reword-attempts.json").exists() and by_claim(w, NARROW).short == OLD_WORDING
    )


def test_a_missing_claude_binary_is_a_stop_not_an_exception(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    result = corroborate_reword.reword_auto("/nonexistent/claude", 0.25)
    assert result["stopped"] and result["written"] == 0
    assert by_claim(w, NARROW).short == OLD_WORDING


def test_reword_skips_a_lesson_edited_meanwhile(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    by_hand = (
        "A short form the owner wrote while the sessions ran, which the step must not overwrite."
    )
    edit_between(w, monkeypatch, short=by_hand)
    result = reword(w)
    assert result["changed"] == 1 and result["written"] == 0 and result["no_proposal"] == 0
    m = by_claim(w, NARROW)
    assert m.short == by_hand and m.reworded is None
    assert reword_state(w)["lessons"] == {} and not reword_runs(w)


def edit_between(w, mp, **changes):
    """The record is changed after the checker session and before the step's edit."""
    real = corroborate_run._ask

    def ask_then_edit(*args, **kw):
        got = real(*args, **kw)
        if args[2] == "check":
            records.update(by_claim(w, NARROW), TODAY, **changes)
        return got

    mp.setattr(corroborate_run, "_ask", ask_then_edit)


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewed": TODAY},
        {"reworded": ago(10)},
        {"status": "superseded", "superseded_by": "other"},
    ],
)
def test_reword_skips_a_lesson_the_owner_kept_meanwhile(w, monkeypatch, changes):
    worse_one(w)
    reword_answers(w, monkeypatch)
    edit_between(w, monkeypatch, **changes)
    result = reword(w)
    assert (
        result["changed"],
        result["written"],
        result["no_proposal"],
        result["failed_edits"],
    ) == (1, 0, 0, 0)
    assert reword_state(w)["lessons"] == {} and not reword_runs(w)
    assert next(m for m in project_lessons(w) if m.claim == NARROW).short == OLD_WORDING


def test_a_strong_lesson_that_got_worse_is_reworded(w, monkeypatch):
    worse_one(w)
    m = by_claim(w, NARROW)
    records.update(m, TODAY, weight="strong", owner_confirmed=TODAY)
    reword_answers(w, monkeypatch)
    assert reword(w)["written"] == 1 and by_claim(w, NARROW).short == NEW_WORDING


def test_a_lesson_that_became_strong_meanwhile_is_still_applied(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    edit_between(w, monkeypatch, weight="strong")
    result = reword(w)
    assert (result["written"], result["changed"]) == (1, 0) and by_claim(
        w, NARROW
    ).short == NEW_WORDING


def project_lessons(w):
    return records.load_memories(records.project_dir(w.pa), "project")


def fake_mem(w, mp, shell):
    """The step's `mem` calls go through a wrapper: `shell` runs first (REAL is the real command), then the real one."""
    script = w.tmp / "mem-fake"
    script.write_text(
        "#!/bin/sh\n"
        + shell.replace("REAL", str(corroborate_run.MEM))
        + f'\nexec {corroborate_run.MEM} "$@"\n'
    )
    script.chmod(0o755)
    mp.setattr(corroborate_run, "MEM", script)


EDIT_EXITS = (
    'if [ "$1" = memory ] && [ "$2" = edit ]; then case "$*" in *--short=*) exit %d;; esac; fi'
)


def test_a_missing_proposal_spends_an_attempt_and_two_give_up(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, writer=json.dumps({"items": []}))
    first = reword(w)
    assert (first["no_proposal"], first["gave_up"]) == (1, 0) and first["stopped"] is None
    assert next(iter(reword_state(w)["lessons"].values()))["count"] == 1
    second = reword(w)
    assert (second["no_proposal"], second["gave_up"]) == (1, 1)
    assert by_claim(w, NARROW).reword_failed == ago(10) and by_claim(w, NARROW).short == OLD_WORDING
    before = calls(w)
    assert reword(w) == NOTHING and calls(w) == before


def test_a_usage_error_of_the_edit_is_a_failed_edit(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    fake_mem(w, monkeypatch, EDIT_EXITS % 2)
    for n in (1, 2, 3):
        got = reword(w)
        assert (got["failed_edits"], got["written"], got["refused_code"], got["gave_up"]) == (
            1,
            0,
            0,
            0,
        )
        assert reword_state(w)["lessons"] == {} and reword_state(w)["failures"]["count"] == n
        assert (
            by_claim(w, NARROW).reword_failed is None and by_claim(w, NARROW).short == OLD_WORDING
        )
    before = calls(w)
    waiting = reword(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]


def test_a_forbidden_term_is_a_refusal(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    fake_mem(w, monkeypatch, EDIT_EXITS % 4)
    got = reword(w)
    assert (got["refused_code"], got["failed_edits"], got["written"]) == (1, 0, 0)
    (entry,) = reword_state(w)["lessons"].values()
    assert entry["count"] == 1 and reword_state(w)["failures"]["count"] == 0


def test_a_failed_give_up_is_retried_without_a_session(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch, checker=False)
    marker = w.tmp / "failed-once"
    fake_mem(
        w,
        monkeypatch,
        f'case "$*" in *--reword-failed*) if [ ! -f {marker} ]; then touch {marker}; exit 2; fi;; esac',
    )
    assert reword(w)["gave_up"] == 0
    second = reword(w)
    assert (second["refused_check"], second["gave_up"]) == (1, 0)
    assert (
        next(iter(reword_state(w)["lessons"].values()))["count"] == ATTEMPTS_TO_GIVE_UP
        and by_claim(w, NARROW).reword_failed is None
    )
    before = calls(w)
    third = reword(w)
    assert third == {**NOTHING, "gave_up": 1} and calls(w) == before
    assert by_claim(w, NARROW).reword_failed == ago(10)
    assert reword(w) == NOTHING and calls(w) == before


def test_every_needs_dry_run(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    done = run(w, "--every", cmd="reword")
    assert done.returncode == USAGE_ERROR and "--dry-run" in done.stderr and calls(w) == 0
    assert (
        by_claim(w, NARROW).short == OLD_WORDING and not (w.cdir / "reword-attempts.json").exists()
    )


@pytest.mark.parametrize(
    "content",
    [
        "[1, 2]",
        "not json",
        '"text"',
        '{"lessons": [], "failures": 5}',
        '{"lessons": {"k": 5, "j": []}, "failures": {"count": "x", "fingerprint": 3}}',
        '{"lessons": 7, "failures": []}',
    ],
)
def test_a_broken_state_file_reads_as_empty(w, content):
    jobs.private_dir(w.cdir)
    (w.cdir / "reword-attempts.json").write_text(content)
    got = corroborate_reword._reword_state(w.cdir)
    assert (
        got["lessons"] == {}
        and got["failures"]["count"] == 0
        and (
            got["failures"]["fingerprint"] is None
            or got["failures"]["fingerprint"] == KEPT_FINGERPRINT
        )
    )


def test_the_two_sessions_of_a_reword_share_one_spend(w, monkeypatch):
    worse_one(w)
    reword_answers(w, monkeypatch)
    spends = []
    real = corroborate_run._ask

    def watch(*args, **kw):
        spends.append(args[4].spend)
        return real(*args, **kw)

    monkeypatch.setattr(corroborate_run, "_ask", watch)
    reword(w)
    assert len(spends) == WRITER_AND_CHECKER_CALLS
    assert isinstance(spends[0], corroborate_run.Spend) and spends[0] is spends[1]
