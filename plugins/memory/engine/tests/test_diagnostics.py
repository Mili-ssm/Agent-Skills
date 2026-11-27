import json
import os
from pathlib import Path

import mem


def test_diagnostics_reports_missing_roles_and_unknown_delivery(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("MEM_HOST", "codex")
    assert mem.main(["diagnostics"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["host"] == "codex"
    assert report["hooks"]["configured"]["SessionStart"] is True
    assert report["hooks"]["last_observed"] is None
    assert report["roles"]["installed"]["memory-researcher"] is False
    assert report["roles"]["session_visibility"] == "unknown"
    assert report["dependencies"]["claude"] is None
    assert report["store"]["path"] is None
    assert not (tmp_path / "mem-data").exists()


def test_diagnostics_reads_store_and_sanitizes_hook_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("MEM_HOST", "codex")
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("MEM_STORE", str(store))
    data = Path(os.environ["MEM_DATA"])
    (data / "hooks").mkdir(parents=True)
    (data / "hooks/log.jsonl").write_text(
        "invalid\n"
        + json.dumps({
            "host": "codex",
            "hook": "session-index",
            "t": "2026-01-01",
            "secret": "do not output",
        })
        + "\n{broken\n"
    )
    assert mem.main(["diagnostics"]) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["store"]["source"] == "MEM_STORE"
    assert report["store"]["readable"] is True
    assert report["hooks"]["last_observed"] == {
        "hook": "session-index",
        "time": "2026-01-01T00:00:00",
    }
    assert "do not output" not in out
