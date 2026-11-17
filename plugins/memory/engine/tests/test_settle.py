"""`mem settle`: pairs to judge, enforced verdicts, the log and whole-pair undo, and the `due` check."""
import datetime
import json

import pytest

import mem
import records
import settle
import store_git
from test_curation import days_ago, gfolder, put  # noqa: F401  (gfolder is a fixture)

TODAY = datetime.date.today()
OLD, NEW = "Use the build cache for every release build.", "Use the build cache for every release build today."


@pytest.fixture
def run(gfolder, capsys):
    def go(*argv):
        code = mem.main(["settle", *argv])
        out = capsys.readouterr()
        return code, out.out, out.err
    return go


def state(folder):
    return json.loads((folder / settle.STATE_NAME).read_text(encoding="utf-8"))


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
    assert code == 0 and {p["b"] for p in json.loads(out)} | {p["a"] for p in json.loads(out)} >= {"c-one"}


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
    assert run("pending")[1] == ""
    assert run("due", "--minutes", "0")[0] == 1


def test_inactive_records_are_ignored(gfolder, run):
    seeded(gfolder, run, status="forgotten")
    assert run("pending")[1] == ""


def test_merge_drops_the_older_even_when_named_first(gfolder, run, tmp_path):
    seeded(gfolder, run)
    code, out, _ = run("apply", "--verdicts", verdicts(tmp_path, {"a": "m:new-one", "b": "old-one", "decision": "merge"}))
    assert code == 0 and out.startswith("applied")
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    old, new = loaded["old-one"], loaded["new-one"]
    assert old.status == "superseded" and old.superseded_by == "new-one"
    assert new.status == "active" and new.observed == 2


def test_supersede_marks_the_older(gfolder, run, tmp_path):
    seeded(gfolder, run, claim="Use the build cache for every release build, version 2.")
    run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "supersede"}))
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert loaded["old-one"].superseded_by == "new-one" and loaded["new-one"].status == "active"


def test_same_day_tie_keeps_the_lower_handle_as_newer(gfolder, run, tmp_path):
    put(gfolder, "zz-old", "Unrelated placeholder claim here.")
    run("pending")
    put(gfolder, "a-first", OLD, created=days_ago(1))
    put(gfolder, "b-second", NEW, created=days_ago(1))
    [pair] = json.loads(run("pending", "--json")[1])
    assert pair["newer"] == "a-first"


def test_flagged_pair_cannot_be_merged_and_the_run_still_judges_it(gfolder, run, tmp_path):
    seeded(gfolder, run, claim="Use the build cache for every release build never.")
    code, out, _ = run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}))
    assert out.startswith("refused") and "never" in out
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert loaded["old-one"].status == "active" and loaded["new-one"].observed == 1
    # the refusal still ends the run: the new record is judged and the pair does not come back
    assert "new-one" in state(gfolder)["judged"]


def test_flagged_pair_can_be_superseded(gfolder, run, tmp_path):
    seeded(gfolder, run, claim="Use the build cache for every release build never.")
    code, out, _ = run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "supersede"}))
    assert out.startswith("applied")


def test_a_verdict_must_name_a_pending_pair_and_other_rows_still_run(gfolder, run, tmp_path):
    seeded(gfolder, run)
    put(gfolder, "other-one", "Completely different statement about tea.", created=days_ago(20))
    put(gfolder, "third", "Another unrelated sentence about oceans.", created=days_ago(20))
    path = verdicts(tmp_path, {"a": "other-one", "b": "third", "decision": "merge"},
                    {"a": "old-one", "b": "new-one", "decision": "merge"})
    code, out, _ = run("apply", "--verdicts", path)
    first, second = out.splitlines()
    assert first.startswith("refused") and "not a pair" in first and second.startswith("applied")
    loaded = {m.handle: m for m in records.load_memories(gfolder, "global")}
    assert loaded["other-one"].status == "active" and loaded["old-one"].status == "superseded"


def test_a_pair_already_judged_is_not_pending_for_a_verdict(gfolder, run, tmp_path):
    put(gfolder, "a-one", OLD)
    put(gfolder, "b-one", NEW)
    run("pending")
    _, out, _ = run("apply", "--verdicts", verdicts(tmp_path, {"a": "a-one", "b": "b-one", "decision": "merge"}))
    assert out.startswith("refused")


def test_nothing_changes_no_file_and_judges_the_pair(gfolder, run, tmp_path):
    seeded(gfolder, run)
    before = (gfolder / "old-one.md").read_bytes()
    run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "nothing"}))
    assert (gfolder / "old-one.md").read_bytes() == before
    assert "new-one" in state(gfolder)["judged"] and run("log")[1] == ""
    assert run("pending")[1] == ""


def test_judged_covers_unpaired_new_records_and_spares_those_written_after_pending(gfolder, run, tmp_path):
    seeded(gfolder, run)
    put(gfolder, "alone", "Something about volcanoes in the south.")
    run("pending")
    put(gfolder, "late", "A claim written while the run was under way.")
    run("apply", "--verdicts", verdicts(tmp_path))
    judged = state(gfolder)["judged"]
    assert "alone" in judged and "new-one" in judged and "late" not in judged
    assert run("due", "--minutes", "30")[0] == 1  # the run just ended: too soon, though "late" waits
    assert settle.due(gfolder, 30, state(gfolder)["last_apply"] + 31 * 60, TODAY) == 1


def test_secret_in_a_reason_refuses_the_row(gfolder, run, tmp_path):
    seeded(gfolder, run)
    _, out, _ = run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge",
                                                              "reason": "key AKIAABCDEFGHIJKLMNOP"}))
    assert out.startswith("refused")


def test_malformed_rows_are_refused_one_by_one(gfolder, run, tmp_path):
    seeded(gfolder, run)
    path = tmp_path / "v.json"
    path.write_text(json.dumps([{"a": "old-one"}, {"a": "old-one", "b": "new-one", "decision": "delete", "reason": "x"}]))
    out = run("apply", "--verdicts", str(path))[1].splitlines()
    assert [line.split("\t")[0] for line in out] == ["refused", "refused"]
    assert run("apply", "--verdicts", str(tmp_path / "missing.json"))[0] == 2


def snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.glob("*.md")}


@pytest.mark.parametrize("decision", ["merge", "supersede", "distinct"])
def test_undo_puts_both_records_back_in_one_command(gfolder, run, tmp_path, decision):
    put(gfolder, "old-one", OLD, created=days_ago(10), body="Old body.\n")
    run("pending")
    put(gfolder, "new-one", NEW, created=days_ago(1), body="New body.\n")
    before = snapshot(gfolder)
    run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": decision}))
    assert snapshot(gfolder) != before
    code, out, err = run("undo", "1")
    assert code == 0, err
    assert snapshot(gfolder) == before
    assert "undone" in run("log", "--all")[1]
    assert run("undo", "1")[0] == 2  # already undone


def test_undo_refuses_when_a_record_changed_again(gfolder, run, tmp_path):
    seeded(gfolder, run)
    run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}))
    assert mem.main(["confirm", "--global", "new-one"]) == 0
    before = snapshot(gfolder)
    code, _, err = run("undo", "1")
    assert code == 2 and "changed again" in err and snapshot(gfolder) == before
    assert run("undo", "9")[0] == 2


def test_log_lists_unacknowledged_settlings_until_ack(gfolder, run, tmp_path):
    seeded(gfolder, run)
    run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "supersede",
                                                   "reason": "newer wording"}))
    code, out, _ = run("log")
    number, date, decision, claims = out.strip().split("\t")
    assert (number, date, decision) == ("1", TODAY.isoformat(), "supersede") and OLD[:20] in claims
    assert run("ack")[1].strip() == "acknowledged 1"
    assert run("log")[1] == "" and run("log", "--all")[1] != ""
    entry = json.loads((gfolder / settle.LOG_NAME).read_text().splitlines()[0])
    assert entry["reason"] == "newer wording" and {entry["older"], entry["newer"]} == {"old-one", "new-one"}


def test_due_needs_new_records_and_an_elapsed_interval(gfolder):
    put(gfolder, "old-one", OLD)
    assert settle.due(gfolder, 30, 1000.0, TODAY) is None  # first use initializes; nothing is new
    put(gfolder, "new-one", NEW)
    assert settle.due(gfolder, 30, 1000.0, TODAY) == 1  # never applied
    st = state(gfolder)
    st["last_apply"] = 1000.0
    settle.save_state(gfolder, st)
    assert settle.due(gfolder, 30, 1000.0 + 30 * 60, TODAY) is None
    assert settle.due(gfolder, 30, 1000.0 + 30 * 60 + 1, TODAY) == 1


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
    run("apply", "--verdicts", verdicts(tmp_path, {"a": "old-one", "b": "new-one", "decision": "merge"}))
    run("undo", "1")
    assert (auto / "status.json").read_text(encoding="utf-8") == '{"finished": 123}'
    assert [p.name for p in data.rglob("*") if p.is_file()] == ["status.json"]


def test_settle_state_files_are_ignored_by_the_store_repository():
    assert {".settle-log", ".settle-state.json"} <= set(store_git.IGNORED_FILES)
