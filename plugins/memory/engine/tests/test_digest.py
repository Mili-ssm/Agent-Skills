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


# --- Task 4: what the step asks for and what it keeps ---

import copy

import pytest

OK = {"fits": True, "faithful": True}


def _topics(*lessons, topic="a"):
    return {topic: list(lessons)}


def _fresh(n=3):
    ls = [_lesson(f"a{i}") for i in range(1, n + 1)]
    return ls, _digest_for(ls)


def _state(**tries):
    return {"tries": dict(tries), "failures": {"count": 0, "fingerprint": ""}}


def _hkey(topic, ls):
    return f"h:{topic}@{digest.heading_print(ls)}"


def _lkey(m, ls):
    return f"l:{m.handle}@{digest.line_print(m)}@{digest.heading_print(ls)}"


def _answer(w, heading="Fresh heading", suffix=" ok"):
    return {w.topic: {"heading": heading if w.heading_state == "write" else None,
                      "lines": {m.handle: f"Rule {m.handle}.{suffix}" for m in w.write}}}


def _all_ok(ws, proposed):
    return {ident: OK for ident, *_ in digest.pairs(ws, proposed)}


def test_work_asks_for_a_new_topic_whole():
    ls = [_lesson(f"a{i}") for i in range(3)]
    (w,) = digest.work(_topics(*ls), {"topics": {}}, _state())
    assert (w.topic, w.heading, w.heading_state, w.keep) == ("a", None, "write", {})
    assert w.write == ls and w.lessons == ls


def test_work_asks_only_for_the_changed_lesson():
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    # the heading print depends on claims only, so the heading stays fresh
    (w,) = digest.work(_topics(*changed), d, _state())
    assert w.heading_state == "keep" and w.heading == "Heading"
    assert w.write == [changed[0]]
    assert w.keep == {"a2": "text a2", "a3": "text a3"}


def test_work_asks_for_a_heading_when_the_topic_changed():
    ls, d = _fresh()
    joined = [*ls, _lesson("a4")]
    (w,) = digest.work(_topics(*joined), d, _state())
    assert w.heading is None and w.heading_state == "write"
    assert w.write == [joined[3]]
    assert set(w.keep) == {"a1", "a2", "a3"}


def test_nothing_to_ask_gives_no_work():
    ls, d = _fresh()
    assert digest.work(_topics(*ls), d, _state()) == []


def test_tries_are_respected():
    ls = [_lesson("a1"), _lesson("a2")]
    assert digest.work(_topics(*ls), {"topics": {}}, _state(**{_hkey("a", ls): 2})) == []
    assert digest.work(_topics(*ls), {"topics": {}}, _state(**{_hkey("a", ls): 1}))[0].write == ls
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    assert digest.work(_topics(*changed), d, _state(**{_lkey(changed[0], changed): 2})) == []


def test_blocks_text():
    ls, d = _fresh(2)
    ls[0] = dataclasses.replace(ls[0], short="Reworded rule.", context="Some\ncontext.")
    (w,) = digest.work(_topics(*ls), d, _state())
    assert digest.blocks([w]) == (
        "topic: a\nheading: Heading\nheading: keep\n\n"
        "id: g:a1\ndo: write\nclaim: Claim a1.\ncontext: Some context.\nshort: Reworded rule.\n\n"
        "id: g:a2\ndo: keep\nclaim: Claim a2.\nshort: Rule a2.\nline: text a2")
    (w2,) = digest.work(_topics(*ls[:1]), {"topics": {}}, _state())
    assert digest.blocks([w2, w2]).count("\n\n\n") == 1
    assert digest.blocks([w2]).startswith("topic: a\nheading: write\n\nid: g:a1\n")


def test_validate_keeps_only_what_was_asked():
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    (w,) = digest.work(_topics(*changed), d, _state())
    got = digest.validate({"topics": [
        {"topic": "a", "heading": "Other", "lines": [{"id": "g:a1", "line": "New."}, {"id": "g:a2", "line": "No."},
                                                     {"id": "g:a3", "line": 3}]},
        {"topic": "zz", "lines": []}]}, [w])
    assert got == {"a": {"heading": None, "lines": {"a1": "New."}}}
    (w2,) = digest.work(_topics(*ls), {"topics": {}}, _state())
    assert digest.validate({"topics": [{"topic": "a", "heading": 5, "lines": "x"}]}, [w2]) == {
        "a": {"heading": None, "lines": {}}}
    assert digest.validate({"topics": [{"topic": "a", "heading": "H"}]}, [w2])["a"]["heading"] == "H"
    for bad in ([], {"topics": {}}, {"topics": "x"}, None):
        with pytest.raises(ValueError):
            digest.validate(bad, [w])


def test_problems():
    m = dataclasses.replace(_lesson("x"), claim="It may help to wait.")
    assert digest.heading_problem("Waiting for builds") is None
    for bad in ("", "  ", "a\nb", " a", "a ", "x" * 81, "Ends with a period.", "Ends with colon:"):
        assert digest.heading_problem(bad)
    assert digest.line_problem("Wait for the build.", dataclasses.replace(m, claim="Wait for the build.")) is None
    assert digest.line_problem("Wait for the build.", m)  # drops the claim's "may"
    for bad in ("", "a\nb", " a", "a ", "x" * 121):
        assert digest.line_problem(bad, m)


def _new_topic(n=3):
    ls = [_lesson(f"a{i}") for i in range(1, n + 1)]
    ws = digest.work(_topics(*ls), {"topics": {}}, _state())
    return ls, ws


def test_decide_stores_what_passed():
    ls, ws = _new_topic()
    prop = _answer(ws[0])
    new, st, counts = digest.decide(ws, prop, _all_ok(ws, prop), {"topics": {}}, _state())
    assert counts == {"headings_written": 1, "lines_written": 3, "refused_code": 0, "refused_check": 0, "missing": 0}
    assert digest.heading(new, "a", ls) == "Fresh heading"
    assert [digest.line(new, "a", m, ls) for m in ls] == [f"Rule {m.handle}. ok" for m in ls]
    assert st["tries"] == {}
    assert digest.work(_topics(*ls), new, st) == []


def test_a_refused_line_is_tried_twice_then_left():
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    ws = digest.work(_topics(*changed), d, _state())
    prop = _answer(ws[0])
    verdicts = {"g:a1": {"fits": True, "faithful": False}}
    new, st, counts = digest.decide(ws, prop, verdicts, d, _state())
    assert new == d and st["tries"] == {_lkey(changed[0], changed): 1} and counts["refused_check"] == 1
    ws = digest.work(_topics(*changed), new, st)
    assert ws
    new, st, _ = digest.decide(ws, prop, verdicts, new, st)
    assert st["tries"][_lkey(changed[0], changed)] == 2
    assert digest.work(_topics(*changed), new, st) == []


def test_a_heading_that_does_not_fit_stores_nothing_for_the_topic():
    ls, ws = _new_topic()
    prop = _answer(ws[0])
    verdicts = _all_ok(ws, prop)
    verdicts["g:a2"] = {"fits": False, "faithful": True}
    new, st, counts = digest.decide(ws, prop, verdicts, {"topics": {}}, _state())
    assert new == {"topics": {}}
    assert st["tries"] == {_hkey("a", ls): 1} and counts["refused_check"] == 1 and counts["lines_written"] == 0
    verdicts["g:a2"] = {"fits": "true", "faithful": True}  # only the exact value true counts
    assert digest.decide(ws, prop, verdicts, {"topics": {}}, _state())[0] == {"topics": {}}


def _joined():
    ls, d = _fresh()
    joined = [*ls, _lesson("a4")]
    return ls, d, joined, digest.work(_topics(*joined), d, _state())


def test_a_kept_line_unfaithful_under_a_new_heading_is_removed():
    ls, d, joined, ws = _joined()
    prop = _answer(ws[0])
    verdicts = _all_ok(ws, prop)
    verdicts["g:a2"] = {"fits": True, "faithful": False}
    new, st, _ = digest.decide(ws, prop, verdicts, d, _state())
    assert "a2" not in new["topics"]["a"]["lines"]
    (w,) = digest.work(_topics(*joined), new, st)
    assert w.heading_state == "keep" and w.write == [joined[1]]


def test_a_kept_line_still_prints_under_a_rewritten_heading():
    ls, d, joined, ws = _joined()
    prop = _answer(ws[0])
    new, st, counts = digest.decide(ws, prop, _all_ok(ws, prop), d, _state())
    assert counts["headings_written"] == 1 and counts["lines_written"] == 1
    assert [digest.line(new, "a", m, joined) for m in joined] == ["text a1", "text a2", "text a3", "Rule a4. ok"]
    assert digest.work(_topics(*joined), new, st) == []


def test_a_given_up_heading_asks_for_nothing():
    ls = [_lesson("a1"), _lesson("a2")]
    assert digest.work(_topics(*ls), {"topics": {}}, _state(**{_hkey("a", ls): 2})) == []


def test_a_heading_without_any_pair_is_not_accepted():
    ls, ws = _new_topic(2)
    prop = {"a": {"heading": "Fine heading", "lines": {"a1": "", "a2": "two\nlines"}}}
    assert digest.pairs(ws, prop) == []
    new, st, counts = digest.decide(ws, prop, {}, {"topics": {}}, _state())
    assert new == {"topics": {}} and st["tries"] == {_hkey("a", ls): 1} and counts["refused_code"] == 1


def test_the_limit_of_lessons_keeps_topics_whole():
    topics = {t: [_lesson(f"{t}{i}", topic=t) for i in range(n)] for t, n in (("a", 20), ("b", 15), ("c", 5))}
    assert [w.topic for w in digest.work(topics, {"topics": {}}, _state())] == ["a", "b"]


def test_decide_does_not_mutate_its_inputs():
    ls, d, joined, ws = _joined()
    prop = _answer(ws[0])
    verdicts = _all_ok(ws, prop)
    before = copy.deepcopy((ws, prop, verdicts, d))
    st = _state()
    st0 = copy.deepcopy(st)
    digest.decide(ws, prop, verdicts, d, st)
    assert (ws, prop, verdicts, d) == before and st == st0
