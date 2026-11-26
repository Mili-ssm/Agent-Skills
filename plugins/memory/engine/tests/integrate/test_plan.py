from integrate.answers import answer_lines
from integrate.plan import Offered, PartInfo, placement_rows
from integrate.rows import Row

FP = "ab12cd34ef"
TARGET = "s:alpha#basics"
UNITS = 2


def _offered(*notes: str, units: int = UNITS) -> Offered:
    return Offered(notes or ("n1",), {TARGET: PartInfo(FP, units)})


def test_malformed_answer_plans_nothing():
    assert answer_lines("I think n1 belongs to basics.") is None
    assert answer_lines(f"n1 | {TARGET} | append | {FP}\nand also this") is None
    assert answer_lines("") is None


def test_answer_lines_tolerates_fences_and_none():
    assert answer_lines("```\nnone\n```") == ["none"]


def test_placement_rows_drop_unoffered_part_or_unit():
    rows, refused = placement_rows([f"n1 | {TARGET} | unit 9 | {FP}"], _offered())
    assert rows == [] and refused == ["n1: no such unit 9"]


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
