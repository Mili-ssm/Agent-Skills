"""`mem-synthesize --backfill`: a read-only session proposes references, code applies them; run with a fake `claude`."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import backfill as bf
import pytest
import synth_pipeline as sp
import syntheses
from test_synth_pipeline_refs import A, B, store, synthesis_text

__all__ = ["store"]  # re-exported: pytest finds the fixture in this module by its name

BIN = Path(__file__).resolve().parents[2] / "bin" / "mem-synthesize"
URL_PART = "Delta says a thing.\n\nSources: [paper](https://example.org/paper)"
TWO_SESSIONS = 2
USAGE_EXIT = 2
ANSWER_LINES = 5
DONE_PART = f"Epsilon is already linked.[a]({A})\n\nSources: [a]({A})"

FAKE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_ARGS"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MODE", "answer")
if mode == "answer":
    print(json.dumps({"type": "result", "is_error": False, "result": open(os.environ["FAKE_ANSWER"]).read(),
                      "total_cost_usd": 0.02, "modelUsage": {}}))
elif mode == "error":
    print(json.dumps({"type": "result", "is_error": True, "result": "boom", "total_cost_usd": 0.01}))
"""


@pytest.fixture
def ms(monkeypatch):
    loader = importlib.machinery.SourceFileLoader("mem_synthesize_bin", str(BIN))
    spec = importlib.util.spec_from_loader("mem_synthesize_bin", loader)
    if spec is None:
        raise ImportError(f"cannot load {BIN}")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules, spec.name, module
    )  # @dataclass before Python 3.13 looks its module up here
    loader.exec_module(module)
    return module


@pytest.fixture
def fake(tmp_path, monkeypatch):
    claude = tmp_path / "fake-claude"
    claude.write_text(FAKE)
    claude.chmod(0o755)
    monkeypatch.setenv("FAKE_ARGS", str(tmp_path / "args.jsonl"))
    monkeypatch.setenv("FAKE_ANSWER", str(tmp_path / "answer.txt"))
    return claude


def sessions(tmp_path):
    path = tmp_path / "args.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def answer(tmp_path, text):
    (tmp_path / "answer.txt").write_text(text)


@pytest.fixture
def full(store):
    for name, text in (("Delta", URL_PART), ("Epsilon", DONE_PART)):
        assert (
            sp.mem(
                store,
                {},
                "synthesis",
                "add",
                "s:attention",
                "--section",
                name,
                "--body-file",
                "-",
                stdin=text + "\n",
            ).returncode
            == 0
        )
    return store


def backfill(ms, claude, store, handles=("s:attention",), dry_run=False):
    lines, rows = [], []
    code = ms.run_backfill(
        str(claude), store, list(handles), 3.0, dry_run, out=lines.append, rows_out=rows
    )
    return code, lines, rows


def marks(ms):
    """Every part marked done, as (store, synthesis, part) -> fingerprint."""
    return {
        (s, n, p): fp
        for s, syns in bf.load_done(ms.done_file())[0].items()
        for n, parts in syns.items()
        for p, fp in parts.items()
    }


def words(root):
    text = synthesis_text(root)
    return {h: syntheses.without_references(t) for h, t in sp.split_parts(text).items()}


ANSWER = f"""```text
alpha | 1 | {A}
alpha | 1 | `{B}`
alpha | 2 | {B}
beta | 1 | {B}
beta | 1 | {A}
alpha | 3 | none
I could not decide on the table rows
```
"""


def test_select_skips_url_only_fully_referenced_and_done_parts(full):
    path = full / "syntheses" / "attention.md"
    assert [p["handle"] for p in bf.select(path, {})] == [
        "alpha",
        "beta",
    ]  # gamma, delta, epsilon skipped
    done = {"alpha": syntheses.fingerprint(syntheses.load_one(path).parts[0].text)}
    assert [p["handle"] for p in bf.select(path, done)] == ["beta"]
    assert [p["handle"] for p in bf.select(path, {"beta": "stale"})] == ["alpha", "beta"]


def test_session_has_only_read_and_no_other_permission(ms, fake, full, tmp_path):
    answer(tmp_path, f"beta | 1 | {B}\n")
    backfill(ms, fake, full)
    (argv,) = sessions(tmp_path)
    argv = (
        argv[: argv.index("-p")] + argv[argv.index("-p") + 2 :]
    )  # the prompt is text, not a permission
    assert argv[argv.index("--tools") + 1] == "Read"
    allowed = argv[argv.index("--allowedTools") + 1 : argv.index("--output-format")]
    assert allowed and all(a.startswith("Read(") for a in allowed), allowed
    assert not {"Bash", "Write", "Edit", "WebSearch", "WebFetch"} & {t.split("(")[0] for t in argv}
    assert (
        argv[argv.index("--model") + 1] == "haiku" and argv[argv.index("--effort") + 1] == sp.CHEAP
    )
    assert "--max-budget-usd" in argv


def test_valid_lines_apply_and_nothing_else_changes(ms, fake, full, tmp_path):
    answer(tmp_path, ANSWER)
    before_words = words(full)
    before_check = sp.mem(full, {}, "check").returncode
    code, lines, rows = backfill(ms, fake, full)
    (row,) = rows
    assert (code, row["status"]) == (0, "ok")
    assert (
        row["parts"],
        row["proposed"],
        row["applied"],
        row["refused"],
        row["none"],
        row["unreadable"],
        row["repeated"],
    ) == (2, 5, 4, 1, 1, 1, 0)
    assert row["mem_check"] == before_check and row["cost"] == pytest.approx(0.02)
    path = full / "syntheses" / "attention.md"
    refs = {
        s.handle: {u.n: u.refs for u in syntheses.units(s.text)[0]}
        for s in syntheses.load_one(path).parts
    }
    assert refs["alpha"][1] == [A, B] and refs["alpha"][2] == [A, B] and refs["alpha"][3] == [B]
    assert refs["alpha"][4] == [] and refs["beta"][1] == [B]
    assert words(full) == before_words
    assert "alpha | 3 | First plain" not in "\n".join(lines)
    table = lines[-2].splitlines() if lines[-2].startswith("synthesis") else lines[-3].splitlines()
    assert table[0].split()[:2] == ["synthesis", "parts"] and table[-1].split()[:3] == [
        "total",
        "2",
        "6",
    ]
    log = next(Path(l.rsplit("log ", 1)[1]) for l in lines if "log " in l).read_text()
    assert "none: alpha | 3 | Third has an inline one in it." in log and "refused:" in log


def test_second_run_starts_no_session_and_a_reworded_part_is_due_again(ms, fake, full, tmp_path):
    answer(tmp_path, ANSWER)
    backfill(ms, fake, full)
    assert len(sessions(tmp_path)) == 1
    code, lines, rows = backfill(ms, fake, full)
    assert code == 0 and rows == [] and len(sessions(tmp_path)) == 1 and "nothing to do" in lines[0]
    done = json.loads(ms.done_file().read_text())
    assert set(done[str(full)]["attention"]) == {"alpha", "beta"}
    path = full / "syntheses" / "attention.md"
    path.write_text(path.read_text().replace("Second one is backed.", "Second one is well backed."))
    backfill(ms, fake, full)
    assert len(sessions(tmp_path)) == TWO_SESSIONS


@pytest.mark.parametrize("mode", ["error", "silent"])
def test_failed_session_applies_nothing_and_marks_nothing(ms, fake, full, monkeypatch, mode):
    tmp_path = fake.parent  # the fixture writes the fake claude and its logs in tmp_path
    monkeypatch.setenv("FAKE_MODE", mode)
    before = (full / "syntheses" / "attention.md").read_bytes()
    code, _, rows = backfill(ms, fake, full)
    assert code == 1 and rows[0]["status"].startswith("failed") and rows[0]["applied"] == 0
    assert (full / "syntheses" / "attention.md").read_bytes() == before
    assert not marks(ms)
    backfill(ms, fake, full)
    assert len(sessions(tmp_path)) == TWO_SESSIONS


def test_an_answer_without_a_readable_line_marks_nothing(ms, fake, full, tmp_path):
    answer(tmp_path, "nothing to say\n")
    code, _, rows = backfill(ms, fake, full)
    assert code == 1 and rows[0]["unreadable"] == 1 and not marks(ms)


def test_restore_returns_the_synthesis_to_its_bytes(ms, fake, full, tmp_path):
    path = full / "syntheses" / "attention.md"
    before = path.read_bytes()
    answer(tmp_path, ANSWER)
    backfill(ms, fake, full)
    assert path.read_bytes() != before
    assert sp.mem(full, {}, "restore", "s:attention").returncode == 0
    assert path.read_bytes() == before


def test_dry_run_lists_the_parts_and_starts_no_session(ms, fake, full, tmp_path):
    code, lines, _ = backfill(ms, fake, full, handles=(), dry_run=True)
    assert code == 0 and not sessions(tmp_path) and not marks(ms)
    assert lines[0].startswith("s:attention: alpha (3 of 5 units") and "beta (1 of 1" in lines[0]
    assert "dry run: 1 syntheses" in lines[-1] and "estimated cost 0.05 USD" in lines[-1]


def test_parse_answer_tolerates_fences_ticks_and_space():
    found, bad, repeated, nothing = bf.parse_answer(
        "```\n  alpha | 2 |  `../knowledge/x/y.md` \nalpha | 2 | ../knowledge/x/y.md\n"
        "s:t#beta | 1 | none\nwords\n```\n"
    )
    assert found == [("alpha", 2, "../knowledge/x/y.md"), ("beta", 1, "none")] and bad == 1
    assert repeated == 1 and not nothing


def test_nothing_answer_is_an_explicit_empty_result():
    for text in ("nothing", " Nothing.\n", "NOTHING\n\n"):
        assert bf.parse_answer(text) == ([], 0, 0, True), text
    for text in ("", "\n", "nothing here\n", "nothing\nalpha | 1 | none\n"):
        assert not bf.parse_answer(text).nothing, text


def test_none_case_and_decorated_targets():
    found, bad, _, _ = bf.parse_answer(
        "alpha | 1 | None\nalpha | 2 | NONE\nalpha | 3 | `<../k/x.md>.`\nalpha | 4 | <../k/y.md>\n"
    )
    assert (
        found
        == [
            ("alpha", 1, "none"),
            ("alpha", 2, "none"),
            ("alpha", 3, "../k/x.md"),
            ("alpha", 4, "../k/y.md"),
        ]
        and bad == 0
    )


def test_line_counts_add_up():
    text = f"```\nalpha | 1 | {A}\nalpha | 1 | {A}\nalpha | 2 | none\nwords\nmore words\n\n```\n"
    found, bad, repeated, _ = bf.parse_answer(text)
    proposed = [f for f in found if f[2] != "none"]
    nones = [f for f in found if f[2] == "none"]
    assert len(proposed) + len(nones) + bad + repeated == ANSWER_LINES


def test_nothing_answer_marks_all_parts_done_and_second_run_is_free(ms, fake, full, tmp_path):
    answer(tmp_path, "Nothing.\n")
    code, _, rows = backfill(ms, fake, full)
    assert (code, rows[0]["status"], rows[0]["proposed"]) == (0, "ok", 0)
    assert {p for (_, _, p) in marks(ms)} == {"alpha", "beta"}
    backfill(ms, fake, full)
    assert len(sessions(tmp_path)) == 1


def test_only_parts_named_by_a_readable_line_are_marked_when_a_line_is_unreadable(
    ms, fake, full, tmp_path
):
    answer(tmp_path, f"beta | 1 | {B}\nalpha is garbled\n")
    backfill(ms, fake, full)
    assert {p for (_, _, p) in marks(ms)} == {"beta"}
    answer(tmp_path, f"beta | 1 | {B}\n")
    backfill(ms, fake, full)
    assert {p for (_, _, p) in marks(ms)} == {"alpha", "beta"}  # clean answer: every selected part


def test_save_done_merges_only_its_entry(tmp_path):
    path = tmp_path / "state" / "done.json"
    bf.save_done(path, "/s", "one", {"a": "1"})
    bf.save_done(path, "/s", "two", {"b": "2"})
    bf.save_done(path, "/s", "one", {"c": "3"})  # another process wrote "two" meanwhile: kept
    data, ok = bf.load_done(path)
    assert ok and data == {"/s": {"one": {"a": "1", "c": "3"}, "two": {"b": "2"}}}
    assert not list(path.parent.glob("*.tmp"))


def test_corrupt_done_file_stops_before_any_session(ms, fake, full, tmp_path, capsys):
    ms.done_file().parent.mkdir(parents=True, exist_ok=True)
    ms.done_file().write_text("{not json")
    for dry in (False, True):
        code, _, rows = backfill(ms, fake, full, dry_run=dry)
        assert code == 1 and rows == [] and not sessions(tmp_path)
        err = capsys.readouterr().err
        assert str(ms.done_file()) in err and "move" in err
    assert bf.load_done(tmp_path / "missing.json") == ({}, True)


def test_store_key_is_the_resolved_path(ms, fake, full, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(full)
    answer(tmp_path, f"beta | 1 | {B}\n")
    backfill(ms, fake, link)
    assert {s for (s, _, _) in marks(ms)} == {str(full.resolve())}


def test_topic_or_self_check_with_backfill_is_an_error(ms, monkeypatch, capsys):
    for flag in (["--topic", "x"], ["--self-check"]):
        monkeypatch.setattr(sys, "argv", ["mem-synthesize", "--backfill", *flag])
        with pytest.raises(SystemExit) as exc:
            ms.main()
        assert exc.value.code == USAGE_EXIT
        assert "--backfill takes synthesis handles" in capsys.readouterr().err


def test_a_failed_done_list_write_does_not_skip_the_table_or_the_commit(
    ms, fake, full, tmp_path, monkeypatch
):
    answer(tmp_path, ANSWER)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(bf, "save_done", boom)
    commits = []
    monkeypatch.setattr(
        ms, "history_commit", lambda store, env, message, log: commits.append(message)
    )
    code, lines, rows = backfill(ms, fake, full)
    assert code == 1 and rows[0]["status"] == "ok, done list not saved: disk full"
    assert any(l.startswith("synthesis") for l in lines)
    assert commits[-1] == "mem-synthesize: after backfill attention"


def test_rows_after_a_session_without_cost_say_why(ms, fake, full, tmp_path, monkeypatch):
    for name in ("two",):
        text = (full / "syntheses" / "attention.md").read_text()
        (full / "syntheses" / f"{name}.md").write_text(text)
    monkeypatch.setenv("FAKE_MODE", "silent")
    _, _, rows = backfill(ms, fake, full, handles=("s:attention", "s:two"))
    assert rows[1]["status"] == "not started: an earlier session returned no cost"
