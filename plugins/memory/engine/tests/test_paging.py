import json

import mem
import pytest

from test_search_stats import add


def run(root, capsys, *args, code=0):
    assert mem.main(["--root", str(root), *args]) == code
    captured = capsys.readouterr()
    return captured.out.splitlines(), captured.err


def many(root, n=5):
    return [add(root, f"zebra-{i}", f"Zebra {i}", "Zebra " * (n - i)) for i in range(n)]


def test_find_default_limit_and_footer(hub_root, capsys):
    many(hub_root, 55)
    out, err = run(hub_root, capsys, "find", "--detail", "paths")
    assert len(out) == 50
    assert err == "-- 1-50 of 58; next: --offset 50 --\n"
    out, err = run(hub_root, capsys, "find", "--detail", "paths", "--offset", "50")
    assert len(out) == 8 and err == ""


def test_find_explicit_limit_and_offset(hub_root, capsys):
    many(hub_root)
    out, err = run(hub_root, capsys, "find", "--type", "knowledge", "--limit", "2", "--offset", "1", "--detail", "paths")
    assert len(out) == 2 and err == "-- 2-3 of 6; next: --offset 3 --\n"


def test_search_offset_pages_the_ranking(hub_root, capsys):
    many(hub_root)
    full, _ = run(hub_root, capsys, "search", "zebra", "--detail", "paths")
    first, err1 = run(hub_root, capsys, "search", "zebra", "--limit", "2", "--detail", "paths")
    second, err2 = run(hub_root, capsys, "search", "zebra", "--limit", "2", "--offset", "2", "--detail", "paths")
    last, err3 = run(hub_root, capsys, "search", "zebra", "--limit", "2", "--offset", "4", "--detail", "paths")
    assert first + second + last == full and len(full) == 5
    assert err1 == "-- 1-2 of 5; next: --offset 2 --\n" and err2 == "-- 3-4 of 5; next: --offset 4 --\n"
    assert err3 == ""


def test_search_offset_with_links_is_refused(hub_root):
    with pytest.raises(SystemExit) as exc:
        mem.main(["--root", str(hub_root), "search", "zebra", "--offset", "1", "--links"])
    assert exc.value.code == 2


def test_search_also_headers_and_single_output_unchanged(hub_root, capsys):
    many(hub_root)
    alone, _ = run(hub_root, capsys, "search", "zebra", "--detail", "paths")
    other, _ = run(hub_root, capsys, "search", "attention", "--detail", "paths")
    both, _ = run(hub_root, capsys, "search", "zebra", "--also", "attention", "--detail", "paths")
    assert both == ["== zebra =="] + alone + ["== attention =="] + other


def test_search_also_logs_one_line_per_query(hub_root, capsys, monkeypatch):
    monkeypatch.delenv("HUB_USAGE_LOG", raising=False)
    many(hub_root)
    run(hub_root, capsys, "search", "zebra", "--also", "attention")
    entries = [json.loads(line) for line in (hub_root / mem.USAGE_LOG).read_text().splitlines()]
    assert [e["query"] for e in entries] == ["zebra", "attention"]
    assert all(e["cmd"] == "search" and e["limit"] == 10 for e in entries)


def test_search_also_empty_query_is_a_parser_error(hub_root):
    with pytest.raises(SystemExit) as exc:
        mem.main(["--root", str(hub_root), "search", "zebra", "--also", "!!"])
    assert exc.value.code == 2


def test_check_paths_filter_and_missing_path(hub_root, capsys):
    bad = add(hub_root, "bad", "Bad", "TODO(hub): fill")
    other = add(hub_root, "bad2", "Bad2", "TODO(hub): fill")
    out, _ = run(hub_root, capsys, "check", bad, code=1)
    assert out and all(line.startswith(bad + ":") for line in out)
    out, _ = run(hub_root, capsys, "check", "literature", code=0)
    assert out == []
    out, _ = run(hub_root, capsys, "check", str(hub_root / "knowledge"), code=1)
    assert any(line.startswith(bad) for line in out) and any(line.startswith(other) for line in out)
    _, err = run(hub_root, capsys, "check", "knowledge/nope.md", code=2)
    assert "no such file" in err


def test_stats_orphans_scope(hub_root, capsys):
    add(hub_root, "lonely", "Lonely")
    out, _ = run(hub_root, capsys, "stats", "--orphans")
    assert "knowledge/computing/lonely.md" in out
    out, _ = run(hub_root, capsys, "stats", "--orphans", "knowledge/computing/lonely.md")
    assert out == ["knowledge/computing/lonely.md"]
    out, _ = run(hub_root, capsys, "stats", "--orphans", "literature")
    assert "knowledge/computing/lonely.md" not in out
    run(hub_root, capsys, "stats", "--orphans", "nope", code=2)


def test_offset_past_the_matches_is_said_once(hub_root, capsys):
    many(hub_root)
    for args, total in ((("find", "--type", "knowledge"), 6), (("search", "zebra"), 5)):
        out, err = run(hub_root, capsys, *args, "--offset", "99")
        assert out == [] and err == f"-- offset 99 is past the {total} matches --\n"
