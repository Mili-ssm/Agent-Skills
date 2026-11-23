import dataclasses
import datetime
import json

import digest
import records

TODAY = datetime.date.today()
K1, K2 = "0123456789ab", "ba9876543210"


def _base():
    """One valid, established, loadable global record (copied from test_rules.py, which is edited elsewhere)."""
    return records.Memory(scope="global", path=None, handle="base", kind="lesson", claim="A claim.",
                          created=datetime.date(2026, 1, 1), observed=1, status="active", context=None,
                          valid_until=None, sources=[f"session s1 project {K1}", f"session s2 project {K2}"],
                          body="", error=None, origin="transcript", weight="light", short="A short rule.")


def _lesson(handle, topic="a", **kw):
    return dataclasses.replace(_base(), handle=handle, claim=f"Claim {handle}.", short=f"Rule {handle}.", topic=topic, **kw)


def _digest_for(lessons, topic="a"):
    h = digest.heading_print(lessons)
    return {"topics": {topic: {"heading": "Heading", "of": h, "lines": {
        m.handle: {"text": f"text {m.handle}", "of": digest.line_print(m), "under": h} for m in lessons}}}}


def test_fingerprints_follow_the_claim_and_the_short_form():
    m = _lesson("x")
    base = digest.line_print(m)
    assert digest.line_print(dataclasses.replace(m, claim="Other.")) != base
    assert digest.line_print(dataclasses.replace(m, short="Other rule.")) != base
    assert digest.line_print(dataclasses.replace(m, log=["x"], versions=["2026-01-01 Old rule."], topic="z")) == base
    ls = [_lesson("a1"), _lesson("a2")]
    hp = digest.heading_print(ls)
    assert digest.heading_print(ls[::-1]) == hp
    assert digest.heading_print(ls[:1]) != hp
    assert digest.heading_print([*ls, _lesson("a3")]) != hp
    assert digest.heading_print([ls[0], dataclasses.replace(ls[1], claim="Changed.")]) != hp


def test_read_drops_what_is_wrong_and_keeps_the_rest(tmp_path):
    empty = {"topics": {}}
    assert digest.read(None) == empty
    assert digest.read(tmp_path) == empty
    f = tmp_path / digest.FILE
    for text in ("", "[]", "not json", '{"topics": []}', '{"topics": {"a": {"heading": "H", "of": "o", "lines": "x"}}}'):
        f.write_text(text)
        assert digest.read(tmp_path) == empty
    good = {"heading": "H", "of": "o", "lines": {"h1": {"text": "t", "of": "o1", "under": "o"}}}
    bad_line = {"text": "t", "under": "o"}
    f.write_text(json.dumps({"topics": {"good": good, "bad": "x", "mixed": {**good, "lines": {
        "h1": good["lines"]["h1"], "h2": bad_line, "h3": 3}}}}))
    got = digest.read(tmp_path)
    assert got["topics"]["good"] == good
    assert got["topics"]["mixed"]["lines"] == {"h1": good["lines"]["h1"]}
    assert "bad" not in got["topics"]


def test_topics_of_keeps_topics_with_two_ready_lessons():
    r1, r2 = _lesson("r1"), _lesson("r2")
    idx = _lesson("i1", load="index")
    lone = _lesson("b1", topic="b")
    none = _lesson("n1", topic=None)
    pend = _lesson("p1", triage="pending")
    got = digest.topics_of([r1, r2, idx, lone, none, pend], TODAY)
    assert list(got) == ["a"]
    assert sorted(m.handle for m in got["a"]) == ["i1", "r1", "r2"]
    assert digest.topics_of([r1, lone], TODAY) == {}


def test_heading_and_line_are_returned_only_when_fresh():
    ls = [_lesson("a1"), _lesson("a2"), _lesson("a3")]
    d = _digest_for(ls)
    assert digest.heading(d, "a", ls) == "Heading"
    assert [digest.line(d, "a", m, ls) for m in ls] == ["text a1", "text a2", "text a3"]
    assert digest.heading(d, "zz", ls) is None
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    assert digest.line(d, "a", changed[0], changed) is None
    assert digest.line(d, "a", changed[1], changed) == "text a2"
    joined = [*ls, _lesson("a4")]
    assert digest.heading(d, "a", joined) is None
    assert all(digest.line(d, "a", m, joined) is None for m in joined)
    d["topics"]["a"]["lines"]["a2"]["under"] = "other"
    assert digest.line(d, "a", ls[1], ls) is None
    assert digest.line(d, "a", ls[0], ls) == "text a1"


def test_write_then_read_round_trip(tmp_path):
    d = _digest_for([_lesson("a1"), _lesson("a2")])
    digest.write(tmp_path, d)
    assert digest.read(tmp_path) == d
    assert [p.name for p in tmp_path.iterdir()] == [digest.FILE]
