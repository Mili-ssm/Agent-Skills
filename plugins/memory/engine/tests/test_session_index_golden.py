"""Golden `mem session-index` output on a fixture store, with the failure and settled lines of the background jobs.

Pinned at plan base (A14, Task 3) before the capture, settle, digest and session modules moved: the expected text is a
literal and stays unchanged across the moves."""

import json
from pathlib import Path

import mem
from settle import state as settle_state
from settle import verdicts as settle_verdicts

FAILED_AT = 1_700_049_600  # 2023-11-15 12:00 UTC: the same date in every time zone

EXPECTED = (
    "memory: the mem command searches notes and memories (skill: memory). Store: 1 notes. Global memories: 1.\n"
    '- Before you act on this project, change something or research a topic: mem search "<topic in English>". '
    "It returns decisions, constraints and pitfalls recorded earlier that the files do not show.\n"
    "- To remember: preferences and personal matters -> auto memory; what a later session would need (a decision, "
    "constraint, pitfall or finding) -> mem remember, in English, with --global if it holds in any project and names "
    "no business; the project's current situation -> both.\n"
    "Automatic settling failed on 2023-11-15: boom; log: /l/capture.log (mem-settle ack clears this).\n"
    "Automatic capture failed on 2023-11-15: boom; log: /l/capture.log (mem-capture ack clears this).\n"
    "memory: settled since 2026-11-02: 1 merged; see `mem settle log`, undo with `mem settle undo <n>`, "
    "hide with `mem settle ack`.\n"
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_session_index_with_job_notices(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    (store / "knowledge" / "d").mkdir(parents=True)
    (store / "knowledge" / "d" / "n.md").write_text("x", encoding="utf-8")
    (store / "mem-store.yaml").write_text("format: 1\n", encoding="utf-8")
    memories = tmp_path / "global"
    memories.mkdir()
    (memories / "pin.md").write_text(
        "---\nkind: lesson\nclaim: Pin the golden.\ncreated: 2026-11-01\nobserved: 1\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (memories / settle_verdicts.LOG_NAME).write_text(
        json.dumps({"seq": 1, "decision": "merge", "date": "2026-11-02"}) + "\n", encoding="utf-8"
    )
    data = tmp_path / "mem-data"
    failure = {"failure": {"at": FAILED_AT, "reason": "boom", "log": "/l/capture.log"}}
    _write_json(data / "capture" / "status.json", failure)
    _write_json(settle_state.settle_dir(data, store) / "status.json", failure)
    monkeypatch.setenv("MEM_STORE", str(store))
    monkeypatch.setenv("MEM_MEMORIES", str(memories))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert mem.main(["session-index"]) == 0
    assert capsys.readouterr().out == EXPECTED
