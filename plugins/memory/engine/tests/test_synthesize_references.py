"""`mem-synthesize` normal mode: references are the last step of a topic, added by the `--backfill` code path.

The writer and the lean loop are stubbed (they are not under test); the reference session is the fake `claude` of
test_backfill, so its command line and its answer are the real ones."""

import math

import pytest
import synth_pipeline as sp
from test_backfill import B, answer, fake, ms, sessions
from test_synth_pipeline_refs import ALPHA, BETA, store

# re-exported: pytest finds the fixture in this module by its name
__all__ = ["fake", "ms", "store"]

TOPIC = "newtopic"
LOOP_OK = {
    "arm_count": None,
    "why": "",
    "fixes": 0,
    "deleted": 0,
    "scope_violations": [],
    "reverted": [],
}
APPLIED = 2  # references in REFS that the fake session answers with a source
TWO_SESSIONS = 2  # the failed reference session, then the later backfill's


@pytest.fixture
def pipeline(store, monkeypatch):
    """Stub the writer and the lean loop; `state` says what they do."""
    state = {"loop": LOOP_OK, "write": True}

    def run_session(*_args: object, env: dict[str, str], **_kw: object) -> dict[str, object]:
        if state["write"]:
            made = sp.mem(
                store,
                env,
                "synthesis",
                "new",
                "--title",
                "New topic",
                "--topics",
                "algorithms",
                "--slug",
                TOPIC,
                "--summary-file",
                "-",
                stdin="How the new topic works here.\n",
            )
            assert made.returncode == 0, made.stderr
            for name, text in (("Alpha", ALPHA), ("Beta", BETA)):
                assert (
                    sp.mem(
                        store,
                        env,
                        "synthesis",
                        "add",
                        f"s:{TOPIC}",
                        "--section",
                        name,
                        "--body-file",
                        "-",
                        stdin=text + "\n",
                    ).returncode
                    == 0
                )
        return {
            "model_usage": {"claude-haiku-4-5": {"costUSD": 0.3}},
            "has_result": True,
            "error": "",
            "cost": 0.3,
            "wall": 1.0,
            "writes": 0,
            "write_errors": 0,
            "denied": False,
            "tool_errors": 0,
            "answer": "Slug: newtopic\n",
        }

    monkeypatch.setattr(sp, "run_session", run_session)
    monkeypatch.setattr(sp, "lean_loop", lambda *a, **kw: state["loop"])
    return state


def synthesize(ms, claude, store, tmp_path, **kw):
    lines, rows = [], []
    code = ms.run(
        str(claude),
        store,
        [TOPIC],
        3.0,
        False,
        out=lines.append,
        root=tmp_path / "run",
        rows_out=rows,
        **kw,
    )
    return code, lines, rows


def text(store):
    return (store / "syntheses" / f"{TOPIC}.md").read_text()


REFS = f"alpha | 2 | {B}\nbeta | 1 | {B}\nalpha | 3 | none\n"


@pytest.mark.usefixtures("pipeline")
def test_a_successful_topic_gets_references_and_the_table_shows_them(ms, fake, store, tmp_path):
    answer(tmp_path, REFS)
    code, lines, (row,) = synthesize(ms, fake, store, tmp_path)
    assert row["status"] == "ok" and code == 0
    assert (row["refs"], row["refs_refused"], row["refs_none"]) == (APPLIED, 0, 1)
    assert row["cost"] == pytest.approx(0.3 + 0.02)  # the reference session's cost is in the total
    assert len(sessions(tmp_path)) == 1 and B in text(store)
    head, body = lines[-2].splitlines()[:2]
    assert head.split()[6:9] == ["refs", "refused", "none"] and body.split()[6:9] == [
        "2",
        "0",
        "1",
    ], lines[-2]
    assert "total cost USD 0.320" in lines[-1]


@pytest.mark.usefixtures("pipeline")
def test_no_references_skips_the_step(ms, fake, store, tmp_path):
    answer(tmp_path, REFS)
    code, _, (row,) = synthesize(ms, fake, store, tmp_path, references=False)
    assert (
        code == 0
        and row["status"] == "ok"
        and row["refs"] == 0
        and row["cost"] == pytest.approx(0.3)
    )
    assert not sessions(tmp_path) and B not in text(store).split("## Beta")[1].split("Sources:")[0]


@pytest.fixture
def failing_session(request, monkeypatch):
    """Make the fake reference session fail as the test parameter says (`error` or `silent`)."""
    monkeypatch.setenv("FAKE_MODE", request.param)


@pytest.mark.parametrize("failing_session", ["error", "silent"], indirect=True)
@pytest.mark.usefixtures("pipeline", "failing_session")
def test_a_failed_reference_step_keeps_the_synthesis_and_a_later_backfill_sends_it(
    ms, fake, store, tmp_path, monkeypatch
):
    code, _, (row,) = synthesize(ms, fake, store, tmp_path)
    assert code == 0 and row["status"].startswith("ok, references not added: "), (
        row
    )  # the topic passes
    assert (row["refs"], row["refs_refused"], row["refs_none"]) == (0, 0, 0)
    after_loop = text(store)
    assert "](" not in after_loop.split("## Beta")[1].split("Sources:")[0]  # no reference was added
    monkeypatch.setenv("FAKE_MODE", "answer")
    answer(tmp_path, REFS)
    lines, rows = [], []
    assert (
        ms.run_backfill(
            str(fake),
            store,
            [f"s:{TOPIC}"],
            3.0,
            False,
            out=lines.append,
            rows_out=rows,
            root=tmp_path / "later",
        )
        == 0
    )
    assert (
        len(sessions(tmp_path)) == TWO_SESSIONS
        and rows[0]["applied"] == APPLIED
        and text(store) != after_loop
    )


@pytest.mark.usefixtures("pipeline")
def test_a_part_selection_that_raises_does_not_fail_the_topic(
    ms, fake, store, tmp_path, monkeypatch
):
    def boom(*a, **kw):
        raise ValueError("unreadable part")

    monkeypatch.setattr(ms.bf, "select", boom)
    code, _, (row,) = synthesize(ms, fake, store, tmp_path)
    assert code == 0 and row["status"] == "ok, references not added: ValueError: unreadable part", (
        row
    )
    assert not sessions(tmp_path)


@pytest.mark.usefixtures("pipeline")
def test_no_reference_session_starts_below_its_usual_cost(ms, fake, store, tmp_path):
    answer(tmp_path, REFS)
    lines, rows = [], []
    budget = (
        0.3 + ms.ESTIMATE_PER_BACKFILL / 2
    )  # the writer leaves less than one reference session costs
    code = ms.run(
        str(fake),
        store,
        [TOPIC],
        budget,
        False,
        out=lines.append,
        root=tmp_path / "run",
        rows_out=rows,
    )
    assert code == 0 and rows[0]["status"] == "ok, references not added: budget spent", rows
    assert not sessions(tmp_path)


@pytest.mark.usefixtures("pipeline")
def test_a_failing_mem_check_after_the_references_fails_the_topic(
    ms, fake, store, tmp_path, monkeypatch
):
    answer(tmp_path, REFS)
    real = ms.backfill_one

    def broken(*a, **kw):
        return {**real(*a, **kw), "mem_check": 1}

    monkeypatch.setattr(ms, "backfill_one", broken)
    code, _, (row,) = synthesize(ms, fake, store, tmp_path)
    assert code == 1 and row["status"].startswith("failed: mem check exit 1 after references"), row
    assert f"mem restore s:{TOPIC}" in row["status"] and row["refs"] == APPLIED


@pytest.mark.usefixtures("pipeline")
def test_a_failing_mem_check_with_no_reference_written_is_not_blamed_on_the_step(
    ms, fake, store, tmp_path, monkeypatch
):
    monkeypatch.setenv("FAKE_MODE", "error")
    real = ms.backfill_one
    monkeypatch.setattr(ms, "backfill_one", lambda *a, **kw: {**real(*a, **kw), "mem_check": 1})
    code, _, (row,) = synthesize(ms, fake, store, tmp_path)
    assert code == 0 and row["status"].startswith("ok, references not added: "), row


@pytest.mark.usefixtures("pipeline")
def test_a_successful_step_is_marked_done_like_backfill_does(ms, fake, store, tmp_path):
    answer(tmp_path, REFS)
    synthesize(ms, fake, store, tmp_path)
    lines, rows = [], []
    ms.run_backfill(
        str(fake),
        store,
        [f"s:{TOPIC}"],
        3.0,
        False,
        out=lines.append,
        rows_out=rows,
        root=tmp_path / "later",
    )
    assert rows == [] and "nothing to do" in lines[0] and len(sessions(tmp_path)) == 1


@pytest.fixture
def failing_pipeline(pipeline, request):
    """Make the writer (`writer`) or the lean loop (`loop`) fail, as the test parameter says."""
    if request.param == "writer":
        pipeline["write"] = False
    else:
        pipeline["loop"] = {**LOOP_OK, "why": "the checker failed"}


@pytest.mark.parametrize("failing_pipeline", ["writer", "loop"], indirect=True)
@pytest.mark.usefixtures("failing_pipeline")
def test_a_failed_topic_gets_no_reference_session(ms, fake, store, tmp_path):
    answer(tmp_path, REFS)
    code, _, (row,) = synthesize(ms, fake, store, tmp_path)
    assert code == 1 and row["status"].startswith("failed") and not sessions(tmp_path)


@pytest.mark.usefixtures("pipeline")
def test_the_reference_session_has_only_read(ms, fake, store, tmp_path):
    answer(tmp_path, REFS)
    synthesize(ms, fake, store, tmp_path)
    (argv,) = sessions(tmp_path)
    argv = argv[: argv.index("-p")] + argv[argv.index("-p") + 2 :]
    assert argv[argv.index("--tools") + 1] == "Read"
    assert not {"Bash", "Write", "Edit", "WebSearch", "WebFetch"} & {t.split("(")[0] for t in argv}
    assert argv[argv.index("--model") + 1] == "haiku" and "--max-budget-usd" in argv


@pytest.mark.usefixtures("pipeline")
def test_restore_undoes_the_references_and_the_next_one_the_step_before(ms, fake, store, tmp_path):
    answer(tmp_path, REFS)
    path = store / "syntheses" / f"{TOPIC}.md"
    synthesize(ms, fake, store, tmp_path)
    with_refs = path.read_bytes()
    assert sp.mem(store, {}, "restore", f"s:{TOPIC}").returncode == 0
    without = path.read_bytes()
    assert (
        without != with_refs and B not in without.decode().split("## Beta")[1].split("Sources:")[0]
    )
    assert (
        sp.mem(store, {}, "restore", f"s:{TOPIC}").returncode == 0
    )  # the writer's last step: the Beta part
    assert "## Beta" not in path.read_text()


def test_dry_run_estimates_the_reference_step_and_no_references_drops_it(ms, store, tmp_path):
    lines = []
    assert ms.run(None, store, ["a", "b"], 3.0, True, out=lines.append) == 0
    assert "1.10 USD" in lines[0] and "reference step" in lines[0]
    lines.clear()
    assert ms.run(None, store, ["a", "b"], 3.0, True, out=lines.append, references=False) == 0
    assert "1.00 USD" in lines[0]
    assert math.isclose(ms.ESTIMATE_PER_BACKFILL, 0.05)
