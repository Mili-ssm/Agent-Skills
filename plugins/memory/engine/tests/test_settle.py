"""`mem settle`: pairs to judge, enforced verdicts, the log and whole-pair undo, and the `due` check."""

import datetime
import json

import mem
import pytest
from settle import verdicts as settle_verdicts
from store import records, store_git
from test_curation import days_ago, gfolder, put

# re-exported: pytest finds the fixture in this module by its name
__all__ = ["gfolder"]

TODAY = datetime.date.today()
OLD, NEW = (
    "Use the build cache for every release build.",
    "Use the build cache for every release build today.",
)
EXIT_REFUSED = 2
OBSERVED_TWICE = 2
DUE_PAIRS = 2
THREE_LINES = 3


@pytest.fixture
def run(gfolder, capsys):
    def go(*argv):
        code = mem.main(["settle", *argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return go


def state(folder):
    return json.loads((folder / settle_verdicts.STATE_NAME).read_text(encoding="utf-8"))


def verdicts(tmp_path, *rows):
    path = tmp_path / "verdicts.json"
    path.write_text(json.dumps([{"reason": "why", **r} for r in rows]), encoding="utf-8")
    return str(path)


def seeded(gfolder, run, **new):
    """An old pair that existed before the first use, judged by the initialization, and then a new look-alike."""
    put(gfolder, "old-one", OLD, created=days_ago(10))
    assert run("pending") == (0, "", "")  # first use: everything that exists is judged
    put(gfolder, "new-one", new.pop("claim", NEW), created=new.pop("created", days_ago(1)), **new)
    run("pending")  # what the model session is shown: the apply covers exactly these


def test_first_use_judges_everything_that_exists(gfolder, run):
    put(gfolder, "a-one", OLD)
    put(gfolder, "b-one", NEW)
    assert run("pending") == (0, "", "")
    assert sorted(state(gfolder)["judged"]) == ["a-one", "b-one"]
    put(gfolder, "c-one", "Use the build cache for every release build then.")
    code, out, _ = run("pending", "--json")
    assert code == 0 and {p["b"] for p in json.loads(out)} | {p["a"] for p in json.loads(out)} >= {
        "c-one"
    }


def test_pending_json_names_the_pair_the_newer_and_flagged_words(gfolder, run):
    seeded(gfolder, run, claim="Use the build cache for every release build never.")
    code, out, _ = run("pending", "--json")
    [pair] = json.loads(out)
    assert code == 0 and pair["pair"] == 1 and {pair["a"], pair["b"]} == {"old-one", "new-one"}
    assert pair["newer"] == "new-one" and "never" in pair["flagged_words"]
    assert {pair["claim_a"], pair["claim_b"]} >= {OLD}


def test_pending_prints_nothing_without_a_new_side(gfolder, run):
    put(gfolder, "a-one", OLD)
    put(gfolder, "b-one", NEW)
    assert run("pending") == (0, "", "")
    assert json.loads(run("pending", "--json")[1]) == []


def test_pipeline_records_are_never_the_new_side(gfolder, run):
    seeded(gfolder, run, extra="origin: pipeline\n")
    assert not run("pending")[1]
    assert run("due", "--minutes", "0")[0] == 1


def test_web_records_are_never_the_new_side(gfolder, run):
    seeded(gfolder, run, extra="origin: web\n")
    assert not run("pending")[1]
    assert run("due", "--minutes", "0")[0] == 1


def test_inactive_records_are_ignored(gfolder, run):
    seeded(gfolder, run, status="forgotten")
    assert not run("pending")[1]


def test_merge_drops_the_older_even_when_named_first(gfolder, run, tmp_path):
    seeded(gfolder, run)
    code, out, _ = run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "m:new-one", "b": "old-one", "decision": "merge"}),
    )
    assert code == 0 and out.startswith("applied")
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    old, new = loaded["old-one"], loaded["new-one"]
    assert old.status == "superseded" and old.superseded_by == "new-one"
    assert new.status == "active" and new.observed == OBSERVED_TWICE


def test_supersede_marks_the_older(gfolder, run, tmp_path):
    seeded(gfolder, run, claim="Use the build cache for every release build, version 2.")
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "supersede"}),
    )
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert loaded["old-one"].superseded_by == "new-one" and loaded["new-one"].status == "active"


def test_the_unjudged_record_is_the_newer_even_when_created_earlier(gfolder, run):
    put(gfolder, "zz-old", "Unrelated placeholder claim here.")
    run("pending")
    put(gfolder, "a-first", OLD, created=days_ago(1))
    put(gfolder, "b-second", NEW, created=days_ago(1))
    st = state(gfolder)
    st["judged"].append("a-first")
    settle_verdicts.save_state(gfolder, st)
    [pair] = json.loads(run("pending", "--json")[1])
    assert pair["newer"] == "b-second"


def test_both_unjudged_use_the_later_date_and_a_same_day_tie_is_undecidable(gfolder, run, tmp_path):
    put(gfolder, "zz-old", "Unrelated placeholder claim here.")
    run("pending")
    put(gfolder, "a-first", OLD, created=days_ago(2))
    put(gfolder, "b-second", NEW, created=days_ago(1))
    [pair] = json.loads(run("pending", "--json")[1])
    assert pair["newer"] == "b-second"
    put(gfolder, "a-first", OLD, created=days_ago(1))
    [pair] = json.loads(run("pending", "--json")[1])
    assert pair["newer"] is None
    rows = [
        {"a": "a-first", "b": "b-second", "decision": d} for d in ("merge", "supersede", "distinct")
    ]
    out = run("apply", "--verdicts", verdicts(tmp_path, *rows))[1].splitlines()
    assert len(out) == THREE_LINES and all(
        line.startswith("refused") and "cannot tell which is newer" in line for line in out[:2]
    )
    assert out[2].startswith("applied")


def test_flagged_pair_cannot_be_merged(gfolder, run, tmp_path):
    seeded(gfolder, run, claim="Use the build cache for every release build never.")
    _, out, _ = run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}),
    )
    assert out.startswith("refused") and "never" in out
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert loaded["old-one"].status == "active" and loaded["new-one"].observed == 1


def test_a_refused_row_keeps_its_pair_pending_for_one_more_run_then_logs_left(
    gfolder, run, tmp_path
):
    seeded(gfolder, run, claim="Use the build cache for every release build never.")
    merge = verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"})
    assert run("apply", "--verdicts", merge)[1].startswith("refused")
    assert "new-one" not in state(gfolder)["judged"] and not run("log", "--all")[1]
    assert len(json.loads(run("pending", "--json")[1])) == 1  # offered again
    assert run("apply", "--verdicts", merge)[1].startswith("refused")
    assert "new-one" in state(gfolder)["judged"]
    [entry] = [
        json.loads(line) for line in (gfolder / settle_verdicts.LOG_NAME).read_text().splitlines()
    ]
    assert entry["decision"] == "left" and entry["files"] == {}
    assert "left" in run("log")[1]
    assert not run("pending")[1]


def test_a_missing_verdict_counts_like_a_refused_one(gfolder, run, tmp_path):
    seeded(gfolder, run)
    run("apply", "--verdicts", verdicts(tmp_path))
    assert "new-one" not in state(gfolder)["judged"]
    run("pending")
    run("apply", "--verdicts", verdicts(tmp_path))
    assert "new-one" in state(gfolder)["judged"] and "left" in run("log")[1]


def test_an_applied_decision_ends_the_pair(gfolder, run, tmp_path):
    seeded(gfolder, run)
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "distinct"}),
    )
    assert "new-one" in state(gfolder)["judged"] and run("log")[1].count("distinct") == 1


def test_flagged_pair_can_be_superseded(gfolder, run, tmp_path):
    seeded(gfolder, run, claim="Use the build cache for every release build never.")
    _, out, _ = run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "supersede"}),
    )
    assert out.startswith("applied")


def test_a_verdict_must_name_a_pending_pair_and_other_rows_still_run(gfolder, run, tmp_path):
    seeded(gfolder, run)
    put(gfolder, "other-one", "Completely different statement about tea.", created=days_ago(20))
    put(gfolder, "third", "Another unrelated sentence about oceans.", created=days_ago(20))
    path = verdicts(
        tmp_path,
        {"a": "other-one", "b": "third", "decision": "merge"},
        {"a": "old-one", "b": "new-one", "decision": "merge"},
    )
    _, out, _ = run("apply", "--verdicts", path)
    first, second = out.splitlines()
    assert first.startswith("refused") and "not a pair" in first and second.startswith("applied")
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert loaded["other-one"].status == "active" and loaded["old-one"].status == "superseded"


def test_a_pair_already_judged_is_not_pending_for_a_verdict(gfolder, run, tmp_path):
    put(gfolder, "a-one", OLD)
    put(gfolder, "b-one", NEW)
    run("pending")
    _, out, _ = run(
        "apply", "--verdicts", verdicts(tmp_path, {"a": "a-one", "b": "b-one", "decision": "merge"})
    )
    assert out.startswith("refused")


def test_nothing_changes_no_file_and_judges_the_pair(gfolder, run, tmp_path):
    seeded(gfolder, run)
    before = (gfolder / "old-one.md").read_bytes()
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "nothing"}),
    )
    assert (gfolder / "old-one.md").read_bytes() == before
    assert "new-one" in state(gfolder)["judged"] and not run("log")[1]
    assert not run("pending")[1]


def test_judged_covers_unpaired_new_records_and_spares_those_written_after_pending(
    gfolder, run, tmp_path
):
    put(gfolder, "old-one", OLD, created=days_ago(10))
    run("pending")
    put(gfolder, "new-one", NEW, created=days_ago(1))
    put(gfolder, "alone", "Something about volcanoes in the south.")
    run("pending")
    put(gfolder, "late", "A claim written while the run was under way.")
    run("apply", "--verdicts", verdicts(tmp_path))
    judged = state(gfolder)["judged"]
    assert "alone" in judged and "late" not in judged
    assert "new-one" not in judged  # its pair got no verdict: offered once more
    assert (
        run("due", "--minutes", "30")[0] == 1
    )  # the run just ended: too soon, though "late" waits
    assert (
        settle_verdicts.due(gfolder, 30, state(gfolder)["last_apply"] + 31 * 60, TODAY) == DUE_PAIRS
    )  # "late" and the retained "new-one"


def test_secret_in_a_reason_refuses_the_row(gfolder, run, tmp_path):
    seeded(gfolder, run)
    _, out, _ = run(
        "apply",
        "--verdicts",
        verdicts(
            tmp_path,
            {
                "a": "old-one",
                "b": "new-one",
                "decision": "merge",
                "reason": "key AKIAABCDEFGHIJKLMNOP",
            },
        ),
    )
    assert out.startswith("refused")


def test_malformed_rows_are_refused_one_by_one(gfolder, run, tmp_path):
    seeded(gfolder, run)
    path = tmp_path / "v.json"
    path.write_text(
        json.dumps([
            {"a": "old-one"},
            {"a": "old-one", "b": "new-one", "decision": "delete", "reason": "x"},
        ])
    )
    out = run("apply", "--verdicts", str(path))[1].splitlines()
    assert [line.split("\t")[0] for line in out] == ["refused", "refused"]
    assert run("apply", "--verdicts", str(tmp_path / "missing.json"))[0] == EXIT_REFUSED


def snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.glob("*.md")}


@pytest.mark.parametrize("decision", ["merge", "supersede", "distinct"])
def test_undo_puts_both_records_back_in_one_command(gfolder, run, tmp_path, decision):
    put(gfolder, "old-one", OLD, created=days_ago(10), body="Old body.\n")
    run("pending")
    put(gfolder, "new-one", NEW, created=days_ago(1), body="New body.\n")
    run("pending")
    before = snapshot(gfolder)
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": decision}),
    )
    assert snapshot(gfolder) != before
    code, _, err = run("undo", "1")
    assert code == 0, err
    assert snapshot(gfolder) == before
    assert "undone" in run("log", "--all")[1]
    assert run("undo", "1")[0] == EXIT_REFUSED  # already undone


def test_undo_refuses_when_a_record_changed_again(gfolder, run, tmp_path):
    seeded(gfolder, run)
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}),
    )
    assert mem.main(["confirm", "--global", "new-one"]) == 0
    before = snapshot(gfolder)
    code, _, err = run("undo", "1")
    assert code == EXIT_REFUSED and "changed again" in err and snapshot(gfolder) == before
    assert run("undo", "9")[0] == EXIT_REFUSED


def test_log_lists_unacknowledged_settlings_until_ack(gfolder, run, tmp_path):
    seeded(gfolder, run)
    run(
        "apply",
        "--verdicts",
        verdicts(
            tmp_path,
            {"a": "old-one", "b": "new-one", "decision": "supersede", "reason": "newer wording"},
        ),
    )
    _, out, _ = run("log")
    number, date, decision, claims = out.strip().split("\t")
    assert (number, date, decision) == ("1", TODAY.isoformat(), "supersede") and OLD[:20] in claims
    assert run("ack")[1].strip() == "acknowledged 1"
    assert not run("log")[1] and run("log", "--all")[1]
    entry = json.loads((gfolder / settle_verdicts.LOG_NAME).read_text().splitlines()[0])
    assert entry["reason"] == "newer wording" and {entry["older"], entry["newer"]} == {
        "old-one",
        "new-one",
    }


def test_due_needs_new_records_and_an_elapsed_interval(gfolder):
    put(gfolder, "old-one", OLD)
    assert (
        settle_verdicts.due(gfolder, 30, 1000.0, TODAY) is None
    )  # first use initializes; nothing is new
    put(gfolder, "new-one", NEW)
    assert settle_verdicts.due(gfolder, 30, 1000.0, TODAY) == 1  # never applied
    st = state(gfolder)
    st["last_apply"] = 1000.0
    settle_verdicts.save_state(gfolder, st)
    assert settle_verdicts.due(gfolder, 30, 1000.0 + 30 * 60, TODAY) is None
    assert settle_verdicts.due(gfolder, 30, 1000.0 + 30 * 60 + 1, TODAY) == 1


def test_due_command_exit_codes(gfolder, run):
    put(gfolder, "old-one", OLD)
    assert run("due", "--minutes", "30")[0] == 1
    put(gfolder, "new-one", NEW)
    assert run("due", "--minutes", "30") == (0, "1\n", "")


def test_settle_never_touches_the_automatic_run_state(gfolder, run, tmp_path, monkeypatch):
    data = tmp_path / "mem-data"
    auto = data / "auto" / "x"
    auto.mkdir(parents=True)
    (auto / "status.json").write_text('{"finished": 123}', encoding="utf-8")
    seeded(gfolder, run)
    run("due", "--minutes", "0")
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}),
    )
    run("undo", "1")
    assert (auto / "status.json").read_text(encoding="utf-8") == '{"finished": 123}'
    assert [p.name for p in data.rglob("*") if p.is_file()] == ["status.json"]


def test_settle_state_files_are_ignored_by_the_store_repository():
    assert {".settle-log", ".settle-state.json"} <= set(store_git.IGNORED_FILES)


@pytest.mark.parametrize("text", ["not json {", "[1, 2]", '{"acked": 0}', '{"judged": "x"}'])
def test_an_unreadable_state_file_is_an_error_and_never_replaced(gfolder, run, text):
    put(gfolder, "old-one", OLD)
    path = gfolder / settle_verdicts.STATE_NAME
    path.write_text(text, encoding="utf-8")
    for argv in (("pending",), ("due", "--minutes", "0"), ("log",)):
        code, _, err = run(*argv)
        assert code == EXIT_REFUSED and settle_verdicts.STATE_NAME in err
    assert path.read_text(encoding="utf-8") == text


def test_an_empty_queue_judges_what_it_examined_and_stops_due(gfolder, run):
    put(gfolder, "old-one", OLD)
    run("pending")
    put(gfolder, "lonely", "Something about volcanoes in the south.")
    assert run("due", "--minutes", "0")[0] == 0
    assert run("pending") == (0, "", "")
    assert "lonely" in state(gfolder)["judged"] and state(gfolder)["last_apply"] is not None
    assert run("due", "--minutes", "0")[0] == 1


def test_a_second_process_is_refused_while_the_lock_is_held(gfolder, run, tmp_path):
    seeded(gfolder, run)
    before = (gfolder / settle_verdicts.STATE_NAME).read_bytes()
    with settle_verdicts.locked(gfolder):
        for argv in (("pending",), ("apply", "--verdicts", verdicts(tmp_path)), ("undo", "1")):
            code, out, err = run(*argv)
            assert code == EXIT_REFUSED and not out and "another mem settle command" in err
    assert (gfolder / settle_verdicts.STATE_NAME).read_bytes() == before
    assert run("pending")[0] == 0  # released


def test_a_failure_after_a_file_changed_is_logged_as_partial_and_can_be_undone(
    gfolder, run, tmp_path, monkeypatch
):
    put(gfolder, "old-one", OLD, created=days_ago(10), body="Old body.\n")
    run("pending")
    put(gfolder, "new-one", NEW, created=days_ago(1), body="New body.\n")
    run("pending")
    before = snapshot(gfolder)
    real = mem._merge_pair

    def broken(keep, drop, today):
        real(keep, drop, today)
        raise OSError("disk went away")

    monkeypatch.setattr(mem, "_merge_pair", broken)
    out = run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}),
    )[1]
    assert out.startswith("failed") and "disk went away" in out
    assert snapshot(gfolder) != before
    entry = json.loads((gfolder / settle_verdicts.LOG_NAME).read_text().splitlines()[0])
    assert entry["partial"] is True and entry["decision"] == "merge" and entry["files"]
    assert "merge" in run("log")[1]
    assert run("undo", "1")[0] == 0 and snapshot(gfolder) == before


def test_settle_adds_its_ignore_lines_to_a_store_that_is_a_repository_already(
    tmp_path, monkeypatch, run
):
    store = tmp_path / "store"
    folder = store / "memories"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    put(folder, "old-one", OLD)
    (store / ".git").mkdir()
    (store / ".gitignore").write_text("node_modules/", encoding="utf-8")
    run("pending")
    lines = (store / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "node_modules/" and {".settle-log", ".settle-state.json"} <= set(lines)
    run("pending")
    assert (store / ".gitignore").read_text(encoding="utf-8").splitlines() == lines


def test_settle_creates_no_gitignore_outside_a_repository(gfolder, run):
    put(gfolder, "old-one", OLD)
    run("pending")
    assert not (gfolder.parent / ".gitignore").exists() and not (gfolder / ".gitignore").exists()


def log_entries(folder):
    return [
        json.loads(line) for line in (folder / settle_verdicts.LOG_NAME).read_text().splitlines()
    ]


def two_newcomers(gfolder, run):
    put(gfolder, "old-one", OLD, created=days_ago(10))
    run("pending")
    put(gfolder, "new-one", NEW, created=days_ago(2))
    put(gfolder, "new-two", "Use the build cache for every release build now.", created=days_ago(1))
    run("pending")


def test_a_handle_with_another_pair_still_retained_is_not_judged(gfolder, run, tmp_path):
    two_newcomers(gfolder, run)
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "distinct"}),
    )
    assert "new-two" not in state(gfolder)["judged"]
    run("pending")
    run("apply", "--verdicts", verdicts(tmp_path))
    assert "new-two" in state(gfolder)["judged"]
    assert any(
        e["decision"] == "left" and "new-two" in {e["older"], e["newer"]}
        for e in log_entries(gfolder)
    )


def test_a_pair_whose_record_is_no_longer_active_needs_no_left_entry(gfolder, run, tmp_path):
    two_newcomers(gfolder, run)
    run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "supersede"}),
    )
    assert not any(
        e["decision"] == "left" and "old-one" in {e["older"], e["newer"]}
        for e in log_entries(gfolder)
    )


def test_offers_count_pending_showings_not_applies(gfolder, run, tmp_path):
    seeded(gfolder, run)
    empty = verdicts(tmp_path)
    run("apply", "--verdicts", empty)
    run("apply", "--verdicts", empty)
    assert not run("log", "--all")[1] and "new-one" not in state(gfolder)["judged"]
    run("pending")
    run("apply", "--verdicts", empty)
    assert "left" in run("log")[1]


def test_apply_without_a_listing_changes_nothing_and_fails(gfolder, run, tmp_path):
    put(gfolder, "old-one", OLD, created=days_ago(10))
    run("pending")
    put(gfolder, "new-one", NEW, created=days_ago(1))
    before, files = (gfolder / settle_verdicts.STATE_NAME).read_bytes(), snapshot(gfolder)
    code, out, _ = run(
        "apply",
        "--verdicts",
        verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "distinct"}),
    )
    assert code != 0 and out.startswith("refused") and "mem settle pending" in out
    assert (gfolder / settle_verdicts.STATE_NAME).read_bytes() == before and snapshot(
        gfolder
    ) == files
    assert not (gfolder / settle_verdicts.LOG_NAME).exists()


def test_a_programming_error_still_logs_the_changed_record_then_propagates(
    gfolder, run, tmp_path, monkeypatch
):
    put(gfolder, "old-one", OLD, created=days_ago(10), body="Old body.\n")
    run("pending")
    put(gfolder, "new-one", NEW, created=days_ago(1), body="New body.\n")
    run("pending")
    before = snapshot(gfolder)
    real = mem._merge_pair

    def broken(keep, drop, today):
        real(keep, drop, today)
        raise KeyError("bug")

    monkeypatch.setattr(mem, "_merge_pair", broken)
    with pytest.raises(KeyError):
        run(
            "apply",
            "--verdicts",
            verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}),
        )
    [entry] = log_entries(gfolder)
    assert entry["partial"] is True and entry["files"]
    with settle_verdicts.locked(gfolder):  # the lock was released
        pass
    assert run("undo", "1")[0] == 0 and snapshot(gfolder) == before


def test_undo_of_a_left_entry_says_there_is_nothing_to_undo(gfolder, run, tmp_path):
    seeded(gfolder, run)
    run("apply", "--verdicts", verdicts(tmp_path))
    run("pending")
    run("apply", "--verdicts", verdicts(tmp_path))
    code, _, err = run("undo", "1")
    assert code == 1 and "settling 1 changed no record: nothing to undo" in err
