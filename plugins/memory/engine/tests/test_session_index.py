import datetime
import io
import json
from pathlib import Path

import pytest

import mem

TODAY = datetime.date(2026, 11, 17)
LINE1 = "memory: the mem command searches notes and memories (skill: memory)."
FIXED = [
    LINE1,
    '- Before you act on this project, change something or research a topic: mem search "<topic in English>". '
    "It returns decisions, constraints and pitfalls recorded earlier that the files do not show.",
    "- To remember: preferences and personal matters -> auto memory; what a later session would need (a decision, "
    "constraint, pitfall or finding) -> mem remember, in English, with --global if it holds in any project and names "
    "no business; the project's current situation -> both.",
]


def write(folder: Path, handle: str, claim: str, *, observed=1, created="2026-11-01", status="active", kind="lesson"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{handle}.md").write_text(
        f"---\nkind: {kind}\nclaim: {claim}\ncreated: {created}\nobserved: {observed}\nstatus: {status}\n---\n",
        encoding="utf-8")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root / ".memory"


def test_fixed_lines_without_store_or_project():
    assert mem.session_index(None, None, None, TODAY).split("\n") == FIXED


def test_store_count_matches_files(hub_root):
    n = len([p for k in ("literature", "knowledge") for p in hub_root.glob(f"{k}/*/*.md") if p.name != "README.md"])
    n += len(list(hub_root.glob("research/*/README.md")))
    lines = mem.session_index(hub_root, None, None, TODAY).split("\n")
    assert lines == [LINE1 + f" Store: {n} notes."] + FIXED[1:]


def test_global_count_with_and_without_store(hub_root, tmp_path):
    g = tmp_path / "g"
    write(g, "a", "A claim.")
    write(g, "b", "Old claim.", status="refuted")
    assert mem.session_index(None, None, g, TODAY).split("\n")[0] == LINE1 + " Global memories: 1."
    first = mem.session_index(hub_root, None, g, TODAY).split("\n")[0]
    assert first.startswith(LINE1 + " Store: ") and first.endswith(" notes. Global memories: 1.")


def test_project_count_alone_and_all_three_in_order(proj, hub_root, tmp_path):
    write(proj, "alpha", "Alpha claim.", observed=1, created="2026-11-05", kind="lesson")
    write(proj, "beta", "Beta claim.", observed=3, created="2026-11-01", kind="decision")
    lines = mem.session_index(None, proj, None, TODAY).split("\n")
    assert lines == [LINE1 + " This project: 2 memories."] + FIXED[1:]
    g = tmp_path / "g"
    write(g, "a", "A claim.")
    n = len([p for k in ("literature", "knowledge") for p in hub_root.glob(f"{k}/*/*.md") if p.name != "README.md"])
    n += len(list(hub_root.glob("research/*/README.md")))
    first = mem.session_index(hub_root, proj, g, TODAY).split("\n")[0]
    assert first == f"{LINE1} Store: {n} notes. Global memories: 1. This project: 2 memories."


def test_list_two_memories(proj):
    write(proj, "alpha", "Alpha claim.", observed=1, created="2026-11-05", kind="lesson")
    write(proj, "beta", "Beta claim.", observed=3, created="2026-11-01", kind="decision")
    lines = mem.session_index(None, proj, None, TODAY, limit=8).split("\n")
    assert lines[:3] == [LINE1 + " This project: 2 memories."] + FIXED[1:]
    assert lines[3:] == ["  m:beta [decision, 2026-11-01] Beta claim.",
                         "  m:alpha [lesson, 2026-11-05] Alpha claim."]


def test_default_is_three_lines_with_forty_memories(proj):
    for i in range(40):
        write(proj, f"m{i:02d}", "y" * 300)
    lines = mem.session_index(None, proj, None, TODAY).split("\n")
    assert len(lines) == 3 and lines[0] == LINE1 + " This project: 40 memories."


def test_order_observed_then_created_then_handle(proj):
    write(proj, "c", "C.", observed=2, created="2026-11-01")
    write(proj, "b", "B.", observed=2, created="2026-11-03")
    write(proj, "a", "A.", observed=2, created="2026-11-03")
    write(proj, "z", "Z.", observed=1, created="2026-11-09")
    rows = mem.session_index(None, proj, None, TODAY, limit=8).split("\n")[3:]
    assert [r.split()[0] for r in rows] == ["m:a", "m:b", "m:c", "m:z"]


def test_long_claim_is_cut(proj):
    write(proj, "long", "x" * 400)
    row = mem.session_index(None, proj, None, TODAY, limit=8).split("\n")[-1]
    assert row.endswith("] " + "x" * 100 + "…")


def test_forty_memories_fit_and_count_the_rest(proj):
    for i in range(40):
        write(proj, f"m{i:02d}", "y" * 300, created="2026-11-01")
    text = mem.session_index(None, proj, None, TODAY, limit=40)
    assert len(text) <= 1500
    lines = text.split("\n")
    assert lines[-1].startswith("  … and ")
    k = int(lines[-1].split()[2])
    listed = [ln for ln in lines if ln.startswith("  m:")]
    assert k + len(listed) == 40 and k > 0


def test_list_eight_of_twelve(proj):
    for i in range(12):
        write(proj, f"m{i:02d}", "short")
    lines = mem.session_index(None, proj, None, TODAY, limit=8).split("\n")
    assert len([ln for ln in lines if ln.startswith("  m:")]) == 8
    assert lines[-1].startswith("  … and 4 more:")


def test_broken_and_refuted_are_skipped(proj, capsys):
    write(proj, "good", "Good.")
    write(proj, "gone", "Gone.", status="refuted")
    (proj / "broken.md").write_text("---\nkind: nonsense\n---\n", encoding="utf-8")
    text = mem.session_index(None, proj, None, TODAY, limit=8)
    assert "This project: 1 memories." in text and "m:good" in text
    assert "gone" not in text and "broken" not in text
    assert capsys.readouterr().err == ""


def test_command_without_store_outside_git(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert mem.main(["session-index"]) == 0
    out = capsys.readouterr()
    assert out.out.rstrip("\n").split("\n") == FIXED and out.err == ""


def test_command_with_store_path_containing_spaces(tmp_path, monkeypatch, capsys):
    store = tmp_path / "my store"
    (store / "knowledge" / "d").mkdir(parents=True)
    (store / "knowledge" / "d" / "n.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("MEM_STORE", str(store))
    assert mem.main(["session-index"]) == 0
    assert "Store: 1 notes." in capsys.readouterr().out


def test_list_option_appends_the_listing(proj, capsys):
    write(proj, "a", "A.")
    assert mem.main(["session-index", "--list", "8"]) == 0
    lines = capsys.readouterr().out.rstrip("\n").split("\n")
    assert len(lines) == 4 and lines[3].startswith("  m:a ")


def test_command_writes_nothing(hub_root, proj, monkeypatch, tmp_path):
    monkeypatch.setenv("MEM_STORE", str(hub_root))
    write(proj, "a", "A.")
    before = sorted(p for p in tmp_path.rglob("*"))
    assert mem.main(["session-index", "--list", "8"]) == 0
    assert sorted(p for p in tmp_path.rglob("*")) == before


def test_state_memories_come_first(proj):
    write(proj, "a", "A.", observed=5, kind="lesson")
    write(proj, "s2", "S two.", observed=1, kind="state", created="2026-11-02")
    write(proj, "s1", "S one.", observed=2, kind="state", created="2026-11-01")
    rows = mem.session_index(None, proj, None, TODAY, limit=8).split("\n")[3:]
    assert [r.split()[0] for r in rows] == ["m:s1", "m:s2", "m:a"]


def test_missing_observed_sorts_as_one(proj):
    (proj / "n.md").parent.mkdir(parents=True, exist_ok=True)
    (proj / "n.md").write_text("---\nkind: lesson\nclaim: N.\ncreated: 2026-11-09\nstatus: active\n---\n", encoding="utf-8")
    write(proj, "two", "Two.", observed=2, created="2026-11-01")
    rows = mem.session_index(None, proj, None, TODAY, limit=8).split("\n")[3:]
    assert [r.split()[0] for r in rows] == ["m:two", "m:n"]


def hook_run(monkeypatch, tmp_path, stdin, argv=("session-index", "--hook")):
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return mem.main(list(argv))


def test_hook_uses_cwd_of_input_and_logs(tmp_path, monkeypatch, capsys):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.delenv("MEM_PROJECT", raising=False)
    monkeypatch.setenv("MEM_PROJECT", str(other))
    write(other / ".memory", "here", "Here.")
    monkeypatch.chdir(tmp_path)
    assert hook_run(monkeypatch, tmp_path, json.dumps({"cwd": str(other), "source": "startup"})) == 0
    out = capsys.readouterr().out
    assert "This project: 1 memories." in out and "m:here" not in out
    lines = (tmp_path / "data" / "hooks" / "log.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert list(rec) == ["t", "hook", "source", "ms", "chars"]
    assert rec["hook"] == "session-index" and rec["source"] == "startup"
    assert isinstance(rec["ms"], int) and rec["chars"] == len(out) - 1
    assert str(other) not in lines[0]


def test_hook_cwd_selects_the_project(tmp_path, monkeypatch, capsys):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    write(repo / ".memory", "inrepo", "In repo.")
    monkeypatch.delenv("MEM_PROJECT", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    hook_run(monkeypatch, tmp_path, json.dumps({"cwd": str(repo)}))
    assert "This project: 1 memories." in capsys.readouterr().out
    rec = json.loads((tmp_path / "data" / "hooks" / "log.jsonl").read_text().splitlines()[0])
    assert rec["source"] is None


def test_hook_with_invalid_input_still_prints_and_logs(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert hook_run(monkeypatch, tmp_path, "not json") == 0
    assert capsys.readouterr().out.rstrip("\n").split("\n") == FIXED
    assert (tmp_path / "data" / "hooks" / "log.jsonl").exists()


def test_without_hook_reads_no_input_and_logs_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    class Boom:
        def read(self, *a):
            raise AssertionError("stdin was read")
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "data"))
    monkeypatch.setattr("sys.stdin", Boom())
    assert mem.main(["session-index"]) == 0
    assert not (tmp_path / "data").exists()


def test_triage_line_counts_the_lessons_awaiting_triage(tmp_path):
    folder = tmp_path / "gmem"
    for handle in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
        write(folder, handle, f"Lesson {handle}.")
        path = folder / f"{handle}.md"
        path.write_text(path.read_text().replace("status: active\n", "status: active\ntriage: pending\n"), encoding="utf-8")
    assert "Triage: 2 general lessons await triage (mem curate --global)." in mem.session_index(None, None, folder, TODAY)
