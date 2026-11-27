"""One test per gap of usage_reviewer.py `severities()` that the stage 0 work closed."""

import usage_reviewer as ur

TABLE = "| # | Where | Severity | Doubt |\n|---|---|---|---|\n| 1 | a.py:1 | medium | x |\n"


def test_low_line_starting_with_a_file_name_is_a_finding_not_a_label() -> None:
    """`Makefile:3 — …` and `a.py:12 — …` inside the Low block count as low findings."""
    report = TABLE + "\nLow:\nMakefile:3 — a doubt\na.py:12 — another\nNot checked: tests\n"
    assert ur.severities(report) == {"medium": 1, "low": 2}


def test_left_out_count_is_added_to_the_low_count() -> None:
    """`Left out: K low findings` adds K to the low count."""
    report = TABLE + "\nLow:\nb.py:1 — one\nLeft out: 4 low findings\nNot checked: tests\n"
    assert ur.severities(report) == {"medium": 1, "low": 5}
