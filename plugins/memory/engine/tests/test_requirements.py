import mem

from test_find_new import write_note

HEADER = ("# Requirements\n\n| ID | Requirement |\n| --- | --- |\n| I-1 | Intent one. |\n"
          "| I-2 | Intent two. |\n\n"
          "| ID | Requirement | Serves | Rests on | Revisit when | Review by |\n"
          "| --- | --- | --- | --- | --- | --- |\n")


def requirements(root, rows):
    write_note(root, "docs/requirements.md", HEADER + rows)


def messages(root):
    return [p.message for p in mem.check(root) if p.path == "docs/requirements.md"]


def test_review_lists_only_due_rows_in_file_order(hub_root, capsys):
    requirements(hub_root, "| C-1 | Later `a, b` thing. | I-1 | x | y | 2027-01-01 |\n"
                           "| C-2 | Due on the day. | I-1, I-2 | x | y | 2026-12-01 |\n"
                           "| C-3 | Long overdue. | I-2 | x | y | 2026-01-15 |\n")
    assert mem.main(["--root", str(hub_root), "review", "--today", "2026-12-01"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "docs/requirements.md:11: C-2 due for review since 2026-12-01: Due on the day.",
        "docs/requirements.md:12: C-3 due for review since 2026-01-15: Long overdue."]
    assert mem.main(["--root", str(hub_root), "review", "--today", "2025-01-01"]) == 0
    assert capsys.readouterr().out == ""


def test_pipe_inside_code_span_does_not_split_cells(hub_root, capsys):
    requirements(hub_root, "| C-1 | Use `a|b` here. | I-1 | `x` | y | 2026-01-01 |\n")
    assert messages(hub_root) == []
    mem.main(["--root", str(hub_root), "review", "--today", "2026-06-01"])
    assert "C-1 due for review since 2026-01-01: Use `a|b` here." in capsys.readouterr().out


def test_requirements_file_absent_is_silent(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "review"]) == 0
    assert capsys.readouterr().out == ""
    assert mem.check(hub_root) == []


def test_valid_requirements_pass(hub_root):
    requirements(hub_root, "| C-1 | Fine. | I-1, I-2 | x | y | 2027-01-01 |\n")
    assert mem.check(hub_root) == []


def test_rule_12_wrong_cell_count(hub_root):
    requirements(hub_root, "| C-1 | Short. | I-1 | x | 2027-01-01 |\n")
    assert any("exactly 6" in m for m in messages(hub_root))


def test_rule_12_bad_dates(hub_root):
    requirements(hub_root, "| C-1 | A. | I-1 | x | y | 2027-13-01 |\n| C-2 | B. | I-1 | x | y | soon |\n")
    assert sum("invalid 'Review by' date" in m for m in messages(hub_root)) == 2


def test_rule_12_duplicate_ids(hub_root):
    requirements(hub_root, "| C-1 | A. | I-1 | x | y | 2027-01-01 |\n| C-1 | B. | I-1 | x | y | 2027-01-01 |\n"
                           "| I-2 | Again. |\n")
    found = messages(hub_root)
    assert sum("duplicate id" in m for m in found) == 2


def test_rule_12_unknown_intent(hub_root):
    requirements(hub_root, "| C-1 | A. | I-1, I-9 | x | y | 2027-01-01 |\n")
    problems = [p for p in mem.check(hub_root) if p.path == "docs/requirements.md"]
    assert len(problems) == 1 and "'I-9'" in problems[0].message and problems[0].line == 10


def test_review_dates_never_fail_check(hub_root):
    requirements(hub_root, "| C-1 | Overdue. | I-1 | x | y | 2000-01-01 |\n")
    assert mem.check(hub_root) == []
