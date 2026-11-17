from conftest import usage_log_path
import json

import mem

from test_search_stats import add


def run(root, capsys, *args):
    assert mem.main(["--root", str(root), *args]) == 0
    return capsys.readouterr().out.splitlines()


def linking(root, name, claim, body, *targets):
    return add(root, name, claim, body + " " + " ".join(f"[x](../../{t})" for t in targets))


def first_column(lines):
    return [line.split("\t")[0] for line in lines]


def test_without_links_output_is_unchanged(hub_root, capsys):
    top = add(hub_root, "top", "Zebra crossings", "Zebra.")
    quiet = add(hub_root, "quiet", "Other", "Nothing.")
    linking(hub_root, "third", "Third", "Zebra.", quiet)
    score = dict((r, s) for r, s, _ in mem.search(hub_root, "zebra"))[top]
    out = run(hub_root, capsys, "search", "zebra", "--limit", "2")
    third = "knowledge/computing/third.md"
    other = {r: s for r, s, _ in mem.search(hub_root, "zebra")}[third]
    assert out == [f"{top}\t{score:.2f}\tZebra crossings", f"{third}\t{other:.2f}\tThird"]


def test_neighbour_follows_separator_with_zero_score(hub_root, capsys):
    quiet = add(hub_root, "quiet", "Other claim", "Nothing relevant.")
    top = linking(hub_root, "top", "Zebra crossings", "Zebra.", quiet)
    out = run(hub_root, capsys, "search", "zebra", "--links")
    assert first_column(out) == [top, "-- linked to the results above --", quiet]
    assert out[2] == f"{quiet}\t0.00\tOther claim"


def test_backlink_is_a_neighbour_and_results_are_not_repeated(hub_root, capsys):
    a = add(hub_root, "a", "Zebra a", "Zebra.")
    b = linking(hub_root, "b", "Zebra b", "Zebra.", a)  # both match: already results
    quiet = linking(hub_root, "quiet", "Other claim", "Nothing.", a)  # links to a result
    out = first_column(run(hub_root, capsys, "search", "zebra", "--links", "--detail", "titles"))
    assert sorted(out[:2]) == [a, b] and out[2:] == ["-- linked to the results above --", quiet]


def test_filter_excludes_neighbour_of_another_type(hub_root, capsys):
    lit = "literature/computing/2017-vaswani-attention.md"
    linking(hub_root, "top", "Zebra crossings", "Zebra.", lit)
    assert lit in first_column(run(hub_root, capsys, "search", "zebra", "--links"))
    out = run(hub_root, capsys, "search", "zebra", "--links", "--type", "knowledge")
    assert lit not in first_column(out) and "-- linked to the results above --" not in out


def test_paths_detail_has_no_separator(hub_root, capsys):
    quiet = add(hub_root, "quiet", "Other claim", "Nothing.")
    top = linking(hub_root, "top", "Zebra crossings", "Zebra.", quiet)
    assert run(hub_root, capsys, "search", "zebra", "--links", "--detail", "paths") == [top, quiet]


def test_order_is_seed_score_sum_plus_own_score(hub_root, capsys):
    n_a = add(hub_root, "n-a", "Alpha", "Nothing.")
    n_b = add(hub_root, "n-b", "Beta", "Nothing.")
    n_c = add(hub_root, "n-c", "Gamma", "Zebra.")  # matches the query itself, but ranks below the two seeds
    s1 = linking(hub_root, "s1", "Zebra one", "Zebra.", n_a, n_b, n_c)
    s2 = linking(hub_root, "s2", "Zebra two", "Zebra.", n_b)
    scores = {r: s for r, s, _ in mem.search(hub_root, "zebra", limit=9)}
    expected = {n_a: scores[s1], n_b: scores[s1] + scores[s2], n_c: scores[s1] + scores[n_c]}
    assert len(set(expected.values())) == 3 and scores[n_c] > 0
    out = run(hub_root, capsys, "search", "zebra", "--links", "--limit", "2", "--detail", "paths")
    assert out[:2] == sorted([s1, s2], key=lambda r: -scores[r]) and out[2:] == sorted(expected, key=lambda r: -expected[r])
    assert out[2] != n_a  # alphabetical order would start with it


def test_usage_log_fields(hub_root, capsys):
    quiet = add(hub_root, "quiet", "Other claim", "Nothing.")
    linking(hub_root, "top", "Zebra crossings", "Zebra.", quiet)
    run(hub_root, capsys, "search", "zebra", "--links")
    run(hub_root, capsys, "search", "zebra")
    with_links, plain = [json.loads(line) for line in usage_log_path().read_text().splitlines()]
    assert with_links["links"] is True and with_links["linked"] == [quiet]
    assert "links" not in plain and "linked" not in plain


def test_only_printed_results_are_seeds(hub_root, capsys):
    """With --limit 1 a note linked only from the second-ranked result is not 'linked to the results above'."""
    of_top = add(hub_root, "of-top", "Other one", "Nothing.")
    of_second = add(hub_root, "of-second", "Other two", "Nothing.")
    top = linking(hub_root, "top", "Zebra zebra crossings", "Zebra zebra.", of_top)
    linking(hub_root, "second", "Second", "Zebra.", of_second)
    out = run(hub_root, capsys, "search", "zebra", "--limit", "1", "--links")
    assert first_column(out) == [top, "-- linked to the results above --", of_top]
