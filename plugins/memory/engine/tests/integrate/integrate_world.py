"""The world `mem-integrate` tests run in: a store with one synthesis part, a git history, and a fake `claude` that
answers from a queue. Shared, not a `conftest.py`: a second one would replace `tests/conftest.py` for the modules that
import from it."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

import pytest
from entry import integrate as entry
from integrate import state as run_state
from integrate_store import (  # ruff: ignore[unused-import]  (a fixture)
    store_with_part,
)

if TYPE_CHECKING:
    from pathlib import Path

    from integrate_store import Store

LOGS = (".git", ".curation-log")


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
if step.get("silent"):
    sys.exit(0)
print(json.dumps({"type": "result", "is_error": step.get("error", False), "result": step["answer"],
                  "total_cost_usd": step.get("cost", 0.02), "modelUsage": {}}))
"""


def flag_values(argv: list[str], flag: str) -> list[str]:
    start = argv.index(flag) + 1
    stop = next((i for i in range(start, len(argv)) if argv[i].startswith("--")), len(argv))
    return argv[start:stop]


class Outcome(NamedTuple):
    rc: int
    out: str
    err: str


def snapshot(root: Path, ignore: tuple[str, ...] = ()) -> dict[str, bytes]:
    """Every file under `root` by relative path, minus those with a path part that starts with an `ignore`."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not any(part.startswith(ignore) for part in p.relative_to(root).parts)
    }


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
                "tools": ",".join(flag_values(argv, "--tools")),
                "allowed_tools": flag_values(argv, "--allowedTools"),
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

    def _main(self, *argv: str) -> Outcome:
        self.capsys.readouterr()
        code = entry.main([*argv, "--store", str(self.store.root), "--claude", str(self.claude)])
        captured = self.capsys.readouterr()
        return Outcome(code, captured.out, captured.err)

    def undo(self, run_id: str | None = None) -> Outcome:
        """`mem-integrate --undo RUN` (the latest run by default)."""
        return self._main("--undo", run_id or self.record().run_id)

    def status(self) -> Outcome:
        return self._main("status")

    def mem(self, *argv: str) -> Outcome:
        return Outcome(*self.store.mem(*argv))

    def edit_note(self, slug: str) -> None:
        """An owner edit outside `mem`: the note's text changes, the curation log does not."""
        path = self.store.note_path(slug)
        path.write_text(path.read_text(encoding="utf-8") + "\nAn owner edit.\n", encoding="utf-8")

    def live_text(self) -> str:
        return self.store.write("live.md", "A live addition.\n")

    @property
    def folder(self) -> Path:
        return entry.state_folder(self.store.root)

    def record(self) -> run_state.RunRecord:
        run_id = max(p.name for p in self.folder.iterdir() if p.is_dir())
        found = run_state.read_record(self.folder, run_id)
        assert found is not None
        return found

    def work_file(self, name: str, index: int = 0) -> Path:
        """A session's input file of the latest run, in that run's folder only."""
        return self.folder / self.record().run_id / "work" / str(index) / name

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
