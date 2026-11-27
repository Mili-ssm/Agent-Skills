"""A fake `codex` for the builders' tests: prints the JSON-lines stream of `codex exec --json` that Task 1 of the
runner plan recorded (`thread.started`, an `agent_message`, `turn.completed` with usage), from a plan of steps.

A step is a dict: `answer` (the final message), `tokens` (billed input plus output), `exit` (the return code),
`silent` (no output at all), `failed` (a `turn.failed` event with that message, no `turn.completed`), `error` (an
`error` event with that message), `stderr` (text written to stderr), `py` (Python run in the session's folder first, to write the output file). Every call
appends `{argv, env, cwd, prompt}` to the log file."""

from __future__ import annotations

import json
import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

OUTPUT_TOKENS = 5

SCRIPT = f"""#!/usr/bin/env python3
import json, os, sys
plan = json.load(open(os.environ["FAKE_CODEX_PLAN"]))
count_file = os.environ["FAKE_CODEX_COUNT"]
n = int(open(count_file).read()) if os.path.exists(count_file) else 0
open(count_file, "w").write(str(n + 1))
prompt = sys.stdin.read()
with open(os.environ["FAKE_CODEX_LOG"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd(), "prompt": prompt}}) + "\\n")
step = plan[n] if n < len(plan) else {{"answer": "none"}}
if step.get("silent"):
    sys.exit(step.get("exit", 0))
if step.get("py"):
    exec(step["py"])
if step.get("stderr"):
    print(step["stderr"], file=sys.stderr)
events = [{{"type": "thread.started", "thread_id": "t"}}, {{"type": "turn.started"}}]
if step.get("answer") is not None:
    events.append({{"type": "item.completed", "item": {{"id": "i", "type": "agent_message", "text": step["answer"]}}}})
if step.get("error"):
    events.append({{"type": "error", "message": step["error"]}})
total = step.get("tokens", 1000)
if step.get("failed"):
    events.append({{"type": "turn.failed", "error": {{"message": step["failed"]}}}})
else:
        events.append({{"type": "turn.completed", "usage": {{"input_tokens": total - {OUTPUT_TOKENS}, "cached_input_tokens": 0,
                "output_tokens": {OUTPUT_TOKENS}, "reasoning_output_tokens": 0}}}})
for e in events:
    print(json.dumps(e))
sys.exit(step.get("exit", 0))
"""


class FakeCodex:
    def __init__(self, folder: Path) -> None:
        self.binary = folder / "fake-codex"
        self.plan_file = folder / "codex-plan.json"
        self.count_file = folder / "codex-count"
        self.log_file = folder / "codex-log.jsonl"
        self.binary.write_text(SCRIPT, encoding="utf-8")
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)

    def plan(self, *steps: dict) -> None:
        self.plan_file.write_text(json.dumps(list(steps)), encoding="utf-8")

    @property
    def calls(self) -> list[dict]:
        if not self.log_file.exists():
            return []
        return [json.loads(ln) for ln in self.log_file.read_text(encoding="utf-8").splitlines()]


def install(folder: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCodex:
    """A fake `codex` found through `MEM_CODEX`, and `MEM_RUNNER=codex`."""
    fake = FakeCodex(folder)
    monkeypatch.setenv("MEM_CODEX", str(fake.binary))
    monkeypatch.setenv("MEM_RUNNER", "codex")
    monkeypatch.setenv("FAKE_CODEX_PLAN", str(fake.plan_file))
    monkeypatch.setenv("FAKE_CODEX_COUNT", str(fake.count_file))
    monkeypatch.setenv("FAKE_CODEX_LOG", str(fake.log_file))
    return fake
