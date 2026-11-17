import datetime
import io
import json
from pathlib import Path

import pytest

import mem
import records
from records import Related

TODAY = datetime.date(2026, 11, 17)


def memory(handle, claim, status="active"):
    return records.Memory("project", Path(f"{handle}.md"), handle, "lesson", claim, TODAY, 1, status,
                          None, None, [], "", None)


def related(memories=(), stems=(), text=""):
    return records.related_records(list(memories), list(stems), text, TODAY, tokenize=mem.tokenize)


def test_containment():
    tok = mem.tokenize
    assert records.containment(tok("retries duplicate side effects"), set(tok("retries duplicate side effects here"))) == 1.0
    assert records.containment(tok("retries duplicate"), {"retries"}) == 0.5
    assert records.containment(tok("the retries"), {"retries"}) == 0.0  # one term left
    assert records.containment(["the", "of", "alpha", "beta"], {"alpha", "beta"}) == 1.0  # stop words ignored
    assert records.containment(["alpha", "2026", "11"], {"alpha"}) == 0.0  # digits are not terms: one term left
    assert records.containment(["alpha", "beta", "2026"], {"alpha", "beta"}) == 1.0


def test_related_bands_order_and_exclusions():
    mems = [memory("b-strong", "alpha beta gamma delta"), memory("a-strong", "alpha beta gamma delta"),
            memory("half", "alpha beta zeta eta"), memory("none", "zeta eta theta iota"),
            memory("gone", "alpha beta gamma delta", status="refuted"),
            memory("quoted", "alpha beta gamma delta")]
    strong, possible = related(mems, ["alpha-beta-gamma-delta", "alpha-beta-zeta-eta"],
                               "alpha beta gamma delta m:quoted")
    assert [r.handle for r in strong if r.kind == "n"] == ["alpha-beta-gamma-delta"]
    handles = [r.handle for r in strong]
    assert "quoted" not in handles and "gone" not in handles
    assert "alpha-beta-gamma-delta" in handles  # related_records still accepts note stems
    assert handles.index("a-strong") < handles.index("b-strong")
    assert {r.handle for r in possible} == {"half", "alpha-beta-zeta-eta"}
    assert all(r.score >= records.POSSIBLE for r in possible) and all(r.score < records.STRONG for r in possible)


def test_order_memories_before_notes_on_equal_score():
    strong, _ = related([memory("m1", "alpha beta")], ["alpha-beta"], "alpha beta")
    assert [r.kind for r in strong] == ["m", "n"]


def test_signal_text_empty_without_strong():
    assert mem.signal_text([], [Related("x", "m", 0.6)]) == ""


LINE1 = "[memory] For information: memories related to this task exist (not read yet): "
LINE3 = ("They are experience, not fact: where one conflicts with this brief, the brief wins and you report the "
         "conflict.")


def test_signal_text_exact():
    text = mem.signal_text([Related("a", "m", 1.0), Related("b", "m", 1.0)], [Related("c", "m", 0.5)])
    assert text.split("\n") == [
        LINE1 + "m:a m:b m:c",
        "2 strong, 1 possibly related. Read one with: mem show m:<handle> (they are files in .memory/).",
        LINE3]


def test_signal_text_twenty_matches():
    strong = [Related(f"memory-handle-{i:02d}-" + "x" * 8, "m", 1.0) for i in range(20)]
    text = mem.signal_text(strong, [])
    assert len(text) <= 400 and text.count("\n") == 2
    assert text.split("\n")[0].count(" m:") == 3 and "20 strong, 0 possibly" in text


def test_already_named_means_a_whole_token():
    mems = [memory("retry-keys", "alpha beta gamma")]
    assert related(mems, [], "alpha beta gamma retry-keys") == ([], [])
    assert related(mems, [], "alpha beta gamma m:retry-keys,") == ([], [])
    assert len(related(mems, [], "alpha beta gamma retry-keys-more")[0]) == 1
    assert len(related(mems, [], "alpha beta gamma xretry-keys")[0]) == 1


def hook(monkeypatch, tmp_path, stdin):
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return mem.main(["signal", "--hook"])


def payload(prompt, tool="Agent", **extra):
    return json.dumps({"tool_name": tool, "tool_input": {"prompt": prompt, **extra}, "cwd": str(Path.cwd())})


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    folder = root / ".memory"
    folder.mkdir(parents=True)
    (folder / "retry-keys.md").write_text(
        "---\nkind: lesson\nclaim: Retries without idempotency keys duplicate side effects\n"
        "created: 2026-11-01\nobserved: 1\nstatus: active\n---\n", encoding="utf-8")
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return folder


def test_hook_appends_signal(proj, tmp_path, monkeypatch, capsys):
    brief = "Review how retries without idempotency keys duplicate side effects in the sync job."
    assert hook(monkeypatch, tmp_path, payload(brief, model="haiku", subagent_type="Explore")) == 0
    out = capsys.readouterr().out
    obj = json.loads(out)
    assert "permissionDecision" not in out
    spec = obj["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    prompt = spec["updatedInput"]["prompt"]
    assert prompt.startswith(brief + "\n\n") and prompt.endswith(
        mem.signal_text([Related("retry-keys", "m", 1.0)], []))
    assert spec["updatedInput"]["model"] == "haiku"
    rec = json.loads((tmp_path / "data" / "hooks" / "log.jsonl").read_text().splitlines()[-1])
    assert list(rec) == ["t", "hook", "ms", "strong", "possible", "subagent_type", "words"]
    assert rec["strong"] == 1 and rec["subagent_type"] == "Explore" and rec["words"] == len(brief.split())


def test_hook_logs_a_null_subagent_type(proj, tmp_path, monkeypatch, capsys):
    assert hook(monkeypatch, tmp_path, payload("Write a poem about the sea.")) == 0
    rec = json.loads((tmp_path / "data" / "hooks" / "log.jsonl").read_text().splitlines()[-1])
    assert rec["subagent_type"] is None and rec["words"] == 6


@pytest.mark.parametrize("stdin", [
    payload("Write a poem about the sea."),
    payload("retries without idempotency keys duplicate side effects", tool="Bash"),
    payload("see m:retry-keys: retries without idempotency keys duplicate side effects"),
    payload(""),
    json.dumps({"tool_name": "Agent"}),
    json.dumps({"tool_name": "Agent", "tool_input": {"prompt": 5}}),
    "", "not json", "[]",
])
def test_hook_prints_nothing(proj, tmp_path, monkeypatch, capsys, stdin):
    assert hook(monkeypatch, tmp_path, stdin) == 0
    assert capsys.readouterr().out == ""


def test_command_without_hook_reads_the_brief(proj, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("retries without idempotency keys duplicate side effects"))
    assert mem.main(["signal"]) == 0
    assert "m:retry-keys" in capsys.readouterr().out


def test_no_store_no_project_prints_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr("sys.stdin", io.StringIO("retries without idempotency keys"))
    assert mem.main(["signal"]) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_notes_are_not_signalled(hub_root, proj, tmp_path, monkeypatch, capsys):
    folder = hub_root / "knowledge" / "d"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bm25-is-a-strong-baseline.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("MEM_STORE", str(hub_root))
    monkeypatch.setattr("sys.stdin", io.StringIO("choose bm25 as a strong baseline"))
    assert mem.main(["signal"]) == 0
    assert capsys.readouterr().out == ""


def test_thresholds_are_the_ones_chosen_on_the_labelled_set():
    # Stage 6 plan, Task 2: chosen on evals/signal/set.json by a rule written beforehand.
    assert (records.STRONG, records.POSSIBLE, records.MIN_TERMS) == (0.6, 0.5, 2)
