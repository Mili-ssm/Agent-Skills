"""`bin/mem-corroborate`: digest_auto: the digest written for the session start."""

import json
import os
from pathlib import Path
from typing import TypedDict, Unpack

import digest
import jobs
import mem
import records
from corroborate import digest as corroborate_digest
from corroborate_world import TODAY, calls, globals_, run, snapshot, w

__all__ = ["w"]  # re-exported: pytest finds the fixture in this module by its name

CALLS_OF_A_FULL_RUN = 2  # the writer and the checker
LESSON_COUNT = 3
KEPT_LINES = 2
SHEET_ROWS = 4  # the heading's row and one per lesson
LINES_AFTER_A_REFUSAL = 2
USAGE_EXIT = 2

DG_TOPIC = "briefing"
DG_HEADING = "when briefing a subagent"
DG_LESSONS = [
    (
        "Give a subagent the check that tells it the task is done before it starts, as it may stop early otherwise.",
        "When briefing a subagent, giving it the acceptance check first may help.",
    ),
    (
        "Name the files a subagent may touch and the ones it must leave alone, as it may otherwise widen its scope.",
        "When briefing a subagent, naming the files it may touch may keep its scope narrow.",
    ),
    (
        "Ask a subagent for a report of a fixed length, as long reports may hide the one finding that matters.",
        "When reading a subagent's report, a fixed length may keep the finding visible.",
    ),
]
DG_LINES = [
    "giving it the acceptance check first may let it tell when it is done",
    "naming the files it may touch may keep it from widening its scope",
    "asking for a report of a fixed length may keep the one finding visible",
]
DG_NEW_SHORT = "When briefing a subagent, stating the check it must pass first may help."


def digest_world(w):
    """Three ready global lessons of one topic, as the fill and the rewording leave them."""
    made = []
    for claim, short in DG_LESSONS:
        m = records.write_memory(
            w.gmem,
            "global",
            kind="lesson",
            claim=claim,
            body="b\n",
            today=TODAY,
            origin="transcript",
            reach="general",
            weight="light",
            topic=DG_TOPIC,
            sources=[
                f"session s5 project {records.project_key(w.pa)}",
                f"session s6 project {records.project_key(w.pb)}",
            ],
        )
        made.append(records.update(m, TODAY, short=short, short_by="model", triage=None))
    return made


def digest_lessons(w):
    return sorted((m for m in globals_(w) if m.topic == DG_TOPIC), key=lambda m: m.handle)


class AnswerOptions(TypedDict, total=False):
    heading: str | None
    lines: dict[str, str] | None
    fits: bool
    unfaithful: tuple[str, ...]
    writer: str
    checker: str


def digest_answers(w, mp, **options: Unpack[AnswerOptions]):
    """The fake's two answers of the step. lines: claim -> line (default DG_LINES in the order of DG_LESSONS); unfaithful: claims
    the checker does not find faithful; writer/checker "ok", "none" (no file) or the file's text."""
    heading = options.get("heading", DG_HEADING)
    lines = options.get("lines")
    fits = options.get("fits", True)
    unfaithful = options.get("unfaithful", ())
    writer = options.get("writer", "ok")
    checker = options.get("checker", "ok")
    mp.delenv("FAKE_DIGEST", raising=False)
    mp.delenv("FAKE_DIGEST_CHECK", raising=False)
    by = {m.claim: m for m in digest_lessons(w)}
    texts = lines or {claim: line for (claim, _s), line in zip(DG_LESSONS, DG_LINES, strict=True)}
    if writer == "ok":
        topic = {
            "topic": DG_TOPIC,
            "lines": [{"id": f"g:{by[c].handle}", "line": t} for c, t in texts.items()],
        }
        if heading is not None:
            topic["heading"] = heading
        writer = json.dumps({"topics": [topic]})
    if writer != "none":
        (w.tmp / "digest-answer.json").write_text(writer)
        mp.setenv("FAKE_DIGEST", str(w.tmp / "digest-answer.json"))
    if checker == "ok":
        checker = json.dumps({
            "verdicts": [
                {
                    "id": f"g:{m.handle}",
                    "reason": "the checker's reason",
                    "fits": fits,
                    "faithful": m.claim not in unfaithful,
                }
                for m in by.values()
            ]
        })
    if checker != "none":
        (w.tmp / "digest-check-answer.json").write_text(checker)
        mp.setenv("FAKE_DIGEST_CHECK", str(w.tmp / "digest-check-answer.json"))


def do_digest(w, **kw):
    return corroborate_digest.digest_auto(str(w.fake), 0.25, **kw)


def engine_digest():
    return digest.read(mem.data_dir(os.environ))  # the folder the session start resolves


def digest_state(w):
    return json.loads((w.cdir / "digest-attempts.json").read_text())


def asked(w, which):
    return Path(os.environ["FAKE_INPUTS"] + f"-digest-{which}").read_text(encoding="utf-8")


DG_NOTHING = {
    "topics": 0,
    "headings_written": 0,
    "lines_written": 0,
    "refused_code": 0,
    "refused_check": 0,
    "missing": 0,
    "unjudged": 0,
    "cost": 0.0,
    "stopped": None,
}


def test_digest_writes_a_topic_the_engine_reads_as_fresh(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    before = snapshot(w)
    assert do_digest(w) == {
        **DG_NOTHING,
        "topics": 1,
        "headings_written": 1,
        "lines_written": 3,
        "cost": 0.06,
    }
    assert calls(w) == CALLS_OF_A_FULL_RUN
    lessons = digest_lessons(w)
    stored = engine_digest()
    assert stored["topics"][DG_TOPIC]["heading"] == DG_HEADING
    assert digest.heading(stored, DG_TOPIC, lessons) == DG_HEADING
    for m in lessons:
        want = DG_LINES[[c for c, _s in DG_LESSONS].index(m.claim)]
        assert digest.line(stored, DG_TOPIC, m, lessons) == want
    assert snapshot(w) == before  # no record is written
    assert (w.data / digest.FILE).exists() and digest_state(w)["failures"]["count"] == 0
    assert not (w.cdir / "runs").exists()  # no journal: nothing to undo


def test_a_refused_line_falls_back_and_is_tried_twice(w, monkeypatch):
    digest_world(w)
    refused = DG_LESSONS[0][0]
    digest_answers(w, monkeypatch, unfaithful=(refused,))
    first = do_digest(w)
    assert (first["headings_written"], first["lines_written"], first["refused_check"]) == (1, 2, 1)
    second = do_digest(w)
    assert (second["headings_written"], second["lines_written"], second["refused_check"]) == (
        0,
        0,
        1,
    )
    before = calls(w)
    assert do_digest(w) == DG_NOTHING and calls(w) == before  # nothing left to ask
    lessons, stored = digest_lessons(w), engine_digest()
    for m in lessons:
        got = digest.line(stored, DG_TOPIC, m, lessons)
        assert got is None if m.claim == refused else got in DG_LINES


def test_a_reworded_lesson_gets_a_new_line_and_the_rest_keep_theirs(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    assert do_digest(w)["lines_written"] == LESSON_COUNT
    first = engine_digest()
    target = next(m for m in digest_lessons(w) if m.claim == DG_LESSONS[1][0])
    records.update(target, TODAY, short=DG_NEW_SHORT)
    new_line = "stating the check it must pass first may let it tell when it is done"
    digest_answers(w, monkeypatch, heading=None, lines={DG_LESSONS[1][0]: new_line})
    assert do_digest(w) == {**DG_NOTHING, "topics": 1, "lines_written": 1, "cost": 0.06}
    text = asked(w, "write")
    assert (
        text.count("do: write") == 1
        and text.count("do: keep") == KEPT_LINES
        and "heading (keep)" in text
    )
    lessons, stored = digest_lessons(w), engine_digest()
    for m in lessons:
        if m.handle == target.handle:
            assert digest.line(stored, DG_TOPIC, m, lessons) == new_line
        else:
            assert (
                stored["topics"][DG_TOPIC]["lines"][m.handle]
                == first["topics"][DG_TOPIC]["lines"][m.handle]
            )
            assert digest.line(stored, DG_TOPIC, m, lessons) is not None


def test_an_unusable_answer_changes_nothing_and_three_in_a_row_wait(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, writer="this is not json")
    for n in (1, 2, 3):
        result = do_digest(w)
        assert result["stopped"] and result["headings_written"] == 0
        state = digest_state(w)
        assert state == {
            "tries": {},
            "failures": {"count": n, "fingerprint": state["failures"]["fingerprint"]},
        }
    assert not (w.data / digest.FILE).exists()
    before = calls(w)
    waiting = do_digest(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]
    records.update(
        digest_lessons(w)[0],
        TODAY,
        claim="Give a subagent the check that tells it the task is done first, as it may help.",
    )
    assert do_digest(w)["stopped"] != waiting["stopped"] and calls(w) == before + 1


def test_a_digest_checker_that_gives_no_usable_answer_is_a_failed_session(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, checker="none")
    result = do_digest(w)
    assert result["stopped"] and result["headings_written"] == 0 and calls(w) == CALLS_OF_A_FULL_RUN
    assert not (w.data / digest.FILE).exists() and digest_state(w)["tries"] == {}
    assert digest_state(w)["failures"]["count"] == 1


def test_digest_dry_run_writes_the_sheet_and_nothing_else(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, unfaithful=(DG_LESSONS[2][0],))
    before = snapshot(w)
    sheet = w.tmp / "sheet.md"
    done = run(w, "--dry-run", "--sheet", str(sheet), cmd="digest")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["topics"] == 1 and calls(w) == CALLS_OF_A_FULL_RUN
    assert (
        snapshot(w) == before
        and not (w.data / digest.FILE).exists()
        and not (w.cdir / "digest-attempts.json").exists()
    )
    rows = [x for x in sheet.read_text().splitlines() if x.startswith("| ") and "---" not in x][1:]
    assert (
        len(rows) == SHEET_ROWS and sum("the checker's reason" in x for x in rows) == LESSON_COUNT
    )  # the heading has a row of its own
    assert (
        any(DG_HEADING in x and DG_LINES[0] in x for x in rows)
        and sum("refused_check" in x for x in rows) == 1
    )
    repo = w.tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    refused = run(w, "--dry-run", "--sheet", str(repo / "sheet.md"), cmd="digest", mode="never")
    assert (
        refused.returncode == USAGE_EXIT
        and "repository" in refused.stderr
        and calls(w) == CALLS_OF_A_FULL_RUN
        and not (repo / "sheet.md").exists()
    )


def test_digest_respects_the_lock(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    lock = jobs.take_run_lock(w.cdir)
    assert lock is not None
    try:
        result = do_digest(w)
    finally:
        os.close(lock)
    assert "run is going" in result["stopped"] and result["headings_written"] == 0 and calls(w) == 0
    assert not (w.data / digest.FILE).exists() and not (w.cdir / "digest-attempts.json").exists()


def test_an_unwritable_sheet_does_not_fail_an_applied_digest_run(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    result = do_digest(w, sheet=w.tmp / "no-such-folder" / "sheet.md")
    assert (
        result["headings_written"] == 1
        and "sheet" in result["stopped"]
        and result["stopped"] != "the step failed"
    )
    assert engine_digest()["topics"][DG_TOPIC]["heading"] == DG_HEADING


def sheet_rows(path):
    return [
        [c.strip() for c in x.strip("|").split(" | ")]
        for x in path.read_text().splitlines()
        if x.startswith("| ") and "---" not in x
    ][1:]


def test_the_sheet_has_a_row_for_a_heading_the_code_refused(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch, heading="h" * 81)
    sheet = w.tmp / "sheet.md"
    result = do_digest(w, sheet=sheet)
    assert (
        result["refused_code"] == 1 and result["headings_written"] == 0 and calls(w) == 1
    )  # nothing for the checker
    rows = sheet_rows(sheet)
    assert len(rows) == SHEET_ROWS
    head, *lines = rows
    assert (
        head[0] == DG_TOPIC
        and head[1] == "h" * 81
        and not head[2]
        and not head[5]
        and head[6] == "refused_code"
    )
    assert "80" in head[7]
    assert all(r[2].startswith("g:") and r[6] == "unjudged" for r in lines)


def test_the_sheet_has_a_row_for_a_line_the_code_refused(w, monkeypatch):
    digest_world(w)
    bad = {
        DG_LESSONS[0][0]: "x" * 121,
        DG_LESSONS[1][0]: DG_LINES[1],
        DG_LESSONS[2][0]: DG_LINES[2],
    }
    digest_answers(w, monkeypatch, lines=bad)
    sheet = w.tmp / "sheet.md"
    result = do_digest(w, sheet=sheet)
    assert result["refused_code"] == 1 and result["lines_written"] == LINES_AFTER_A_REFUSAL
    rows = sheet_rows(sheet)
    assert sorted(r[6] for r in rows) == ["refused_code", "written", "written", "written"]
    refused = next(r for r in rows if r[6] == "refused_code")
    assert refused[1] == DG_HEADING and refused[5] == "x" * 121 and "120" in refused[7]


def test_a_lesson_the_checker_left_out_is_not_judged_and_spends_no_try(w, monkeypatch):
    digest_world(w)
    by = {m.claim: m for m in digest_lessons(w)}
    only = by[DG_LESSONS[0][0]]
    verdict = json.dumps({
        "verdicts": [{"id": f"g:{only.handle}", "reason": "ok", "fits": True, "faithful": True}]
    })
    digest_answers(w, monkeypatch, checker=verdict)
    result = do_digest(w)
    assert result == {
        **DG_NOTHING,
        "topics": 1,
        "headings_written": 1,
        "lines_written": 1,
        "unjudged": 2,
        "cost": 0.06,
    }
    assert digest_state(w)["tries"] == {}
    assert list(engine_digest()["topics"][DG_TOPIC]["lines"]) == [only.handle]
    # the two left out are asked again, as nothing was spent
    digest_answers(w, monkeypatch, heading=None)
    assert do_digest(w)["lines_written"] == LINES_AFTER_A_REFUSAL


def test_a_run_with_nothing_to_write_still_prunes_and_starts_no_session(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    assert do_digest(w)["lines_written"] == LESSON_COUNT
    data = mem.data_dir(os.environ)
    assert data is not None
    stored = engine_digest()
    stored["topics"]["vanished"] = {
        "heading": "when gone",
        "of": "x",
        "lines": {"h1": {"text": "t", "of": "o", "under": "x"}},
    }
    digest.write(data, stored)
    state = digest_state(w)
    state["tries"]["h:vanished@x"] = 1
    state["tries"]["l:old@x@y"] = 2
    (w.cdir / "digest-attempts.json").write_text(json.dumps(state))
    before = calls(w)
    assert do_digest(w) == DG_NOTHING and calls(w) == before
    assert list(engine_digest()["topics"]) == [DG_TOPIC] and digest_state(w)["tries"] == {}
    # a dry run prunes nothing
    stored["topics"]["vanished"] = {"heading": "when gone", "of": "x", "lines": {}}
    digest.write(data, stored)
    do_digest(w, apply=False)
    assert "vanished" in engine_digest()["topics"]


def test_a_run_that_writes_also_prunes(w, monkeypatch):
    digest_world(w)
    data = mem.data_dir(os.environ)
    assert data is not None
    digest.write(data, {"topics": {"vanished": {"heading": "when gone", "of": "x", "lines": {}}}})
    digest_answers(w, monkeypatch)
    assert do_digest(w)["headings_written"] == 1
    assert list(engine_digest()["topics"]) == [DG_TOPIC]


def test_a_digest_that_cannot_be_written_is_a_counted_failed_run(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    (w.data / digest.FILE).mkdir()  # the path is taken by a directory: the write fails
    for n in (1, 2, 3):
        before = calls(w)
        result = do_digest(w)
        assert (
            calls(w) == before + 2
            and result["stopped"]
            and "written" in result["stopped"]
            and result["headings_written"] == 0
        )
        assert digest_state(w)["failures"]["count"] == n and digest_state(w)["tries"] == {}
    before = calls(w)
    waiting = do_digest(w)
    assert calls(w) == before and "waiting" in waiting["stopped"]


def test_a_state_that_cannot_be_written_still_gives_a_result(w, monkeypatch):
    digest_world(w)
    digest_answers(w, monkeypatch)
    w.cdir.mkdir(parents=True, exist_ok=True)
    w.cdir.mkdir(parents=True, exist_ok=True)
    (w.cdir / "digest-attempts.json").mkdir()
    result = do_digest(w)
    assert result["stopped"] and result["stopped"] != "the step failed"
