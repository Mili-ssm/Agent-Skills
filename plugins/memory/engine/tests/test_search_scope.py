import json

import mem
from commands import read
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
    assert (
        run(hub_root, capsys, "attention")[1]
        == run(hub_root, capsys, "attention", "--type", "knowledge")[1]
    )


def test_deep_equals_the_previous_default_ranking_of_all_types(hub_root, capsys):
    expected = "".join(
        f"{rel}\t{score:.2f}\t{title}\n"
        for rel, score, title in read.note_search.search(hub_root, "attention")
    )
    _, out, err = run(hub_root, capsys, "attention", "--deep")
    assert out == expected and {"literature", "knowledge"} <= kinds(out) and not err


def test_explicit_type_needs_no_deep_and_prints_no_hint(hub_root, capsys):
    _, out, err = run(hub_root, capsys, "attention", "--type", "literature")
    assert kinds(out) == {"literature"} and not err


def test_hint_when_the_default_prints_fewer_than_three_and_deep_would_print_more(hub_root, capsys):
    _, out, err = run(hub_root, capsys, "evaluating")  # only an investigation matches
    assert not out and err == "no matches\n" + HINT
    _, _, err = run(hub_root, capsys, "attention")  # one knowledge note, one source: more in deep
    assert err == HINT


def test_no_hint_with_deep_or_when_nothing_more_exists(hub_root, capsys):
    assert not run(hub_root, capsys, "evaluating", "--deep")[2]
    assert HINT not in run(hub_root, capsys, "zzzunknown")[2]


def test_links_in_the_default_search_stay_among_knowledge_notes(hub_root, capsys):
    _, out, _ = run(hub_root, capsys, "attention", "--links")
    assert kinds(out) == {"knowledge"}


def test_also_applies_the_default_to_every_query(hub_root, capsys):
    _, out, _ = run(hub_root, capsys, "attention", "--also", "vaswani")
    assert "== attention ==" in out and "literature/" not in out


def test_usage_log_records_deep(hub_root, capsys):
    run(hub_root, capsys, "attention", "--deep")
    run(hub_root, capsys, "attention")
    first, second = [json.loads(line) for line in usage_log_path().read_text().splitlines()]
    assert first["deep"] is True and "deep" not in second


def test_batch_reuses_full_corpus_for_misses_and_sparse_hint(hub_root, capsys, monkeypatch):
    original = read.note_search.build_corpus
    calls = []

    def build(*args, **kwargs):
        calls.append(kwargs.get("type"))
        return original(*args, **kwargs)

    monkeypatch.setattr(read.note_search, "build_corpus", build)
    _, _, err = run(
        hub_root, capsys, "unknownone", "--also", "unknowntwo", "--also", "unknownthree"
    )
    assert err == "no matches\n" * 3
    assert calls == ["knowledge", None]
    calls.clear()
    _, _, err = run(hub_root, capsys, "unknownone", "--also", "attention")
    assert err == "no matches\n" + HINT
    assert calls == ["knowledge", None]
    calls.clear()
    run(hub_root, capsys, "unknownone", "--also", "attention", "--deep")
    assert calls == [None]


def test_failed_hint_corpus_build_is_retried(hub_root, capsys, monkeypatch):
    original = read.note_search.build_corpus
    calls = []

    def build(*args, **kwargs):
        calls.append(kwargs.get("type"))
        if calls == ["knowledge", None]:
            raise OSError("transient")
        return original(*args, **kwargs)

    monkeypatch.setattr(read.note_search, "build_corpus", build)
    _, _, err = run(hub_root, capsys, "unknownone", "--also", "attention")
    assert err == "no matches\n" + HINT
    assert calls == ["knowledge", None, None]
