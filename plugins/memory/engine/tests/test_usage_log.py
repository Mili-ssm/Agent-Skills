import json

import mem
from conftest import usage_log_path

from test_find_new import write_note
from test_show import NOTE, REL


def entries(root):
    path = usage_log_path()
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_search_logs_one_line(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "search", "attention", "--type", "knowledge"]) == 0
    printed = [line.split("\t")[0] for line in capsys.readouterr().out.splitlines()]
    (entry,) = entries(hub_root)
    assert entry["cmd"] == "search" and entry["query"] == "attention"
    assert entry["t"].endswith("Z") and len(entry["t"]) == 20
    assert entry["limit"] == 10 and entry["filters"] == {"type": "knowledge"}
    assert entry["results"] == printed and printed
    assert "detail" in entry


def test_search_without_matches_logs_empty_results(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "search", "zzzqqq"]) == 0
    assert entries(hub_root)[0]["results"] == []


def test_show_logs_paths_and_sections(hub_root, capsys):
    write_note(hub_root, REL, NOTE)
    assert mem.main(["--root", str(hub_root), "show", REL, "--section", "Claim"]) == 0
    (entry,) = entries(hub_root)
    assert entry["cmd"] == "show" and entry["paths"] == [REL]
    assert entry["sections"] == ["Claim"] and entry["outline"] is False


def test_failed_show_logs_nothing(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "show", "nope.md"]) == 1
    assert entries(hub_root) == []


def test_opt_out(hub_root, monkeypatch):
    monkeypatch.setenv("MEM_USAGE_LOG", "0")
    mem.main(["--root", str(hub_root), "search", "attention"])
    assert not usage_log_path().exists()


def test_unwritable_usage_path_is_silent(hub_root, capsys):
    mem.main(["--root", str(hub_root), "search", "attention"])
    expected = capsys.readouterr()
    usage_log_path().parent.rename(usage_log_path().parent.with_name("moved"))
    usage_log_path().parent.write_text("not a folder")
    assert mem.main(["--root", str(hub_root), "search", "attention"]) == 0
    got = capsys.readouterr()
    assert (got.out, got.err) == (expected.out, expected.err)


def test_search_eval_and_new_do_not_log(hub_root, capsys):
    mem.main(["--root", str(hub_root), "search-eval"])
    mem.main(["--root", str(hub_root), "new", "knowledge", "--slug", "zebra-facts", "--claim",
              "Zebra facts hold", "--topics", "computing", "--confidence", "low",
              "--level", "beginner", "--origin", "experience"])
    assert entries(hub_root) == []


def test_stats_counts_entries(hub_root, capsys):
    mem.main(["--root", str(hub_root), "search", "attention"])
    capsys.readouterr()
    mem.main(["--root", str(hub_root), "stats"])
    assert "usage log entries: 1" in capsys.readouterr().out.splitlines()


def test_query_that_is_not_valid_utf8_is_logged_on_one_line(hub_root, capsys):
    odd = "attention\udcff\u2028x"  # a surrogate from undecodable argv, and a line separator
    assert mem.main(["--root", str(hub_root), "search", odd]) == 0
    assert capsys.readouterr().err == ""
    (entry,) = entries(hub_root)
    assert entry["query"] == odd


def test_show_logs_a_repeated_path_once(hub_root, capsys):
    write_note(hub_root, REL, NOTE)
    assert mem.main(["--root", str(hub_root), "show", REL, "./" + REL]) == 0
    assert entries(hub_root)[0]["paths"] == [REL]


def test_related_does_not_log(hub_root, capsys):
    write_note(hub_root, REL, NOTE)
    assert mem.main(["--root", str(hub_root), "related", REL]) == 0
    assert entries(hub_root) == []
