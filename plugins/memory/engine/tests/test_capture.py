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
GOOD = {"kind": "lesson", "signal": "owner_correction", "claim": "Run the validator before every commit in this project",
        "context": "the owner corrected a commit made without it", "evidence": "always run the validator before a commit"}

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
