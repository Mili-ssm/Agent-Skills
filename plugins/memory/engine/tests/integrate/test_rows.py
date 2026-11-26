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


def test_parse_rows_wants_exactly_ten_hex_characters():
    rows, bad = parse_rows(
        "n | s:a#b | append | ab12cd34\nn | s:a#b | append | ab12cd34ef5\nn | s:a#b | append | AB12CD34EF\n"
    )
    assert rows == [] and len(bad) == MALFORMED


def test_parse_rows_reports_a_dash_note_as_malformed():
    rows, bad = parse_rows("-n | s:alpha#basics | append | ab12cd34ef\n")
    assert rows == [] and len(bad) == 1


def test_check_claim():
    assert check_claim("Rust moves values by default.", {}) is None
    assert check_claim("See this:", {}) == "claim ends with a colon"
    assert check_claim("  ", {}) == "claim is empty"


def test_check_claim_refuses_a_secret():
    assert check_claim("Set db_password = correcthorse now.", {}) == "secret in the claim"


def test_check_claim_refuses_a_forbidden_term(tmp_path):
    terms = tmp_path / "agent-memory" / "forbidden-terms"
    terms.parent.mkdir()
    terms.write_text("acme\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert check_claim("Acme moves values.", env) == "forbidden term in the claim"


def test_check_claim_refuses_brackets_and_multi_unit_claims():
    assert check_claim("Use [x] here.", {}) == "claim holds brackets"
    assert check_claim("One. Two.", {}) == "claim is not one sentence"
