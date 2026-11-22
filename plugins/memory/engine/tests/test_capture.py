import json
from pathlib import Path
import capture

def write(tmp_path, entries):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries) + "\n")
    return p

def user(text, kind="human", **kw): return {"type": "user", "message": {"content": text}, **({"origin": {"kind": kind}} if kind else {}), **kw}
def queued(text, mode="prompt", **kw): return {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": mode, "prompt": text, **kw}}
def agent(*blocks, **kw): return {"type": "assistant", "message": {"content": list(blocks)}, **kw}
def text(t): return {"type": "text", "text": t}
def use(i, name, **inp): return {"type": "tool_use", "id": i, "name": name, "input": inp}
def result(i, content, err=False): return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": content, "is_error": err}]}}

def test_extract_keeps_owner_agent_and_tool_events_with_line_numbers(tmp_path):
    p = write(tmp_path, [user("use tabs,\nnot spaces"), agent(text("ok"), use("a", "Bash", command="make test")),
                         result("a", "2 failed", err=True), agent(use("b", "Bash", command="make test")), result("b", "all passed")])
    out, last = capture.extract(p)
    assert out.splitlines() == ["[1] OWNER: use tabs, not spaces", "[2] AGENT: ok", "[2] TOOL Bash: make test",
                                "[3] TOOL ERROR Bash: 2 failed", "[4] TOOL Bash: make test", "[5] TOOL OK Bash"]
    assert last == 5

def test_extract_leaves_out_meta_summary_and_plain_results(tmp_path):
    p = write(tmp_path, [user("meta", isMeta=True), user("summary", isCompactSummary=True), user("<system-tag>x", kind=None),
                         queued("a reminder", isMeta=True), agent(use("a", "Read", file_path="x.py")), result("a", "content of x")])
    assert capture.extract(p)[0].splitlines() == ["[5] TOOL Read: x.py"]

def test_extract_tells_the_owner_from_reports(tmp_path):
    p = write(tmp_path, [user("typed by the owner"), user("an old prompt", kind=None), queued("typed while the agent worked"),
                         queued("<task-notification>done", mode="task-notification"), user("<task-notification>a review\nfound a bug", kind="task-notification"),
                         user("report from a peer", kind="peer"), agent(use("q", "AskUserQuestion", description="which one?")), result("q", "the second\noption")])
    assert capture.extract(p)[0].splitlines() == [
        "[1] OWNER: typed by the owner", "[2] OWNER: an old prompt", "[3] OWNER: typed while the agent worked",
        "[5] REPORT: <task-notification>a review found a bug", "[6] REPORT: report from a peer",
        "[7] TOOL AskUserQuestion: which one?", "[8] OWNER ANSWER: the second option"]

def test_parts_and_counts():
    t = "\n".join(f"[{i}] OWNER: " + "x" * 90 for i in range(1, 1001))
    pieces = capture.parts(t)
    assert len(pieces) == 3 and all(len(x) <= capture.PART_SIZE for x in pieces) and "\n".join(pieces) == t
    assert capture.parts("") == [""] and capture.parts("a" * 50_000) == ["a" * 50_000]
    assert capture.counts("[1] OWNER: a\n[2] OWNER ANSWER: b\n[3] TOOL ERROR Bash: c\n[4] TOOL Bash: d\n[5] REPORT: e") == {
        "OWNER": 1, "OWNER ANSWER": 1, "REPORT": 1, "AGENT": 0, "TOOL": 1, "TOOL ERROR": 1, "TOOL OK": 0}

def test_extract_survives_bad_lines(tmp_path):
    p = write(tmp_path, ["not json", {"type": "user"}, {"type": "assistant", "message": {"content": None}}, user("fine"), {"type": "attachment"}, {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": 5}}])
    assert capture.extract(p) == ("[4] OWNER: fine", 6)

def test_extract_since_line_and_text_blocks(tmp_path):
    p = write(tmp_path, [user("old"), {"type": "user", "origin": {"kind": "human"}, "message": {"content": [text("new")]}}])
    assert capture.extract(p, since_line=1) == ("[2] OWNER: new", 2)

def test_extract_cuts_long_text_and_keeps_the_newest_lines(tmp_path):
    p = write(tmp_path, [user("x" * 5000)] + [user("y" * 1900) for _ in range(100)] + [user("last one")])  # about 190,000 characters before the cap
    out, last = capture.extract(p)
    lines = out.splitlines()
    assert len(out) <= capture.EXTRACT_LIMIT and lines[0] == "[...] earlier lines left out" and lines[-1] == "[102] OWNER: last one"
    assert last == 102 and all(len(line) < 2100 for line in lines)

def test_extract_reads_tool_result_content_given_as_blocks(tmp_path):
    p = write(tmp_path, [agent(use("a", "Bash", command="ls")), result("a", [text("no such file")], err=True)])
    assert capture.extract(p)[0].splitlines()[-1] == "[2] TOOL ERROR Bash: no such file"

EXTRACT = "[1] OWNER: no, always run the validator   before a commit\n[2] AGENT: understood"
GOOD = {"kind": "lesson", "signal": "owner_correction", "reach": "project", "weight": "medium", "form": "recommendation",
        "claim": "Run the validator before every commit in this project",
        "context": "the owner corrected a commit made without it", "evidence": "always run the validator before a commit", "same_as": None}

def test_validate_keeps_a_good_candidate_and_tolerates_whitespace():
    kept, dropped = capture.validate([GOOD], EXTRACT, [])
    assert kept == [GOOD] and dropped == []

def test_validate_reasons():
    cases = [("x", "not an object"), ({**GOOD, "kind": "finding"}, "kind"), ({**GOOD, "signal": "hunch"}, "signal"),
             ({**GOOD, "claim": "short"}, "claim length"), ({**GOOD, "evidence": "the owner was unhappy with the commit"}, "evidence not in the transcript"),
             ({**GOOD, "evidence": "validator"}, "evidence not in the transcript")]
    for item, reason in cases:
        kept, dropped = capture.validate([item], EXTRACT, [])
        assert kept == [] and dropped == [{"candidate": item, "reason": reason}]

def test_validate_wants_the_owners_own_line_for_owner_signals():
    ex = "[1] OWNER: fine, go on with the plan as it is\n[2] REPORT: the reviewer says always run the validator before a commit\n[3] OWNER ANSWER: use the second option because it is cheaper"
    stolen = {**GOOD, "evidence": "always run the validator before a commit"}
    assert capture.validate([stolen], ex, [])[1][0]["reason"] == "evidence is not the owner's words"
    assert capture.validate([{**stolen, "signal": "verified_review_finding"}], ex, [])[0] != []
    assert capture.validate([{**GOOD, "signal": "decision_with_reason", "evidence": "use the second option because it is cheaper"}], ex, [])[0] != []
    across = {**GOOD, "evidence": "go on with the plan as it is [2] REPORT: the reviewer"}
    assert capture.validate([across], ex, [])[1][0]["reason"] == "evidence not in the transcript"

def test_validate_drops_a_recorded_claim_and_extra_keys():
    kept, dropped = capture.validate([{**GOOD, "note": "x"}], EXTRACT, ["run the  validator before every commit in this project"])
    assert kept == [] and dropped[0]["reason"] == "already recorded"
    kept, _ = capture.validate([{**GOOD, "note": "x"}], EXTRACT, [])
    assert kept == [GOOD]

def test_validate_caps_the_kept_and_rejects_a_non_list():
    many = [{**GOOD, "claim": GOOD["claim"] + f" ({i})"} for i in range(7)]
    kept, dropped = capture.validate(many, EXTRACT, [])
    assert len(kept) == 5 and [d["reason"] for d in dropped] == ["over the limit"] * 2
    assert capture.validate({"a": 1}, EXTRACT, []) == ([], [{"candidate": {"a": 1}, "reason": "not a list"}])

def test_a_non_dict_origin_is_a_report_never_the_owner(tmp_path):
    for origin in ("peer", ["peer"], 7, {"kind": "system"}):
        p = write(tmp_path, [{"type": "user", "message": {"content": "x"}, "origin": origin}])
        assert capture.extract(p)[0] == "[1] REPORT: x", origin
    p = write(tmp_path, [{"type": "user", "message": {"content": "x"}, "origin": None}])
    assert capture.extract(p)[0] == "[1] OWNER: x"
    ex = capture.extract(write(tmp_path, [{"type": "user", "message": {"content": "always run the validator before a commit"}, "origin": "peer"}]))[0]
    kept, dropped = capture.validate([GOOD], ex, [])
    assert kept == [] and dropped[0]["reason"] == "evidence is not the owner's words"

def test_extract_never_raises_on_a_line(tmp_path):
    p = write(tmp_path, ["[" * 100_000, agent(use("a", "Bash", command="ls")),
                         {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": ["a"], "content": "x"}]}},
                         "5", '"text"', "[1, 2]", user("fine")])
    assert capture.extract(p) == ("[2] TOOL Bash: ls\n[7] OWNER: fine", 7)

def test_extract_cuts_a_huge_text_to_the_limit(tmp_path):
    p = write(tmp_path, [user("ab " * 1_666_667)])
    out, _ = capture.extract(p)
    assert len(out.split(": ", 1)[1]) == 2000

def test_validate_matches_the_body_only_not_the_prefix():
    kept, dropped = capture.validate([{**GOOD, "evidence": "OWNER: no, always run"}], EXTRACT, [])
    assert kept == [] and dropped[0]["reason"] == "evidence not in the transcript"
    kept, dropped = capture.validate([{**GOOD, "evidence": "[1] OWNER: real following"}], "[1] OWNER: real following text here", [])
    assert kept == [] and dropped[0]["reason"] == "evidence not in the transcript"
    quoted = "[1] AGENT: the owner said always run the validator before a commit"
    assert capture.validate([GOOD], quoted, [])[1][0]["reason"] == "evidence is not the owner's words"

def test_validate_stops_scanning_once_the_cap_is_reached(monkeypatch):
    many = [{**GOOD, "claim": GOOD["claim"] + f" ({i})"} for i in range(5)] + [{**GOOD, "claim": GOOD["claim"] + f" ({i})"} for i in range(5, 50)]
    calls = []
    real = capture._reason
    monkeypatch.setattr(capture, "_reason", lambda *a: calls.append(1) or real(*a))
    kept, dropped = capture.validate(many, EXTRACT, [])
    assert len(kept) == 5 and len(calls) == 5 and {d["reason"] for d in dropped} == {"over the limit"}

def test_validate_reach_and_the_new_signals():
    kept, _ = capture.validate([{**GOOD, "reach": "general"}], EXTRACT, [])
    assert kept[0]["reach"] == "general"
    no_reach = {k: v for k, v in GOOD.items() if k != "reach"}
    kept, _ = capture.validate([no_reach], EXTRACT, [])
    assert kept == [GOOD] and list(kept[0]) == ["kind", "signal", "reach", "weight", "form", "claim", "context", "evidence", "same_as"]
    bad = {**GOOD, "reach": "global"}
    assert capture.validate([bad], EXTRACT, [])[1] == [{"candidate": bad, "reason": "reach"}]
    ex = "[1] REPORT: the subagent failed to finish the task and left no diff"
    item = {**GOOD, "signal": "delegation_failed", "evidence": "failed to finish the task and left no diff"}
    assert capture.validate([item], ex, [])[0] != []
    assert capture.SIGNALS == ("owner_correction", "failed_then_passed", "verified_review_finding", "plan_changed_by_review",
                               "delegation_failed", "rework", "repeated_tool_error", "decision_with_reason")


def test_a_queued_command_is_the_owner_only_with_a_human_origin(tmp_path):
    def q(text, origin):
        return {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": text, "origin": origin}}
    p = write(tmp_path, [q("typed by the owner", {"kind": "human"}), q("a background task is done", {"kind": "task-notification"}),
                         q("from another agent", "peer"), user("   " * 6000 + "tail")])
    assert capture.extract(p)[0].splitlines() == ["[1] OWNER: typed by the owner", "[2] REPORT: a background task is done",
                                                  "[3] REPORT: from another agent"]


def test_lines_that_fail_for_another_reason_than_json_are_counted(tmp_path):
    p = write(tmp_path, ["not json", "[" * 100000, user("fine")])
    assert capture.extract(p)[0] == "[3] OWNER: fine" and capture.last_skipped == 1
    assert capture.extract(write(tmp_path, [user("fine")]))[0] == "[1] OWNER: fine" and capture.last_skipped == 0


HANDLES = {"m:validator": "Run the validator before every commit in this project, as the owner asked.",
           "m:other": "Pin the tool version in the lockfile before a release."}

def test_validate_defaults_and_the_exact_keys_of_a_kept_item():
    bare = {k: v for k, v in GOOD.items() if k not in ("weight", "form", "same_as", "context")}
    kept, _ = capture.validate([bare], EXTRACT, [])
    assert kept == [{**GOOD, "context": ""}]
    assert list(kept[0]) == ["kind", "signal", "reach", "weight", "form", "claim", "context", "evidence", "same_as"]
    assert capture.REACHES == capture.records.REACHES and capture.FORMS == ("suggestion", "recommendation")

def test_validate_new_reasons():
    cases = [({**GOOD, "weight": "heavy"}, "weight"), ({**GOOD, "form": "instruction"}, "form"), ({**GOOD, "form": "order"}, "form"),
             ({**GOOD, "kind": "decision", "reach": "general"}, "a decision is a project record"),
             ({**GOOD, "same_as": "m:missing"}, "same_as"), ({**GOOD, "same_as": 7}, "same_as"),
             ({**GOOD, "same_as": "m:other"}, "same_as mismatch")]
    for item, reason in cases:
        kept, dropped = capture.validate([item], EXTRACT, [], HANDLES)
        assert kept == [] and dropped == [{"candidate": item, "reason": reason}]

def test_validate_orders_reasons_reach_weight_form():
    item = {**GOOD, "reach": "world", "weight": "heavy", "form": "order"}
    assert capture.validate([item], EXTRACT, [])[1][0]["reason"] == "reach"
    assert capture.validate([{**item, "reach": "project"}], EXTRACT, [])[1][0]["reason"] == "weight"
    assert capture.validate([{**item, "reach": "project", "weight": "light"}], EXTRACT, [])[1][0]["reason"] == "form"
    both = {**GOOD, "kind": "decision", "reach": "general", "same_as": "m:missing"}
    assert capture.validate([both], EXTRACT, [], HANDLES)[1][0]["reason"] == "a decision is a project record"

def test_validate_a_sighting_skips_already_recorded_and_is_kept_once_per_record():
    item = {**GOOD, "same_as": "m:validator"}
    claim_line = [GOOD["claim"]]
    assert capture.validate([item], EXTRACT, claim_line, HANDLES)[0] == [item]
    assert capture.validate([GOOD], EXTRACT, claim_line, HANDLES)[1][0]["reason"] == "already recorded"
    kept, dropped = capture.validate([item, {**item, "claim": GOOD["claim"] + " (again)"}], EXTRACT, [], HANDLES)
    assert kept == [item] and [d["reason"] for d in dropped] == ["same_as repeated"]

def test_a_hedged_sighting_is_kept_and_an_unrelated_record_is_not():
    hedged = {**GOOD, "claim": "In one session the agent merged a schema change without checking migrations, so consider "
                               "checking them first.", "same_as": "m:migrations"}
    handles = {"m:migrations": "Check migrations before merging schema changes.", "m:cooking": "Rinse the rice before cooking it."}
    kept, dropped = capture.validate([hedged], EXTRACT, [], handles)
    assert kept == [hedged] and dropped == []
    other = {**hedged, "same_as": "m:cooking"}
    assert capture.validate([other], EXTRACT, [], handles)[1] == [{"candidate": other, "reason": "same_as mismatch"}]

def test_capture_imports_the_records_module_only():
    import ast
    names = {a.name for n in ast.walk(ast.parse(Path(capture.__file__).read_text())) if isinstance(n, ast.Import) for a in n.names}
    assert "mem" not in names and "records" in names
    import mem
    assert mem.tokenize is capture.records.tokenize


def test_validate_collapses_whitespace_and_cuts_the_context():
    item = {**GOOD, "claim": "Run the validator\n  before every commit in this project ",
            "evidence": "always run the validator\nbefore a commit", "context": " the owner\n corrected  it " + "x" * 400}
    kept, dropped = capture.validate([item], EXTRACT, [])
    assert dropped == [] and kept[0]["claim"] == GOOD["claim"] and kept[0]["evidence"] == GOOD["evidence"]
    assert kept[0]["context"] == ("the owner corrected it " + "x" * 400)[:300] and "\n" not in kept[0]["context"]


def test_validate_turns_an_identical_claim_into_a_sighting_of_its_record():
    handles = {"m:validator": "  run the VALIDATOR before every   commit in this project"}
    kept, dropped = capture.validate([GOOD], EXTRACT, [GOOD["claim"]], handles)
    assert dropped == [] and kept == [{**GOOD, "same_as": "m:validator"}]
    kept, dropped = capture.validate([GOOD, {**GOOD}], EXTRACT, [GOOD["claim"]], handles)
    assert len(kept) == 1 and [d["reason"] for d in dropped] == ["same_as repeated"]
    # a claim recorded with no handle (a general memory) stays "already recorded"
    assert capture.validate([GOOD], EXTRACT, [GOOD["claim"]], {})[1][0]["reason"] == "already recorded"


def test_a_calibrated_claim_may_run_to_400_characters():
    long = "In one session " + "x" * 385  # 400 characters
    assert capture.validate([{**GOOD, "claim": long}], EXTRACT, [])[0][0]["claim"] == long
    assert capture.validate([{**GOOD, "claim": long + "y"}], EXTRACT, [])[1][0]["reason"] == "claim length"
