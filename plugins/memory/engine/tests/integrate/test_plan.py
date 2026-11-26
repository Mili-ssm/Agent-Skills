from integrate.answers import answer_lines
from integrate.plan import Offered, PartInfo, placement_rows
from integrate.rows import Row

FP = "ab12cd34ef"
TARGET = "s:alpha#basics"
UNITS = 2


def _offered(*notes: str, units: int = UNITS) -> Offered:
    return Offered(frozenset(notes or ("n1",)), {TARGET: PartInfo(FP, units)})


def test_malformed_answer_plans_nothing():
    assert answer_lines("I think n1 belongs to basics.") is None
    assert answer_lines(f"n1 | {TARGET} | append | {FP}\nand also this") is None
    assert answer_lines("") is None


def test_answer_lines_tolerates_fences_and_none():
    assert answer_lines("```\nnone\n```") == ["none"]


def test_placement_rows_drop_unoffered_unit():
    rows, refused = placement_rows([f"n1 | {TARGET} | unit 9 | {FP}"], _offered())
    assert rows == [] and refused == ["n1: no such unit 9"]


def test_placement_rows_drop_unit_one_past_the_end():
    rows, refused = placement_rows([f"n1 | {TARGET} | unit {UNITS + 1} | {FP}"], _offered())
    assert rows == [] and refused == [f"n1: no such unit {UNITS + 1}"]


def test_placement_rows_drop_unit_zero_as_malformed():
    rows, refused = placement_rows([f"n1 | {TARGET} | unit 0 | {FP}"], _offered())
    assert rows == [] and refused == ["malformed row"]


def test_placement_rows_drop_a_row_parse_rows_rejects():
    rows, refused = placement_rows([f"n1 | {TARGET} | append | {FP} please"], _offered())
    assert rows == [] and refused == ["malformed row"]


def test_part_not_offered_is_distinct_from_unit_range():
    rows, refused = placement_rows([f"n1 | s:beta#other | unit 1 | {FP}"], _offered())
    assert rows == [] and refused == ["n1: part not offered"]


def test_offered_notes_are_matched_whole_not_as_substrings():
    assert isinstance(_offered("n1").notes, frozenset)
    rows, refused = placement_rows([f"n | {TARGET} | append | {FP}"], _offered("n1"))
    assert rows == [] and refused == ["n: not offered"]


def test_none_with_rows_is_a_contradiction():
    assert answer_lines(f"none\nn1 | {TARGET} | append | {FP}") is None
    assert answer_lines(f"n1 | {TARGET} | append | {FP}\nnone") is None


def test_none_alone_is_valid():
    assert answer_lines("none") == ["none"]
    assert answer_lines("none\nnone") == ["none", "none"]


def test_fence_glued_row_refuses_the_whole_answer():
    assert answer_lines(f"```n1 | {TARGET} | append | {FP}") is None
    assert answer_lines(f"```\nn1 | {TARGET} | append | {FP}\n```x y") is None


def test_row_with_trailing_prose_refuses_the_answer():
    assert answer_lines(f"n1 | {TARGET} | append | {FP} because it fits") is None


def test_crlf_answer_is_accepted():
    row = f"n1 | {TARGET} | append | {FP}"
    assert answer_lines(f"```\r\n{row}\r\n```\r\n") == [row]


def test_language_tagged_fence_is_accepted():
    row = f"n1 | {TARGET} | append | {FP}"
    assert answer_lines(f"```text\n{row}\n```") == [row]


def test_placement_row_with_dash_note_is_refused():
    rows, refused = placement_rows(
        [f"--owner-approved | {TARGET} | append | {FP}"], _offered("--owner-approved")
    )
    assert rows == [] and refused == ["malformed row"]


def test_note_not_offered():
    rows, refused = placement_rows([f"n9 | {TARGET} | append | {FP}"], _offered())
    assert rows == [] and refused == ["n9: not offered"]


def test_part_not_offered():
    rows, refused = placement_rows([f"n1 | s:beta#other | append | {FP}"], _offered())
    assert rows == [] and refused == ["n1: part not offered"]


def test_part_changed_since_read():
    rows, refused = placement_rows([f"n1 | {TARGET} | append | 0123456789"], _offered())
    assert rows == [] and refused == ["n1: part changed since it was read"]


def test_note_placed_twice():
    lines = [f"n1 | {TARGET} | append | {FP}", f"n1 | {TARGET} | unit 1 | {FP}"]
    rows, refused = placement_rows(lines, _offered())
    assert rows == [Row("n1", TARGET, "append", None, FP)]
    assert refused == ["n1: placed twice"]


def test_none_and_comments_produce_nothing():
    assert placement_rows(["none", "# nothing fits"], _offered()) == ([], [])


def test_valid_unit_row_is_kept():
    rows, refused = placement_rows([f"n1 | {TARGET} | unit 2 | {FP}"], _offered())
    assert rows == [Row("n1", TARGET, "unit", 2, FP)] and refused == []


def test_fenced_answer_end_to_end():
    lines = answer_lines(f"```\nn1 | {TARGET} | append | {FP}\nn2 | {TARGET} | unit 5 | {FP}\n```")
    assert lines is not None
    rows, refused = placement_rows(lines, _offered("n1", "n2"))
    assert rows == [Row("n1", TARGET, "append", None, FP)]
    assert refused == ["n2: no such unit 5"]
