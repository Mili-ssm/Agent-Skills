"""`mem-integrate --self-check`: no model, no cost. The briefs fill, the answer parser takes canned input, and the whole
flow (a run against a fake `claude`) works on a small store built in a temp folder, so it never touches the owner's data.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from integrate import answers
from integrate import state as run_state
from synthesize import pipeline as sp
from synthesize import run as synth_run

if TYPE_CHECKING:
    from types import ModuleType


logger = logging.getLogger(__name__)


class SelfCheckError(Exception):
    """A self-check step failed; the message says which."""


def _require(ok: object, reason: str) -> None:
    if not ok:
        raise SelfCheckError(reason)


FAKE_CLAUDE = """#!/usr/bin/env python3
import json
plan_file, count_file = {plan!r}, {count!r}
plan = json.load(open(plan_file))
try:
    n = int(open(count_file).read())
except OSError:
    n = 0
open(count_file, "w").write(str(n + 1))
answer = plan[n] if n < len(plan) else "none"
print(json.dumps({{"type": "result", "is_error": False, "result": answer,
                  "total_cost_usd": 0.0, "modelUsage": {{}}}}))
"""
CHECK_PART = "Values have exactly one owner.[old-note](../knowledge/notes/old-note.md)"
NOTE_BODY = (
    "## Claim\n\n{claim}\n\n## Evidence\n\nObserved.\n\n## Applies when\n\nAlways.\n\n"
    "## Does not apply when\n\nNever.\n"
)


def _check_briefs(runner: ModuleType) -> None:
    for name in ("place", "check"):
        try:
            text = sp.brief(name, briefs=runner.INTEGRATE_BRIEFS, INPUT_FILE="/tmp/input.json")
        except AssertionError as exc:
            raise SelfCheckError(f"the {name} brief: {exc}") from exc
        _require("/tmp/input.json" in text, f"the {name} brief does not name its input file")


def _check_parser() -> None:
    row = "n | s:a#b | append | ab12cd34ef"
    _require(answers.answer_lines(f"```\n{row}\n```") == [row], "a good answer was refused")
    _require(answers.answer_lines("none") == ["none"], "`none` was refused")
    _require(answers.answer_lines("I think n fits.") is None, "a malformed answer was accepted")
    _require(answers.answer_lines(f"none\n{row}") is None, "`none` with a row was accepted")


def _mem(store: Path, env: dict, *args: str) -> str:
    found = sp.mem(store, env, *args)
    _require(
        found.returncode == 0, f"mem {' '.join(args[:2])} failed: {found.stderr.strip()[:200]}"
    )
    return found.stdout


def _build_store(tmp: Path) -> tuple[Path, dict]:
    """A store with synthesis `alpha` (part `basics`, member `old-note`) and one loose note, `new-note`."""
    store = tmp / "store"
    env = synth_run.session_env(store)  # as `run_env`: the check clears every MEM_ variable first
    found = subprocess.run(
        [str(sp.MEM), "init", str(store)],
        env=env,
        cwd=tmp,
        capture_output=True,
        text=True,
        check=False,
    )
    _require(found.returncode == 0, f"mem init failed: {found.stderr.strip()[:200]}")
    for slug, claim in (("old-note", "Ownership is tracked."), ("new-note", "Moves are default.")):
        body = tmp / f"{slug}.md"
        body.write_text(NOTE_BODY.format(claim=claim), encoding="utf-8")
        _mem(
            store, env, "new", "knowledge", "--slug", slug, "--claim", claim, "--topics", "notes",
            "--confidence", "low", "--level", "basic", "--origin", "experience",
            "--body-file", str(body),
        )  # fmt: skip
    summary, part = tmp / "summary.md", tmp / "part.md"
    summary.write_text("Rust ownership.\n", encoding="utf-8")
    part.write_text(
        f"{CHECK_PART}\n\nSources: [old-note](../knowledge/notes/old-note.md)\n",
        encoding="utf-8",
    )
    _mem(
        store, env, "synthesis", "new", "--title", "Alpha", "--topics", "notes", "--slug", "alpha",
        "--summary-file", str(summary),
    )  # fmt: skip
    _mem(
        store, env, "synthesis", "add", "s:alpha", "--section", "Basics", "--body-file", str(part)
    )  # fmt: skip
    _mem(store, env, "synthesis", "attach", "old-note", "s:alpha#basics")
    return store, env


def _fake_claude(tmp: Path, replies: list[str]) -> Path:
    (tmp / "plan.json").write_text(json.dumps(replies), encoding="utf-8")
    script = tmp / "fake-claude"
    script.write_text(
        FAKE_CLAUDE.format(plan=str(tmp / "plan.json"), count=str(tmp / "count")), encoding="utf-8"
    )
    script.chmod(0o755)
    return script


def _isolate(tmp: Path) -> None:
    """Point every state folder at `tmp`, so the check never touches the owner's data. Changes `os.environ`:
    call it inside `mock.patch.dict(os.environ)`."""
    for name in [k for k in os.environ if k.startswith("MEM_")]:
        os.environ.pop(name)  # every one the check does not set below
    for name, folder in (
        ("MEM_DATA", "data"),
        ("XDG_DATA_HOME", "share"),
        ("MEM_PROJECT", "project"),
        ("XDG_CONFIG_HOME", "cfg"),
    ):
        os.environ[name] = str(tmp / folder)


def _check_flow(runner: ModuleType, place_check: tuple[str, str] | None) -> None:
    with (
        tempfile.TemporaryDirectory(prefix="mem-integrate-check-") as tmp_name,
        mock.patch.dict(os.environ),
    ):
        _isolate(Path(tmp_name))
        _flow(runner, Path(tmp_name), place_check)


def _flow(runner: ModuleType, tmp: Path, place_check: tuple[str, str] | None) -> None:
    store, env = _build_store(tmp)
    cands = json.loads(_mem(store, env, "synthesis", "integrate", "--candidates"))
    _require(cands and cands[0]["parts"], "the fixture store offers no candidate")
    row = f"new-note | s:alpha#basics | append | {cands[0]['parts'][0]['fingerprint']}"
    replies = list(place_check or (row, row))
    claude = _fake_claude(tmp, replies)
    captured = io.StringIO()
    with redirect_stdout(captured):
        code = runner.cmd_run(store, str(claude), None)
    _require(code == 0, f"the run exited {code}")
    folder = runner.state_folder(store)
    run_id = max(p.name for p in folder.iterdir() if p.is_dir())
    record = run_state.read_record(folder, run_id)
    _require(record is not None, "the run left no record")
    failures = record.failures if record else []
    _require(
        not any(runner.UNREADABLE_FAILURE in f for f in failures),
        f"a session could not read its input file: {failures}",
    )
    _require(not failures, f"the run failed: {failures}")
    attached = next(iter(store.glob("knowledge/*/new-note.md"))).read_text(encoding="utf-8")
    _require(
        re.search(r"(?m)^part_of: \"?alpha#basics", attached), "the agreed row was not applied"
    )
    _require(
        record is not None and [g.kind for g in record.groups] == ["integrate"],
        "the run did not record one integrate group",
    )


def self_check(runner: ModuleType, answers_given: tuple[str, str] | None = None) -> int:
    """No cost: the briefs fill, the answer parser on canned input, then the whole flow (a run against a fake
    `claude`) on a small store built in a temp folder. `runner` is the `entry.integrate` module (it imports this one, so this one cannot import it); `answers_given` replaces the fake's place and check answers."""
    try:
        _check_briefs(runner)
        _check_parser()
        _check_flow(runner, answers_given)
    except SelfCheckError as exc:
        print(f"self-check failed: {exc}")
        return 1
    except Exception as exc:  # any broken step ends as a line, not a traceback
        logger.debug("self-check failed", exc_info=True)
        print(f"self-check failed: {type(exc).__name__}: {exc}")
        return 1
    print("self-check passed")
    return 0
