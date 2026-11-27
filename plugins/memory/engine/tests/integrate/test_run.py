"""`mem-integrate run`: two read-only sessions per synthesis (place, check) and one `mem synthesis integrate` call,
run with a fake `claude` that answers from a queue."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import mem
import pytest
from core import auto_state, jobs
from entry import integrate as entry
from integrate import state as run_state
from integrate_store import (  # ruff: ignore[unused-import]  (a fixture)
    LONG_AGO,
    store_with_part,
)
from synthesize import run as synth_run

if TYPE_CHECKING:
    from integrate_store import Store

CUTOFF = LONG_AGO + 1000
ONE_RUN_SESSIONS = 2
UNIT_TWO = 2
FAKE_COST = 0.02
SMALL_BUDGET = "0.0001"

FAKE = """#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
plan_file, count_file = os.environ["FAKE_PLAN"], os.environ["FAKE_COUNT"]
plan = json.load(open(plan_file))
n = int(open(count_file).read()) if os.path.exists(count_file) else 0
open(count_file, "w").write(str(n + 1))
with open(os.environ["FAKE_ARGS"], "a") as f:
    f.write(json.dumps(argv) + "\\n")
step = plan[n] if n < len(plan) else {"answer": "none"}
print(json.dumps({"type": "result", "is_error": step.get("error", False), "result": step["answer"],
                  "total_cost_usd": step.get("cost", 0.02), "modelUsage": {}}))
"""


def _flag_values(argv: list[str], flag: str) -> list[str]:
    start = argv.index(flag) + 1
    stop = next((i for i in range(start, len(argv)) if argv[i].startswith("--")), len(argv))
    return argv[start:stop]


@dataclass
class World:
    store: Store
    claude: Path
    tmp: Path
    capsys: pytest.CaptureFixture[str]
    work: Path | None = None

    def answers(self, *steps: str | dict) -> None:
        plan = [s if isinstance(s, dict) else {"answer": s} for s in steps]
        (self.tmp / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    @property
    def sessions(self) -> list[dict]:
        path = self.tmp / "args.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return [
            {
                "tools": ",".join(_flag_values(argv, "--tools")),
                "allowed_tools": _flag_values(argv, "--allowedTools"),
                "argv": argv,
            }
            for argv in map(json.loads, lines)
        ]

    def run(self, *extra: str) -> tuple[int, str]:
        self.capsys.readouterr()
        code = entry.main([
            "run",
            "--store",
            str(self.store.root),
            "--claude",
            str(self.claude),
            *extra,
        ])
        return code, self.capsys.readouterr().out

    @property
    def folder(self) -> Path:
        return entry.state_folder(self.store.root)

    def record(self) -> run_state.RunRecord:
        run_id = max(p.name for p in self.folder.iterdir() if p.is_dir())
        found = run_state.read_record(self.folder, run_id)
        assert found is not None
        return found

    @property
    def mem_log(self) -> str:
        return (self.folder / self.record().run_id / "log.txt").read_text(encoding="utf-8")

    def row(self, note: str, action: str = "append", handle: str = "alpha") -> str:
        return f"{note} | s:{handle}#basics | {action} | {self.store.fingerprint(handle)}"

    def commits(self) -> list[str]:
        out = subprocess.run(
            ["git", "-C", str(self.store.root), "log", "--format=%s"],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        return out.stdout.splitlines()

    def attached(self, slug: str) -> bool:
        return self.store.meta(slug).get("part_of") == "alpha#basics"


@pytest.fixture
def world(store_with_part, tmp_path, monkeypatch, capsys) -> World:
    claude = tmp_path / "fake-claude"
    claude.write_text(FAKE, encoding="utf-8")
    claude.chmod(0o755)
    for name, file in (
        ("FAKE_PLAN", "plan.json"),
        ("FAKE_COUNT", "count"),
        ("FAKE_ARGS", "args.jsonl"),
    ):
        monkeypatch.setenv(name, str(tmp_path / file))
    root = store_with_part.root
    git = ["git", "-C", str(root)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "config", "user.email", "t@example.org"], check=True)
    subprocess.run([*git, "config", "user.name", "t"], check=True)
    result = World(store_with_part, claude, tmp_path, capsys)
    result.work = entry.state_folder(root)
    return result


def test_run_integrates_one_note_end_to_end(world):
    row = world.row("n-new")
    world.answers(row, row)
    code, out = world.run()
    assert code == 0
    assert "applied\tn-new" in world.mem_log and world.attached("n-new")
    assert [c["tools"] for c in world.sessions] == ["Read"] * ONE_RUN_SESSIONS
    assert world.commits()[:2] == ["mem-integrate: after", "mem-integrate: before"]
    assert "synthesis" in out and "placed" in out and "siblings" not in out
    group = world.record().groups
    assert [(g.handles, g.kind) for g in group] == [(["s:alpha"], "integrate")]
    assert group[0].group_id


def test_every_session_argv_allows_read_of_the_work_folder(world):
    world.answers(world.row("n-new"), world.row("n-new"))
    world.run()
    sessions = world.sessions
    assert sessions
    for c in sessions:
        (allowed,) = c["allowed_tools"]
        assert allowed.startswith("Read(//") and allowed.endswith("/work/0/**)")
        assert str(world.folder) in allowed


def test_session_has_no_write_or_shell_tools(world):
    world.answers(world.row("n-new"), world.row("n-new"))
    world.run()
    for c in world.sessions:
        assert c["tools"] == "Read" and "Bash" not in " ".join(c["argv"])
        settings = c["argv"][c["argv"].index("--settings") + 1]
        assert json.loads(Path(settings).read_text(encoding="utf-8")) == {"disableAllHooks": True}
        assert c["argv"][c["argv"].index("--model") + 1] == "haiku"


def test_run_applies_nothing_on_malformed_answer(world):
    world.answers("I think n-new fits the first part.")
    code, out = world.run()
    assert code == 0 and not world.attached("n-new")
    assert "failed:" in out and world.record().groups == []
    assert len(world.sessions) == 1


def test_checker_must_agree(world):
    world.answers(world.row("n-new"), "none")
    assert world.run()[0] == 0
    assert not world.attached("n-new") and world.record().groups == []
    done = run_state.read_done(world.folder)
    assert {"n-new", "n-dup"} <= set(done)


def test_malformed_check_answer_keeps_none(world):
    world.answers(world.row("n-new"), "sure, go ahead")
    _, out = world.run()
    assert not world.attached("n-new") and "failed:" in out


def test_check_keeps_only_rows_in_both_answers(world):
    world.answers(
        f"{world.row('n-new')}\n{world.row('n-dup', 'unit 2')}",
        world.row("n-new"),
    )
    world.run()
    assert world.attached("n-new") and not world.attached("n-dup")


def test_row_the_check_invents_is_not_kept(world):
    world.answers(world.row("n-new"), world.row("n-dup", "unit 2"))
    world.run()
    assert not world.attached("n-new") and not world.attached("n-dup")


def test_run_skips_superseded_and_disputed(world):
    world.store.edit_meta("n-new", "superseded_by: n-dup")
    world.store.edit_meta("n-dup", "disputed: true")
    world.answers(world.row("n-new"), world.row("n-new"))
    world.run()
    assert world.sessions == []


def test_place_input_lists_the_notes_offered(world):
    world.answers("none")
    world.run()
    data = json.loads(next(world.folder.glob("*/work/0/place.json")).read_text(encoding="utf-8"))
    assert {n["note"] for n in data["notes"]} == {"n-new", "n-dup"}
    (part,) = data["parts"]
    assert part["part"] == "s:alpha#basics" and part["fingerprint"] == world.store.fingerprint()


def test_check_input_has_claim_and_target_text(world):
    world.answers(f"{world.row('n-new')}\n{world.row('n-dup', 'unit 2')}", "none")
    world.run()
    data = json.loads(next(world.folder.glob("*/work/0/check.json")).read_text(encoding="utf-8"))
    by_row = {item["row"]: item for item in data}
    new = by_row[world.row("n-new")]
    assert (
        new["claim"] == "Rust moves values by default."
        and "Values have exactly" in new["part_text"]
    )
    dup = by_row[world.row("n-dup", "unit 2")]
    assert dup["sentence"].startswith("Borrowing lends a value without moving it.")
    assert dup["unit"] == UNIT_TWO


def test_done_list_skips_unchanged_note_on_second_run(world):
    world.answers("none")
    world.run()
    assert len(world.sessions) == 1
    world.run()
    assert len(world.sessions) == 1  # nothing offered: both notes are done
    path = world.store.note_path("n-new")
    path.write_text(path.read_text(encoding="utf-8") + "\nAn owner edit.\n", encoding="utf-8")
    world.answers("none")
    (world.tmp / "count").unlink()
    world.run()
    data = json.loads(next(world.folder.glob("*/work/0/place.json")).read_text(encoding="utf-8"))
    assert [n["note"] for n in data["notes"]] == ["n-new"]


def test_one_session_per_synthesis(world):
    both = f"{world.row('n-new')}\n{world.row('n-dup', 'unit 2')}"
    world.answers(both, both)
    world.run()
    assert len(world.sessions) == ONE_RUN_SESSIONS  # two notes, one synthesis: not 4
    assert world.attached("n-new") and world.attached("n-dup")
    assert len(world.record().groups) == 1


def test_note_on_two_syntheses_applied_once(world):
    world.store.add_beta()
    world.store.new_note("n-both", "Both topics take this claim.")
    world.store.set_line("n-both", "topics", ["ml", "algorithms"])
    world.answers(world.row("n-both"), world.row("n-both"))
    world.run()
    groups = world.record().groups
    assert [g.handles for g in groups] == [["s:alpha"]]
    assert world.store.meta("n-both")["part_of"] == "alpha#basics"


def test_busy_lock_starts_nothing(world):
    fd = jobs.take_run_lock(auto_state.auto_dir(synth_run.state_dir(), world.store.root))
    assert fd is not None
    try:
        code, out = world.run()
    finally:
        os.close(fd)
    assert code == 0 and "holds the lock" in out
    assert world.sessions == [] and world.commits() == []


def test_budget_stops_run(world):
    row = world.row("n-new")
    world.answers({"answer": row, "cost": FAKE_COST}, row)
    _, out = world.run("--budget", SMALL_BUDGET)
    assert "budget spent" in out
    assert len(world.sessions) == 1 and not world.attached("n-new")
    assert world.record().groups == []


def test_run_does_not_inflate_new_since(world):
    for path in world.store.root.rglob("*"):
        if path.is_file():
            os.utime(path, (LONG_AGO, LONG_AGO))

    def count() -> int:
        world.capsys.readouterr()
        assert (
            mem.main(["--root", str(world.store.root), "curate", "--new-since", str(CUTOFF)]) == 0
        )
        return int(world.capsys.readouterr().out.strip())

    before = count()
    world.answers(world.row("n-new"), world.row("n-new"))
    world.run()
    assert world.attached("n-new")
    assert count() == before


def test_interrupted_run_keeps_its_groups(world):
    world.store.add_beta()
    world.store.new_note("n-beta", "Beta takes another claim.")
    world.store.set_line("n-beta", "topics", ["algorithms"])
    row = world.row("n-new")
    world.answers(row, row, {"answer": "boom", "error": True})
    _, out = world.run()
    record = world.record()
    assert [g.handles for g in record.groups] == [["s:alpha"]]
    assert record.failures and "failed:" in out
    assert "n-beta" not in run_state.read_done(world.folder)


def test_dry_run_changes_nothing(world):
    before = world.store.snapshot()
    code, out = world.run("--dry-run")
    assert code == 0 and "tokens" in out and "alpha: 2 notes" in out
    assert world.sessions == [] and world.commits() == []
    assert world.store.snapshot() == before
    assert not world.folder.exists()
