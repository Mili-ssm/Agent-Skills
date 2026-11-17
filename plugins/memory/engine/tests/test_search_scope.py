import mem
from conftest import usage_log_path


def run(root, capsys, *argv):
    code = mem.main(["--root", str(root), "search", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def kinds(out):
    return {line.split("/")[0] for line in out.splitlines() if "/" in line.split("\t")[0]}


HINT = "mem: more in sources and syntheses: repeat with --deep.\n"


def test_default_ranks_knowledge_notes_only(hub_root, capsys):
    _, out, _ = run(hub_root, capsys, "attention")
    assert kinds(out) == {"knowledge"}


def test_default_equals_an_explicit_knowledge_type(hub_root, capsys):
    assert run(hub_root, capsys, "attention")[1] == run(hub_root, capsys, "attention", "--type", "knowledge")[1]


def test_deep_equals_the_previous_default_ranking_of_all_types(hub_root, capsys):
    expected = "".join(f"{rel}\t{score:.2f}\t{title}\n" for rel, score, title in mem.search(hub_root, "attention"))
    _, out, err = run(hub_root, capsys, "attention", "--deep")
    assert out == expected and {"literature", "knowledge"} <= kinds(out) and err == ""


def test_explicit_type_needs_no_deep_and_prints_no_hint(hub_root, capsys):
    _, out, err = run(hub_root, capsys, "attention", "--type", "literature")
    assert kinds(out) == {"literature"} and err == ""


def test_hint_when_the_default_prints_fewer_than_three_and_deep_would_print_more(hub_root, capsys):
    _, out, err = run(hub_root, capsys, "evaluating")  # only an investigation matches
    assert out == "" and err == "no matches\n" + HINT
    _, _, err = run(hub_root, capsys, "attention")  # one knowledge note, one source: more in deep
    assert err == HINT


def test_no_hint_with_deep_or_when_nothing_more_exists(hub_root, capsys):
    assert run(hub_root, capsys, "evaluating", "--deep")[2] == ""
    assert HINT not in run(hub_root, capsys, "zzzunknown")[2]


def test_links_in_the_default_search_stay_among_knowledge_notes(hub_root, capsys):
    _, out, _ = run(hub_root, capsys, "attention", "--links")
    assert kinds(out) == {"knowledge"}


def test_also_applies_the_default_to_every_query(hub_root, capsys):
    _, out, _ = run(hub_root, capsys, "attention", "--also", "vaswani")
    assert "== attention ==" in out and "literature/" not in out


def test_usage_log_records_deep(hub_root, capsys):
    import json
    run(hub_root, capsys, "attention", "--deep")
    run(hub_root, capsys, "attention")
    first, second = [json.loads(line) for line in usage_log_path().read_text().splitlines()]
    assert first["deep"] is True and "deep" not in second
