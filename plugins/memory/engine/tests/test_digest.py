import dataclasses
import datetime
import json
from typing import Any, cast

from digest import lessons as digest_lessons
from store import records

TODAY = datetime.date.today()
K1, K2 = "0123456789ab", "ba9876543210"
SECOND_TRY = 2
UNJUDGED_TWO = 2
UNJUDGED_THREE = 3
INDEX_TOPICS = 80
HEADING_WIDTH = 80
HEADINGS_TOTAL = 800
TEXT_LIMIT = 9500


def _base():
    """One valid, established, loadable global record (copied from test_rules.py, which is edited elsewhere)."""
    return records.Memory(
        scope="global",
        path=cast("Any", None),  # never read by the digest code under test
        handle="base",
        kind="lesson",
        claim="A claim.",
        created=datetime.date(2026, 1, 1),
        observed=1,
        status="active",
        context=None,
        valid_until=None,
        sources=[f"session s1 project {K1}", f"session s2 project {K2}"],
        body="",
        error=None,
        origin="transcript",
        weight="light",
        short="A short rule.",
    )


def _lesson(handle, topic: str | None = "a", **kw):
    return dataclasses.replace(
        _base(), handle=handle, claim=f"Claim {handle}.", short=f"Rule {handle}.", topic=topic, **kw
    )


def _digest_for(lessons, topic="a"):
    h = digest_lessons.heading_print(lessons)
    return {
        "topics": {
            topic: {
                "heading": "Heading",
                "of": h,
                "lines": {
                    m.handle: {
                        "text": f"text {m.handle}",
                        "of": digest_lessons.line_print(m),
                        "under": h,
                    }
                    for m in lessons
                },
            }
        }
    }


def test_fingerprints_follow_the_claim_and_the_short_form():
    m = _lesson("x")
    base = digest_lessons.line_print(m)
    assert digest_lessons.line_print(dataclasses.replace(m, claim="Other.")) != base
    assert digest_lessons.line_print(dataclasses.replace(m, short="Other rule.")) != base
    assert (
        digest_lessons.line_print(
            dataclasses.replace(m, log=["x"], versions=["2026-01-01 Old rule."], topic="z")
        )
        == base
    )
    ls = [_lesson("a1"), _lesson("a2")]
    hp = digest_lessons.heading_print(ls)
    assert digest_lessons.heading_print(ls[::-1]) == hp
    assert digest_lessons.heading_print(ls[:1]) != hp
    assert digest_lessons.heading_print([*ls, _lesson("a3")]) != hp
    assert digest_lessons.heading_print([ls[0], dataclasses.replace(ls[1], claim="Changed.")]) != hp


def test_read_drops_what_is_wrong_and_keeps_the_rest(tmp_path):
    empty = {"topics": {}}
    assert digest_lessons.read(None) == empty
    assert digest_lessons.read(tmp_path) == empty
    f = tmp_path / digest_lessons.FILE
    for text in (
        "",
        "[]",
        "not json",
        '{"topics": []}',
        '{"topics": {"a": {"heading": "H", "of": "o", "lines": "x"}}}',
    ):
        f.write_text(text)
        assert digest_lessons.read(tmp_path) == empty
    good = {"heading": "H", "of": "o", "lines": {"h1": {"text": "t", "of": "o1", "under": "o"}}}
    bad_line = {"text": "t", "under": "o"}
    f.write_text(
        json.dumps({
            "topics": {
                "good": good,
                "bad": "x",
                "mixed": {**good, "lines": {"h1": good["lines"]["h1"], "h2": bad_line, "h3": 3}},
            }
        })
    )
    got = digest_lessons.read(tmp_path)
    assert got["topics"]["good"] == good
    assert got["topics"]["mixed"]["lines"] == {"h1": good["lines"]["h1"]}
    assert "bad" not in got["topics"]


def test_topics_of_keeps_topics_with_two_ready_lessons():
    r1, r2 = _lesson("r1"), _lesson("r2")
    idx = _lesson("i1", load="index")
    lone = _lesson("b1", topic="b")
    none = _lesson("n1", topic=None)
    pend = _lesson("p1", triage="pending")
    got = digest_lessons.topics_of([r1, r2, idx, lone, none, pend], TODAY)
    assert list(got) == ["a"]
    assert sorted(m.handle for m in got["a"]) == ["i1", "r1", "r2"]
    assert digest_lessons.topics_of([r1, lone], TODAY) == {}


def test_heading_and_line_are_returned_only_when_fresh():
    ls = [_lesson("a1"), _lesson("a2"), _lesson("a3")]
    d = _digest_for(ls)
    assert digest_lessons.heading(d, "a", ls) == "Heading"
    assert [digest_lessons.line(d, "a", m, ls) for m in ls] == ["text a1", "text a2", "text a3"]
    assert digest_lessons.heading(d, "zz", ls) is None
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    assert digest_lessons.line(d, "a", changed[0], changed) is None
    assert digest_lessons.line(d, "a", changed[1], changed) == "text a2"
    joined = [*ls, _lesson("a4")]
    assert digest_lessons.heading(d, "a", joined) is None
    assert all(digest_lessons.line(d, "a", m, joined) is None for m in joined)
    d["topics"]["a"]["lines"]["a2"]["under"] = "other"
    assert digest_lessons.line(d, "a", ls[1], ls) is None
    assert digest_lessons.line(d, "a", ls[0], ls) == "text a1"


def test_write_then_read_round_trip(tmp_path):
    d = _digest_for([_lesson("a1"), _lesson("a2")])
    digest_lessons.write(tmp_path, d)
    assert digest_lessons.read(tmp_path) == d
    assert [p.name for p in tmp_path.iterdir()] == [digest_lessons.FILE]


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
    return f"h:{topic}@{digest_lessons.heading_print(ls)}"


def _lkey(m, ls):
    return f"l:{m.handle}@{digest_lessons.line_print(m)}@{digest_lessons.heading_print(ls)}"


def _answer(w, heading="Fresh heading", suffix=" ok"):
    return {
        w.topic: {
            "heading": heading if w.heading_state == "write" else None,
            "lines": {m.handle: f"Rule {m.handle}.{suffix}" for m in w.write},
        }
    }


def _all_ok(ws, proposed):
    return {ident: OK for ident, *_ in digest_lessons.pairs(ws, proposed)}


def test_work_asks_for_a_new_topic_whole():
    ls = [_lesson(f"a{i}") for i in range(3)]
    (w,) = digest_lessons.work(_topics(*ls), {"topics": {}}, _state())
    assert (w.topic, w.heading, w.heading_state, w.keep) == ("a", None, "write", {})
    assert w.write == ls and w.lessons == ls


def test_work_asks_only_for_the_changed_lesson():
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    # the heading print depends on claims only, so the heading stays fresh
    (w,) = digest_lessons.work(_topics(*changed), d, _state())
    assert w.heading_state == "keep" and w.heading == "Heading"
    assert w.write == [changed[0]]
    assert w.keep == {"a2": "text a2", "a3": "text a3"}


def test_work_asks_for_a_heading_when_the_topic_changed():
    ls, d = _fresh()
    joined = [*ls, _lesson("a4")]
    (w,) = digest_lessons.work(_topics(*joined), d, _state())
    assert w.heading is None and w.heading_state == "write"
    assert w.write == [joined[3]]
    assert set(w.keep) == {"a1", "a2", "a3"}


def test_nothing_to_ask_gives_no_work():
    ls, d = _fresh()
    assert digest_lessons.work(_topics(*ls), d, _state()) == []


def test_tries_are_respected():
    ls = [_lesson("a1"), _lesson("a2")]
    assert digest_lessons.work(_topics(*ls), {"topics": {}}, _state(**{_hkey("a", ls): 2})) == []
    assert (
        digest_lessons.work(_topics(*ls), {"topics": {}}, _state(**{_hkey("a", ls): 1}))[0].write
        == ls
    )
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    assert (
        digest_lessons.work(_topics(*changed), d, _state(**{_lkey(changed[0], changed): 2})) == []
    )


def test_blocks_text():
    ls, d = _fresh(2)
    ls[0] = dataclasses.replace(ls[0], short="Reworded rule.", context="Some\ncontext.")
    (w,) = digest_lessons.work(_topics(*ls), d, _state())
    assert digest_lessons.blocks([w]) == (
        "topic: a\nheading (keep): Heading\n\n"
        "id: g:a1\ndo: write\nclaim: Claim a1.\ncontext: Some context.\nshort: Reworded rule.\n\n"
        "id: g:a2\ndo: keep\nclaim: Claim a2.\nshort: Rule a2.\nline: text a2"
    )
    (w2,) = digest_lessons.work(_topics(*ls[:1]), {"topics": {}}, _state())
    assert digest_lessons.blocks([w2, w2]).count("\n\n\n") == 1
    assert digest_lessons.blocks([w2]).startswith("topic: a\nheading: write\n\nid: g:a1\n")


def test_validate_keeps_only_what_was_asked():
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    (w,) = digest_lessons.work(_topics(*changed), d, _state())
    got = digest_lessons.validate(
        {
            "topics": [
                {
                    "topic": "a",
                    "heading": "Other",
                    "lines": [
                        {"id": "g:a1", "line": "New."},
                        {"id": "g:a2", "line": "No."},
                        {"id": "g:a3", "line": 3},
                    ],
                },
                {"topic": "zz", "lines": []},
            ]
        },
        [w],
    )
    assert got == {"a": {"heading": None, "lines": {"a1": "New."}}}
    (w2,) = digest_lessons.work(_topics(*ls), {"topics": {}}, _state())
    assert digest_lessons.validate(
        {"topics": [{"topic": "a", "heading": 5, "lines": "x"}]}, [w2]
    ) == {"a": {"heading": None, "lines": {}}}
    assert (
        digest_lessons.validate({"topics": [{"topic": "a", "heading": "H"}]}, [w2])["a"]["heading"]
        == "H"
    )
    for bad in ([], {"topics": {}}, {"topics": "x"}, None):
        with pytest.raises(ValueError):
            digest_lessons.validate(bad, [w])


def test_problems():
    m = dataclasses.replace(_lesson("x"), claim="It may help to wait.")
    assert digest_lessons.heading_problem("Waiting for builds") is None
    for bad in ("", "  ", "a\nb", " a", "a ", "x" * 81, "Ends with a period.", "Ends with colon:"):
        assert digest_lessons.heading_problem(bad)
    assert (
        digest_lessons.line_problem(
            "Wait for the build.", dataclasses.replace(m, claim="Wait for the build.")
        )
        is None
    )
    assert digest_lessons.line_problem("Wait for the build.", m)  # drops the claim's "may"
    for bad in ("", "a\nb", " a", "a ", "x" * 121):
        assert digest_lessons.line_problem(bad, m)


def _new_topic(n=3):
    ls = [_lesson(f"a{i}") for i in range(1, n + 1)]
    ws = digest_lessons.work(_topics(*ls), {"topics": {}}, _state())
    return ls, ws


def test_decide_stores_what_passed():
    ls, ws = _new_topic()
    prop = _answer(ws[0])
    new, st, counts = digest_lessons.decide(ws, prop, _all_ok(ws, prop), {"topics": {}}, _state())
    assert counts == {
        "headings_written": 1,
        "lines_written": 3,
        "refused_code": 0,
        "refused_check": 0,
        "missing": 0,
        "unjudged": 0,
    }
    assert digest_lessons.heading(new, "a", ls) == "Fresh heading"
    assert [digest_lessons.line(new, "a", m, ls) for m in ls] == [
        f"Rule {m.handle}. ok" for m in ls
    ]
    assert st["tries"] == {}
    assert digest_lessons.work(_topics(*ls), new, st) == []


def test_a_refused_line_is_tried_twice_then_left():
    ls, d = _fresh()
    changed = [dataclasses.replace(ls[0], short="Reworded rule."), *ls[1:]]
    ws = digest_lessons.work(_topics(*changed), d, _state())
    prop = _answer(ws[0])
    verdicts = {"g:a1": {"fits": True, "faithful": False}}
    new, st, counts = digest_lessons.decide(ws, prop, verdicts, d, _state())
    assert (
        new == d and st["tries"] == {_lkey(changed[0], changed): 1} and counts["refused_check"] == 1
    )
    ws = digest_lessons.work(_topics(*changed), new, st)
    assert ws
    new, st, _ = digest_lessons.decide(ws, prop, verdicts, new, st)
    assert st["tries"][_lkey(changed[0], changed)] == SECOND_TRY
    assert digest_lessons.work(_topics(*changed), new, st) == []


def test_a_heading_that_does_not_fit_stores_nothing_for_the_topic():
    ls, ws = _new_topic()
    prop = _answer(ws[0])
    verdicts: dict[str, Any] = _all_ok(ws, prop)
    verdicts["g:a2"] = {"fits": False, "faithful": True}
    new, st, counts = digest_lessons.decide(ws, prop, verdicts, {"topics": {}}, _state())
    assert new == {"topics": {}}
    assert (
        st["tries"] == {_hkey("a", ls): 1}
        and counts["refused_check"] == 1
        and counts["lines_written"] == 0
    )
    verdicts["g:a2"] = {"fits": "true", "faithful": True}  # only the exact value true counts
    assert digest_lessons.decide(ws, prop, verdicts, {"topics": {}}, _state())[0] == {"topics": {}}


def _joined():
    ls, d = _fresh()
    joined = [*ls, _lesson("a4")]
    return ls, d, joined, digest_lessons.work(_topics(*joined), d, _state())


def test_a_kept_line_unfaithful_under_a_new_heading_is_removed():
    _ls, d, joined, ws = _joined()
    prop = _answer(ws[0])
    verdicts = _all_ok(ws, prop)
    verdicts["g:a2"] = {"fits": True, "faithful": False}
    new, st, _ = digest_lessons.decide(ws, prop, verdicts, d, _state())
    assert "a2" not in new["topics"]["a"]["lines"]
    (w,) = digest_lessons.work(_topics(*joined), new, st)
    assert w.heading_state == "keep" and w.write == [joined[1]]


def test_a_kept_line_still_prints_under_a_rewritten_heading():
    _ls, d, joined, ws = _joined()
    prop = _answer(ws[0])
    new, st, counts = digest_lessons.decide(ws, prop, _all_ok(ws, prop), d, _state())
    assert counts["headings_written"] == 1 and counts["lines_written"] == 1
    assert [digest_lessons.line(new, "a", m, joined) for m in joined] == [
        "text a1",
        "text a2",
        "text a3",
        "Rule a4. ok",
    ]
    assert digest_lessons.work(_topics(*joined), new, st) == []


def test_a_given_up_heading_asks_for_nothing():
    ls = [_lesson("a1"), _lesson("a2")]
    assert digest_lessons.work(_topics(*ls), {"topics": {}}, _state(**{_hkey("a", ls): 2})) == []


def test_a_heading_without_any_pair_is_not_accepted():
    ls, ws = _new_topic(2)
    prop = {"a": {"heading": "Fine heading", "lines": {"a1": "", "a2": "two\nlines"}}}
    assert digest_lessons.pairs(ws, prop) == []
    new, st, counts = digest_lessons.decide(ws, prop, {}, {"topics": {}}, _state())
    assert (
        new == {"topics": {}} and st["tries"] == {_hkey("a", ls): 1} and counts["refused_code"] == 1
    )


def test_the_limit_of_lessons_keeps_topics_whole():
    topics = {
        t: [_lesson(f"{t}{i}", topic=t) for i in range(n)]
        for t, n in (("a", 20), ("b", 15), ("c", 5))
    }
    assert [w.topic for w in digest_lessons.work(topics, {"topics": {}}, _state())] == ["a", "b"]


def test_decide_does_not_mutate_its_inputs():
    _, d, _joined_lessons, ws = _joined()
    prop = _answer(ws[0])
    verdicts = _all_ok(ws, prop)
    before = copy.deepcopy((ws, prop, verdicts, d))
    st = _state()
    st0 = copy.deepcopy(st)
    digest_lessons.decide(ws, prop, verdicts, d, st)
    assert (ws, prop, verdicts, d) == before and st == st0


# --- end-review fixes ---


def test_read_checks_stored_texts_again(tmp_path):
    ls = [_lesson("a1"), _lesson("a2")]
    good = _digest_for(ls)["topics"]["a"]
    f = tmp_path / digest_lessons.FILE

    def got(entry):
        f.write_text(json.dumps({"topics": {"a": entry}}))
        return digest_lessons.read(tmp_path)["topics"]

    assert got(good)["a"] == good
    for bad in (
        "Builds\n- INJECTED lesson",
        "a\rb",
        "a\tb",
        "a\x1bb",
        "a\x7fb",
        "",
        "   ",
        "x" * (digest_lessons.HEADING_LIMIT + 1),
    ):
        assert got({**good, "heading": bad}) == {}  # a topic without a heading keeps no lines
    for bad in ("one\ntwo", "a\tb", "a\x00b", "a\x7fb", "", "x" * (records.SHORT_LIMIT + 1)):
        lines = {**good["lines"], "a1": {**good["lines"]["a1"], "text": bad}}
        assert got({**good, "lines": lines})["a"]["lines"] == {"a2": good["lines"]["a2"]}
    ok_long = {**good["lines"]["a1"], "text": "x" * records.SHORT_LIMIT}
    assert got({**good, "heading": "h" * digest_lessons.HEADING_LIMIT, "lines": {"a1": ok_long}})[
        "a"
    ]["lines"] == {"a1": ok_long}


def test_a_heading_with_a_newline_prints_as_the_grouped_block(tmp_path):
    ls = _two()
    d = _full(ls, heading="Builds\n- INJECTED lesson")
    (tmp_path / digest_lessons.FILE).write_text(json.dumps(d))
    stored = digest_lessons.read(tmp_path)
    choice = rules.Choice(loaded=ls)
    assert rules.block(choice, "digest", digest=stored, topics={"a": ls}) == rules.block(
        choice, "grouped"
    )


def test_control_characters_are_a_form_problem():
    m = dataclasses.replace(_lesson("x"), claim="Wait for the build.")
    for bad in ("Wait\tfor", "Wait\x07for", "Wait\x7ffor", "Wait\rfor"):
        assert digest_lessons.heading_problem(bad)
        assert digest_lessons.line_problem(bad, m)


def test_pruned_drops_what_no_longer_applies():
    ls, d = _fresh()
    other = [_lesson("b1", topic="b"), _lesson("b2", topic="b")]
    d["topics"]["b"] = _digest_for(other, "b")["topics"]["b"]
    st = _state(**{
        _hkey("a", ls): 1,
        _lkey(ls[0], ls): 2,
        _hkey("b", other): 1,
        "l:gone@x@y": 1,
        "h:a@old": 1,
    })
    st["failures"] = {"count": 2, "fingerprint": "f"}
    new_d, new_st = digest_lessons.pruned(d, st, _topics(*ls))
    assert list(new_d["topics"]) == ["a"] and new_d["topics"]["a"] == d["topics"]["a"]
    assert (
        new_st["tries"] == {_hkey("a", ls): 1, _lkey(ls[0], ls): 2}
        and new_st["failures"] == st["failures"]
    )
    # a line whose lesson left the topic goes, the others stay
    fewer = ls[:2]
    new_d, new_st = digest_lessons.pruned(d, st, _topics(*fewer))
    assert sorted(new_d["topics"]["a"]["lines"]) == ["a1", "a2"]
    # a lesson without a valid short form has no line key
    nos = [dataclasses.replace(ls[0], short=None), *ls[1:]]
    _, new_st = digest_lessons.pruned(
        d, _state(**{_lkey(nos[0], nos): 1, _lkey(ls[1], nos): 1}), _topics(*nos)
    )
    assert new_st["tries"] == {_lkey(ls[1], nos): 1}


def test_pruned_changes_nothing_passed_in_and_keeps_a_full_digest():
    ls, d = _fresh()
    st = _state(**{_hkey("a", ls): 1})
    before = copy.deepcopy((d, st))
    new_d, new_st = digest_lessons.pruned(d, st, _topics(*ls))
    assert (d, st) == before and new_d == d and new_st == st
    assert digest_lessons.pruned({"topics": {}}, _state(), {}) == ({"topics": {}}, _state())


def test_a_lesson_without_a_verdict_is_not_judged():
    ls, ws = _new_topic()
    prop = _answer(ws[0])
    verdicts = {"g:a1": OK}
    new, st, counts = digest_lessons.decide(ws, prop, verdicts, {"topics": {}}, _state())
    assert (
        counts["unjudged"] == UNJUDGED_TWO
        and counts["headings_written"] == 1
        and counts["lines_written"] == 1
    )
    assert counts["refused_check"] == 0 and st["tries"] == {}
    assert list(new["topics"]["a"]["lines"]) == ["a1"]
    # a verdict that is present and not true still spends a try
    verdicts = {"g:a1": OK, "g:a2": {"fits": True, "faithful": False}}
    new, st, counts = digest_lessons.decide(ws, prop, verdicts, {"topics": {}}, _state())
    assert (
        counts["unjudged"] == 1
        and counts["refused_check"] == 1
        and st["tries"] == {_lkey(ls[1], ls): 1}
    )
    assert sorted(new["topics"]["a"]["lines"]) == ["a1"]


def test_a_heading_needs_one_verdict_and_every_verdict_fitting():
    ls, ws = _new_topic()
    prop = _answer(ws[0])
    new, st, counts = digest_lessons.decide(ws, prop, {}, {"topics": {}}, _state())
    assert (
        new == {"topics": {}}
        and st["tries"] == {}
        and counts["unjudged"] == UNJUDGED_THREE
        and counts["refused_check"] == 0
    )
    verdicts = {"g:a1": OK, "g:a2": {"fits": False, "faithful": True}}
    new, st, counts = digest_lessons.decide(ws, prop, verdicts, {"topics": {}}, _state())
    assert (
        new == {"topics": {}}
        and st["tries"] == {_hkey("a", ls): 1}
        and counts["refused_check"] == 1
    )


# --- printing the digest and the index (Task 3) ---

import os
import subprocess

import mem
import pytest
from store import rules
from test_rules_session import PLUGIN, pad


def _full(lessons, topic="a", heading="when doing x", texts=None):
    h = digest_lessons.heading_print(lessons)
    return {
        "topics": {
            topic: {
                "heading": heading,
                "of": h,
                "lines": {
                    m.handle: {
                        "text": (texts or {}).get(m.handle, f"text {m.handle}"),
                        "of": digest_lessons.line_print(m),
                        "under": h,
                    }
                    for m in lessons
                },
            }
        }
    }


def _two():
    return [_lesson("a1"), _lesson("a2")]


def test_a_fresh_digest_prints_heading_and_lines():
    ls = _two()
    choice = rules.Choice(loaded=ls)
    want = [
        rules.HEADER,
        "a: when doing x",
        *(f"- text {m.handle} (held in 2 projects)" for m in ls),
    ]
    assert rules.block(choice, "digest", digest=_full(ls), topics={"a": ls}) == want


def test_a_changed_lesson_prints_its_short_form_and_the_rest_keep_their_lines():
    ls = _two()
    d = _full(ls)
    ls[1] = dataclasses.replace(
        ls[1], short="New rule."
    )  # the heading is fresh only for the claims, which did not change
    got = rules.block(rules.Choice(loaded=ls), "digest", digest=d, topics={"a": ls})
    assert got[1:] == ["a: when doing x", "- text a1 (held in 2 projects)", rules.line(ls[1])]


def test_a_changed_topic_prints_the_bare_topic():
    ls = _two()
    d = _full(ls)
    more = [*ls, _lesson("a3")]
    got = rules.block(rules.Choice(loaded=more), "digest", digest=d, topics={"a": more})
    assert got[1:] == ["a:", *map(rules.line, more)]


def test_no_digest_equals_grouped():
    ls = _two()
    choice = rules.Choice(loaded=ls)
    grouped = rules.block(choice, "grouped")
    assert rules.block(choice, "digest") == grouped
    assert rules.block(choice, "digest", digest={"topics": {}}, topics={"a": ls}) == grouped


def test_a_project_lesson_prints_its_short_form_under_the_heading():
    ls = _two()
    proj = dataclasses.replace(_lesson("p1"), scope="project")
    choice = rules.Choice(loaded=[ls[0], proj, ls[1]])
    got = rules.block(choice, "digest", digest=_full(ls), topics={"a": ls})
    assert got[1:] == [
        "a: when doing x",
        "- text a1 (held in 2 projects)",
        "- text a2 (held in 2 projects)",
        rules.line(proj),
    ]


def test_a_stale_line_prints_after_the_digest_lines_and_a_bare_topic_keeps_its_order():
    ls = [*_two(), _lesson("a3")]
    d = _full(ls)
    stale = [dataclasses.replace(ls[0], short="New rule."), *ls[1:]]
    got = rules.block(rules.Choice(loaded=stale), "digest", digest=d, topics={"a": stale})
    assert got[1:] == [
        "a: when doing x",
        "- text a2 (held in 2 projects)",
        "- text a3 (held in 2 projects)",
        rules.line(stale[0]),
    ]
    more = [*ls, _lesson("a4")]  # a changed topic has no heading: no reordering
    proj = dataclasses.replace(_lesson("p1"), scope="project")
    got = rules.block(rules.Choice(loaded=[proj, *more]), "digest", digest=d, topics={"a": more})
    assert got[1:] == ["a:", *map(rules.line, [proj, *more])]


def test_the_order_under_a_heading_keeps_the_limit():
    ls = [dataclasses.replace(_lesson(f"l{i:02}"), short=pad("Rule", 60)) for i in range(40)]
    proj = dataclasses.replace(_lesson("p1"), scope="project", short=pad("Rule", 60))
    choice = rules.Choice(loaded=[proj, *ls[:29]])
    texts = {m.handle: pad("Digest", 120) for m in ls}
    got = rules.block(choice, "digest", digest=_full(ls, texts=texts), topics={"a": ls})
    printed = got[2:]
    assert sum(len(x) + 1 for x in printed) <= rules.RULES_LIMIT and rules.line(proj) in printed


def test_index_names_the_headings_of_topics_left_out():
    a, b = _two(), [_lesson("b1", topic="b")]
    left = rules.Choice(left=[(m, rules.OVER) for m in [*a, *b]])
    assert rules.index_lines(left, digest=_full(a), topics={"a": a}) == [
        "More lessons, by topic (mem rules --more <topic>):",
        "- a (2): when doing x",
        "- b (1)",
    ]
    assert rules.index_lines(left) == [rules.more_line(left)]
    assert rules.index_lines(left, digest={"topics": {}}, topics={"a": a}) == [
        rules.more_line(left)
    ]
    assert rules.index_lines(rules.Choice(), digest=_full(a), topics={"a": a}) == []


def test_the_index_sums_the_topics_left_out_in_the_singular_or_the_plural():
    groups = dict(list(_forty().items())[:17])
    left = rules.Choice(left=[(m, rules.OVER) for ls in groups.values() for m in ls])
    tails = set()
    for size in range(60, 81):  # the longer the headings, the fewer topics fit
        got = rules.index_lines(left, digest=_digest_of(groups, "h" * size), topics=groups)
        if got[-1].startswith("- and "):
            tails.add(got[-1])
    assert "- and 2 more in 1 topic" in tails and "- and 4 more in 2 topics" in tails
    assert not any(" in 1 topics" in t for t in tails)


def _forty():
    out = {}
    for i in range(40):
        ls = [
            _lesson(f"t{i:02}x", topic=f"topic{i:02}"),
            _lesson(f"t{i:02}y", topic=f"topic{i:02}"),
        ]
        out[f"topic{i:02}"] = ls
    return out


def _digest_of(groups, heading="h" * 80):
    return {"topics": {t: _full(ls, t, heading)["topics"][t] for t, ls in groups.items()}}


def test_index_stays_within_its_limit():
    groups = _forty()
    left = rules.Choice(left=[(m, rules.OVER) for ls in groups.values() for m in ls])
    got = rules.index_lines(left, digest=_digest_of(groups), topics=groups)
    assert (
        len("\n".join(got)) <= rules.INDEX_LIMIT
        and got[-1].startswith("- and ")
        and got[-1].endswith(" topics")
    )
    named = sum(2 for x in got[1:-1])
    assert named + int(got[-1].split()[2]) == INDEX_TOPICS


def test_digest_lines_stay_within_the_limit_of_lesson_lines():
    ls = [dataclasses.replace(_lesson(f"l{i:02}"), short=pad("Rule", 60)) for i in range(40)]
    choice = rules.Choice(
        loaded=ls[:30]
    )  # the slack left under the limit lets about ten lines grow by 60 characters
    texts = {m.handle: pad("Digest", 120) for m in ls}
    got = rules.block(choice, "digest", digest=_full(ls, texts=texts), topics={"a": ls})
    printed = got[2:]
    assert sum(len(x) + 1 for x in printed) <= rules.RULES_LIMIT
    digested = [x.startswith("- Digest") for x in printed]
    assert digested[0] and not digested[-1] and digested == sorted(digested, reverse=True)
    assert printed[-1] == rules.line(choice.loaded[-1])


def test_headings_stay_within_their_limit():
    groups = {
        f"topic{i:02}": [
            _lesson(f"t{i:02}x", topic=f"topic{i:02}"),
            _lesson(f"t{i:02}y", topic=f"topic{i:02}"),
        ]
        for i in range(30)
    }
    choice = rules.Choice(loaded=[m for ls in groups.values() for m in ls])
    got = rules.block(choice, "digest", digest=_digest_of(groups), topics=groups)
    heads = [x for x in got if x.endswith("h" * 80)]
    assert (
        sum(HEADING_WIDTH for _ in heads) == HEADINGS_TOTAL
        and len(heads) == rules.HEADINGS_LIMIT // 80
    )
    assert [x for x in got if x.endswith(":")] == [f"topic{i:02}:" for i in range(10, 30)]


# the commands

K = "0123456789ab"


def _store(tmp_path, monkeypatch, n=2, topic="a"):
    folder = tmp_path / "gmem"
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    monkeypatch.setenv("MEM_PROJECT", str(proj))
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("MEM_RULES_LAYOUT", raising=False)
    for i in range(n):
        assert (
            mem.main([
                "remember",
                "--global",
                "--kind",
                "lesson",
                "--claim",
                f"Lesson {i}.",
                "--origin",
                "transcript",
                "--reach",
                "general",
                "--short",
                f"Rule {i}.",
                "--topic",
                topic,
                "--weight",
                "light",
                "--source",
                f"session a project {K}",
                "--source",
                f"session b project {'ba9876543210'}",
            ])
            == 0
        )
    for m in records.load_memories(folder, "global"):
        if m.triage == "pending":
            assert mem.main(["triage", "accept", m.handle]) == 0
        assert mem.main(["confirm", f"m:{m.handle}", "--global", "--by-owner"]) == 0
    return folder, proj, tmp_path / "data"


def _write_digest(folder, data):
    ls = records.load_memories(folder, "global")
    digest_lessons.write(data, _full(ls, heading="when doing x"))


def _run(capsys, *argv):
    capsys.readouterr()
    assert mem.main(list(argv)) == 0
    return capsys.readouterr().out


def test_rules_command_and_session_start_take_the_digest_layout(tmp_path, monkeypatch, capsys):
    folder, _, data = _store(tmp_path, monkeypatch)
    before = _run(capsys, "session-index")
    _write_digest(folder, data)
    assert "a: when doing x\n- text " in _run(capsys, "rules", "--layout", "digest")
    assert (
        _run(capsys, "session-index") == before
    )  # unset: no heading anywhere, and nothing is left out
    monkeypatch.setenv("MEM_RULES_LAYOUT", "digest")
    assert "a: when doing x\n- text " in _run(capsys, "session-index")
    monkeypatch.setenv("MEM_RULES_LAYOUT", "grouped")
    assert "a:\n- Rule" in _run(capsys, "session-index")


def test_a_broken_digest_file_leaves_the_grouped_block(tmp_path, monkeypatch, capsys):
    _, _, data = _store(tmp_path, monkeypatch)
    monkeypatch.setenv("MEM_RULES_LAYOUT", "grouped")
    grouped = _run(capsys, "session-index")
    data.mkdir(parents=True, exist_ok=True)
    (data / digest_lessons.FILE).write_text("{")
    monkeypatch.setenv("MEM_RULES_LAYOUT", "digest")
    assert _run(capsys, "session-index") == grouped
    monkeypatch.setattr(digest_lessons, "topics_of", lambda *a: 1 / 0)
    assert _run(capsys, "session-index") == grouped


def test_the_hooks_pass_the_digest_value(tmp_path):
    home, store, proj, data = (
        tmp_path / "home",
        tmp_path / "store",
        tmp_path / "work" / "proj",
        tmp_path / "data",
    )
    for d in (home, store, proj):
        d.mkdir(parents=True)
    (store / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(proj), "init", "-q"], check=True)
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "MEM_STORE": str(store),
        "MEM_DATA": str(data),
    }
    for i in range(2):
        r = subprocess.run(
            [
                str(PLUGIN / "bin" / "mem"),
                "remember",
                "--global",
                "--kind",
                "lesson",
                "--claim",
                f"Hook lesson {i}.",
                "--origin",
                "transcript",
                "--reach",
                "general",
                "--short",
                f"Hook rule {i}.",
                "--topic",
                "a",
                "--source",
                f"session a project {K}",
                "--source",
                "session b project ba9876543210",
            ],
            cwd=proj,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r.returncode == 0, r.stderr
    lessons = records.load_memories(store / "memories", "global")
    for m in lessons:
        subprocess.run(
            [str(PLUGIN / "bin" / "mem"), "confirm", f"m:{m.handle}", "--global", "--by-owner"],
            cwd=proj,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
    digest_lessons.write(data, _full(lessons, heading="when doing x"))
    run = lambda layout: subprocess.run(
        [str(PLUGIN / "hooks" / "session-index.sh")],
        input=json.dumps({"cwd": str(proj), "source": "startup"}),
        env={**env, "CLAUDE_PLUGIN_OPTION_RULES_LAYOUT": layout},
        capture_output=True,
        text=True,
        check=False,
    )
    assert "a: when doing x\n- text " in run("digest").stdout
    assert "a:\n- Hook rule" in run("grouped").stdout
    envfile = tmp_path / "envfile"
    envfile.write_text("")
    done = subprocess.run(
        [str(PLUGIN / "hooks" / "session-env.sh")],
        env={
            **env,
            "CLAUDE_ENV_FILE": str(envfile),
            "CLAUDE_PLUGIN_OPTION_RULES_LAYOUT": "digest",
            "XDG_CONFIG_HOME": str(tmp_path / "c"),
            "XDG_DATA_HOME": str(tmp_path / "d"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert "export MEM_RULES_LAYOUT=digest" in envfile.read_text().splitlines()


def test_session_start_text_stays_printable(tmp_path, monkeypatch, capsys):
    """As many lessons as load (the longest short forms) and many more left out, a full digest and a full index."""
    folder, _proj, data = _store(tmp_path, monkeypatch, n=0)
    n = 0
    for t in range(75):
        for _ in range(2):
            n += 1
            assert (
                mem.main([
                    "remember",
                    "--global",
                    "--kind",
                    "lesson",
                    "--claim",
                    f"Claim {n}.",
                    "--origin",
                    "transcript",
                    "--reach",
                    "general",
                    "--short",
                    pad(f"Rule {n}", 103),
                    "--topic",
                    f"topic{t:02}",
                    "--source",
                    f"session a project {K}",
                    "--source",
                    "session b project ba9876543210",
                ])
                == 0
            )
    for m in records.load_memories(folder, "global"):
        if m.triage == "pending":
            assert mem.main(["triage", "accept", m.handle]) == 0
        assert mem.main(["confirm", f"m:{m.handle}", "--global", "--by-owner"]) == 0
    groups = digest_lessons.topics_of(records.load_memories(folder, "global"), TODAY)
    full = {
        "topics": {
            t: _full(ls, t, "h" * 80, {m.handle: pad("Digest", 120) for m in ls})["topics"][t]
            for t, ls in groups.items()
        }
    }
    digest_lessons.write(data, full)
    monkeypatch.setenv("MEM_RULES_LAYOUT", "digest")
    text = _run(capsys, "session-index")
    assert "mem rules --more" in text and "- and " in text and "h" * 80 in text
    assert len(text) < TEXT_LIMIT
