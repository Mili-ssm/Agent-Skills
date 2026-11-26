from integrate.rows import Row, check_claim, parse_rows

MALFORMED = 3


def test_parse_rows_append_and_unit():
    rows, bad = parse_rows(
        "n1 | s:alpha#basics | append | ab12cd34ef\nn2 | s:alpha#basics | unit 3 | ab12cd34ef\n# note\n\n"
    )
    assert rows == [
        Row("n1", "s:alpha#basics", "append", None, "ab12cd34ef"),
        Row("n2", "s:alpha#basics", "unit", 3, "ab12cd34ef"),
    ]
    assert bad == []


def test_parse_rows_reports_malformed():
    rows, bad = parse_rows("n1 | s:alpha | append | x\nn1 | s:alpha#basics | unit 0 | ab\nnone\n")
    assert rows == []
    assert len(bad) == MALFORMED


def test_check_claim():
    assert check_claim("Rust moves values by default.", {}) is None
    assert check_claim("See this:", {}) == "claim ends with a colon"
    assert check_claim("  ", {}) == "claim is empty"


def test_check_claim_refuses_brackets_and_multi_unit_claims():
    assert check_claim("Use [x] here.", {}) == "claim holds brackets"
    assert check_claim("One. Two.", {}) == "claim is not one sentence"
