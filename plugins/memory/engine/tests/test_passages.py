from conftest import usage_log_path
import json

import pytest

import mem

LIT = "literature/computing/2017-vaswani-attention.md"
FOLDER = "2017-vaswani-attention"


def source(root, text, name="source.txt"):
    folder = root / ".sources" / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def text_of(n, marks=()):
    """n words, w1..wn, with the word at each 1-based position in `marks` replaced by `zeta`."""
    return " ".join("zeta" if i in marks else f"w{i}" for i in range(1, n + 1))


def run(root, capsys, *args, path=LIT):
    code = mem.main(["--root", str(root), "passages", path, *args])
    return code, capsys.readouterr()


def test_windows_cover_the_text_and_keep_the_last_shorter_one():
    # 23 words, windows of 10 start at 1, 6, 11, 16 (last ends at the text's end) and 21 is not needed
    total, found = mem.passages(text_of(23, {1, 6, 11, 16, 23}), "zeta", count=99, words=10)
    assert total == 23
    assert [(a, b) for a, b, _ in found] == [(1, 10), (6, 15), (11, 20), (16, 23)]
    assert found[-1][2].split()[-1] == "zeta" and len(found[-1][2].split()) == 8


def test_best_windows_come_back_in_document_order_with_word_ranges():
    words = text_of(100).split()
    for position in (86, 87, 88):  # three hits make window 81-90 the best, a single hit window 1-10 the second
        words[position - 1] = "zeta"
    words[4] = "zeta"
    total, found = mem.passages(" ".join(words), "zeta", count=2, words=10)
    assert total == 100 and len(found) == 2
    assert [a for a, _, _ in found] == sorted(a for a, _, _ in found)
    assert all(len(t.split()) == b - a + 1 for a, b, t in found)
    assert any(a <= 86 <= b for a, b, _ in found)


@pytest.mark.parametrize("position", range(1, 41))
def test_a_figure_at_a_window_boundary_is_inside_a_window(position):
    _, found = mem.passages(text_of(40, {position}), "zeta", count=99, words=10)
    assert any(a <= position <= b and t.split()[position - a] == "zeta" for a, b, t in found)


def test_cli_output_format_and_blank_line_between_passages(hub_root, capsys):
    source(hub_root, text_of(60, {5, 58}))
    code, out = run(hub_root, capsys, "zeta", "--words", "10")
    assert code == 0 and out.err == ""
    head, second = out.out.rstrip("\n").split("\n\n")
    assert head.splitlines()[:2] == [f"source: .sources/{FOLDER}/source.txt (60 words)", "== words 1-10 of 60 =="]
    assert head.splitlines()[2] == text_of(60).split("w5 ")[0] + "zeta " + " ".join(f"w{i}" for i in range(6, 11))
    assert second.splitlines()[0] == "== words 51-60 of 60 =="


def test_missing_source_exits_1_naming_the_folder_and_logs_nothing(hub_root, capsys):
    code, out = run(hub_root, capsys, "zeta")
    assert code == 1 and out.out == ""
    assert f".sources/{FOLDER}/" in out.err and f"fetch-sources {LIT}" in out.err
    assert not usage_log_path().exists()


def test_a_note_that_is_not_literature_exits_1(hub_root, capsys):
    code, out = run(hub_root, capsys, "zeta", path="knowledge/computing/attention-replaces-recurrence.md")
    assert code == 1 and out.out == "" and "fetch-sources" in out.err


def test_no_matching_passage_exits_0_with_empty_stdout(hub_root, capsys):
    source(hub_root, text_of(30))
    code, out = run(hub_root, capsys, "zebra")
    assert code == 0 and out.out == "" and out.err.startswith(f"no matching passage in .sources/{FOLDER}/")
    (entry,) = [json.loads(line) for line in usage_log_path().read_text().splitlines()]
    assert entry["hits"] == 0


def test_query_without_words_is_a_usage_error(hub_root, capsys):
    source(hub_root, text_of(30))
    with pytest.raises(SystemExit) as exc:
        run(hub_root, capsys, "!!!")
    assert exc.value.code == 2


def test_the_largest_txt_is_chosen_and_ties_go_by_name(hub_root, capsys):
    source(hub_root, "zeta small", "a.txt")
    source(hub_root, text_of(30, {3}), "c.txt")
    source(hub_root, text_of(30, {4}), "b.txt")  # same size as c.txt: the name decides
    source(hub_root, "zeta", "d.md")
    _, out = run(hub_root, capsys, "zeta")
    assert out.out.startswith(f"source: .sources/{FOLDER}/b.txt (30 words)")


def test_usage_log_entry(hub_root, capsys):
    source(hub_root, text_of(30, {3}))
    run(hub_root, capsys, "zeta", "--count", "2", "--words", "10")
    (entry,) = [json.loads(line) for line in usage_log_path().read_text().splitlines()]
    assert entry["cmd"] == "passages" and entry["path"] == LIT and entry["query"] == "zeta"
    assert (entry["count"], entry["words"], entry["hits"]) == (2, 10, 1)


def test_absolute_path_inside_the_hub_is_accepted(hub_root, capsys):
    source(hub_root, text_of(40, marks=(7,)))
    code, out = run(hub_root, capsys, "zeta", path=str((hub_root / LIT).resolve()))
    assert code == 0 and out.out.startswith(f"source: .sources/{FOLDER}/source.txt (40 words)")
