"""`mem synthesis integrate`: rows that join knowledge notes to a part, applied as one logged, undoable group."""

from __future__ import annotations

import hashlib
import json

import mem
import pytest
from commands import integrate as integrate_command
from integrate_store import store_with_part  # ruff: ignore[unused-import]  (a fixture)
from syntheses import units

EXISTING_TARGET = "../knowledge/computing/existing-note.md"
NEW_TARGET = "../knowledge/computing/n-new.md"
DUP_TARGET = "../knowledge/computing/n-dup.md"
USAGE_EXIT = 2
ALPHA_UNITS = 2
NEW_CLAIM = "Rust moves values by default."
DIGEST_LENGTH = 10


def row(note: str, store, action: str = "append", fp: str | None = None) -> str:
    return f"{note} | s:alpha#basics | {action} | {fp or store.fingerprint()}"


def test_append_row_appends_claim_word_for_word_with_reference(store_with_part):
    store = store_with_part
    code, out, err = store.integrate(row("n-new", store))
    assert (code, err) == (0, "")
    assert "applied\tn-new\ts:alpha#basics\tappend" in out.splitlines()
    new = store.section()
    last = units.units(new)[0][-1]
    assert last.plain == NEW_CLAIM and last.refs == [NEW_TARGET]
    assert store.meta("n-new")["part_of"] == "alpha#basics"
    assert units.is_current(store.meta("n-new")["part_of_hash"], new, NEW_TARGET)
    assert store.mem("check") == (0, "", "")


def test_unit_row_adds_reference_only(store_with_part):
    store = store_with_part
    code, out, _ = store.integrate(row("n-dup", store, "unit 2"))
    assert code == 0 and "applied\tn-dup\ts:alpha#basics\tunit 2" in out.splitlines()
    found = units.units(store.section())[0]
    assert len(found) == ALPHA_UNITS and DUP_TARGET in found[1].refs
    assert units.is_current(store.meta("n-dup")["part_of_hash"], store.section(), DUP_TARGET)


def test_summary_line(store_with_part):
    store = store_with_part
    _, out, _ = store.integrate(
        row("n-new", store), row("n-dup", store, "unit 2"), row("nothing", store)
    )
    lines = out.splitlines()
    assert "refused\tnothing\tno such note" in lines
    assert lines[-2] == "s:alpha: appended 1, referenced 1, refused 1"
    assert lines[-1].startswith("group\t")


def test_member_cited_by_unchanged_unit_stays_current(store_with_part):
    store = store_with_part
    before = store.meta("existing-note")["part_of_hash"]
    assert before.startswith("u:")
    store.integrate(row("n-new", store))
    assert store.meta("existing-note")["part_of_hash"] == before
    assert units.is_current(before, store.section(), EXISTING_TARGET)


def test_member_current_by_whole_part_stamp_is_restamped(store_with_part):
    store = store_with_part
    store.new_note("plain-member", "Plain members are stamped by the whole part.")
    assert store.mem("synthesis", "attach", "plain-member", "s:alpha#basics")[0] == 0
    plain = "../knowledge/computing/plain-member.md"
    assert store.meta("plain-member")["part_of_hash"] == units.fingerprint(store.section())
    store.integrate(row("n-new", store))
    assert units.is_current(store.meta("plain-member")["part_of_hash"], store.section(), plain)


def test_member_stale_before_stays_stale(store_with_part):
    store = store_with_part
    path = store.note_path("existing-note")
    text = path.read_text(encoding="utf-8")
    stale = store.meta("existing-note")["part_of_hash"]
    path.write_text(text.replace(stale, "u:0000000000"), encoding="utf-8")
    store.integrate(row("n-new", store))
    assert store.meta("existing-note")["part_of_hash"] == "u:0000000000"


def test_changed_part_refuses_row(store_with_part):
    store = store_with_part
    code, out, _ = store.integrate("n-new | s:alpha#basics | append | 0000000000")
    assert code == 0
    assert "refused\tn-new\tpart changed since it was read" in out.splitlines()
    assert "part_of" not in store.meta("n-new")
    assert not any(x.startswith("group\t") for x in out.splitlines())


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("part_of: alpha#basics", "already part of a synthesis"),
        ("superseded_by: n-dup", "superseded"),
        (
            "disputed:\n  - {date: 2026-01-01, fact: x, source: 'https://e.org', quote: q}",
            "disputed",
        ),
    ],
)
def test_note_state_refused(store_with_part, state, reason):
    store = store_with_part
    store.edit_meta("n-new", state)
    before = store.note_path("n-new").read_bytes()
    code, out, _ = store.integrate(row("n-new", store))
    assert code == 0 and f"refused\tn-new\t{reason}" in out.splitlines()
    assert store.note_path("n-new").read_bytes() == before


def test_not_a_knowledge_note_refused(store_with_part):
    store = store_with_part
    code, out, _ = store.integrate(row("2017-vaswani-attention", store))
    assert code == 0
    assert "refused\t2017-vaswani-attention\tnot a knowledge note" in out.splitlines()


def test_no_such_unit_refused(store_with_part):
    store = store_with_part
    _, out, _ = store.integrate(row("n-dup", store, "unit 9"))
    assert "refused\tn-dup\tno such unit 9" in out.splitlines()


def test_unit_numbers_above_the_original_count_are_refused_after_an_append(store_with_part):
    store = store_with_part
    _, out, _ = store.integrate(row("n-new", store), row("n-dup", store, "unit 3"))
    assert "refused\tn-dup\tno such unit 3" in out.splitlines()


def test_secret_claim_refused(store_with_part):
    store = store_with_part
    store.new_note("n-secret", "Placeholder claim.")
    store.set_line("n-secret", "claim", "The password = hunter2hunter2 for the bucket.")
    before = store.snapshot()
    _, out, _ = store.integrate(row("n-secret", store))
    assert "refused\tn-secret\tsecret in the claim" in out.splitlines()
    assert store.snapshot() == before


def test_forbidden_term_refused(store_with_part):
    store = store_with_part
    assert mem.main(["terms", "add", "Zebracorp"]) == 0
    store.capsys.readouterr()
    store.new_note("n-term", "Placeholder claim.")
    store.set_line("n-term", "claim", "Zebracorp shipped the borrow checker.")
    before = store.snapshot()
    _, out, _ = store.integrate(row("n-term", store))
    assert "refused\tn-term\tforbidden term in the claim" in out.splitlines()
    assert store.snapshot() == before


def test_claim_ending_with_colon_refused(store_with_part):
    store = store_with_part
    store.new_note("n-colon", "These are the rules:")
    _, out, _ = store.integrate(row("n-colon", store))
    assert "refused\tn-colon\tclaim ends with a colon" in out.splitlines()


def test_rows_apply_as_one_group_and_restore_returns_bytes(store_with_part):
    store = store_with_part
    before = store.snapshot()
    code, out, _ = store.integrate(row("n-new", store), row("n-dup", store, "unit 2"))
    assert code == 0 and store.snapshot() != before
    group = {x["group"] for x in store.log_lines() if x["action"] == "integrate"}
    assert len(group) == 1
    assert f"group\t{group.pop()}" in out.splitlines()
    assert store.mem("restore", "s:alpha")[0] == 0
    assert store.snapshot() == before


def test_changed_file_between_read_and_write_rolls_back(store_with_part, monkeypatch):
    store = store_with_part
    original = integrate_command.integrate_changes

    def build_then_edit(*args, **kwargs):
        outcome = original(*args, **kwargs)
        path = store.note_path("n-dup")
        path.write_text(path.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
        return outcome

    monkeypatch.setattr(integrate_command, "integrate_changes", build_then_edit)
    log_before = store.log_lines()
    code, _, err = store.integrate(row("n-new", store), row("n-dup", store, "unit 2"))
    assert code == USAGE_EXIT and "changed since it was read" in err
    assert "part_of" not in store.meta("n-new")
    assert NEW_CLAIM not in store.section()
    assert store.log_lines() == log_before


def test_two_rows_same_part_use_original_fingerprint_and_unit_numbers(store_with_part):
    store = store_with_part
    fp = store.fingerprint()
    _, out, _ = store.integrate(row("n-new", store, fp=fp), row("n-dup", store, "unit 2", fp=fp))
    lines = out.splitlines()
    assert "applied\tn-new\ts:alpha#basics\tappend" in lines
    assert "applied\tn-dup\ts:alpha#basics\tunit 2" in lines
    found = units.units(store.section())[0]
    assert found[-1].plain == NEW_CLAIM and DUP_TARGET in found[1].refs


def test_malformed_row_is_a_usage_error_and_writes_nothing(store_with_part):
    store = store_with_part
    before = store.snapshot()
    code, _, err = store.integrate("n-new | s:alpha | append")
    assert code == USAGE_EXIT and "line 1" in err
    assert store.snapshot() == before


def test_candidates_json(store_with_part):
    store = store_with_part
    data = store.candidates()
    assert [n["handle"] for n in data[0]["notes"]] == ["n-dup", "n-new"]
    assert data[0]["synthesis"] == "alpha"
    part = data[0]["parts"][0]
    assert part["section"] == "basics" and part["fingerprint"] == store.fingerprint()
    note = data[0]["notes"][1]
    assert note["claim"] == NEW_CLAIM and len(note["digest"]) == DIGEST_LENGTH


def test_candidates_units_are_the_units_of_the_part(store_with_part):
    store = store_with_part
    part = store.candidates()[0]["parts"][0]
    expected = [{"n": u.n, "text": u.text} for u in units.units(store.section())[0]]
    assert part["units"] == expected


def test_candidates_digest_is_the_hash_of_the_note_bytes(store_with_part):
    store = store_with_part
    note = next(n for n in store.candidates()[0]["notes"] if n["handle"] == "n-new")
    data = store.note_path("n-new").read_bytes()
    assert note["digest"] == hashlib.sha256(data).hexdigest()[:10]


def test_candidates_skip_superseded_disputed_attached(store_with_part):
    store = store_with_part
    store.edit_meta("n-new", "superseded_by: n-dup")
    assert [n["handle"] for n in store.candidates()[0]["notes"]] == ["n-dup"]
    store.edit_meta("n-dup", "part_of: alpha#basics")
    assert store.candidates() == []


def test_candidates_skip_disputed(store_with_part):
    store = store_with_part
    store.edit_meta(
        "n-new", "disputed:\n  - {date: 2026-01-01, fact: x, source: 'https://e.org', quote: q}"
    )
    assert [n["handle"] for n in store.candidates()[0]["notes"]] == ["n-dup"]


def test_candidates_note_under_the_first_of_two_syntheses(store_with_part):
    store = store_with_part
    store.set_line("n-new", "topics", ["ml", "algorithms"])
    code = store.mem(
        "synthesis", "new", "--title", "Beta", "--topics", "algorithms", "--slug", "beta",
        "--summary-file", store.write("s2.md", "Other.\n"),
    )[0]  # fmt: skip
    assert code == 0
    data = store.candidates()
    assert [d["synthesis"] for d in data] == ["alpha"]
    assert "n-new" in [n["handle"] for n in data[0]["notes"]]


def test_integrate_prints_group_id(store_with_part):
    store = store_with_part
    _, out, _ = store.integrate(row("n-new", store))
    ids = {x["group"] for x in store.log_lines() if x["action"] == "integrate"}
    assert out.splitlines()[-1] == f"group\t{next(iter(ids))}"


def test_restore_by_handle_after_live_append_does_not_undo_the_group(store_with_part):
    """The hazard Task 7 guards: after integrate, a live append to the part is the newest change of s:alpha, so
    `mem restore s:alpha` undoes that append and leaves the integration in place."""
    store = store_with_part
    store.integrate(row("n-new", store))
    integrated = store.section()
    body = store.write("live.md", "A live sentence follows the integration.\n")
    assert store.mem("synthesis", "append", "s:alpha#basics", "--body-file", body)[0] == 0
    assert store.mem("restore", "s:alpha")[0] == 0
    assert store.section() == integrated
    assert store.meta("n-new")["part_of"] == "alpha#basics"


def test_candidates_output_is_json_only(store_with_part):
    store = store_with_part
    code, out, err = store.mem("synthesis", "integrate", "--candidates")
    assert code == 0 and not err and isinstance(json.loads(out), list)
