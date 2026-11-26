"""`mem remember --origin`: web and pipeline writes are marked and do not start the automatic run."""

import time

import mem
import pytest
from store import records


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    monkeypatch.setenv("MEM_PROJECT", str(tmp_path))
    return folder


def remember(*extra, claim="Retries need idempotency keys."):
    return mem.main(["remember", "--global", "--kind", "lesson", "--claim", claim, *extra])


def test_origin_is_stored_and_a_session_write_has_none(gfolder):
    assert remember("--origin", "web") == 0
    assert remember("--origin", "pipeline", claim="Another claim entirely.") == 0
    assert remember(claim="A claim from a session.") == 0
    got = {m.handle: m.origin for m in records.load_memories(gfolder, "global")}
    assert got == {
        "retries-need-idempotency-keys": "web",
        "another-claim-entirely": "pipeline",
        "a-claim-from-a-session": None,
    }
    assert "origin" not in (gfolder / "a-claim-from-a-session.md").read_text()


def test_an_unknown_origin_is_refused(gfolder, capsys):
    with pytest.raises(SystemExit):
        remember("--origin", "dream")


def test_a_web_memory_is_marked_unconfirmed_in_search_and_memories(gfolder, hub_root, capsys):
    assert remember("--origin", "web") == 0
    assert remember("--origin", "pipeline", claim="Idempotency keys expire daily.") == 0
    capsys.readouterr()
    assert mem.main(["--root", str(hub_root), "search", "idempotency keys"]) == 0
    out = capsys.readouterr().out
    assert "[memory: lesson, observed 1, " in out
    assert ", web, unconfirmed]\tRetries need idempotency keys." in out
    assert "pipeline" not in out and "Idempotency keys expire daily." in out
    assert mem.main(["memories", "--global"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [ln for ln in lines if "web, unconfirmed" in ln] == [
        next(ln for ln in lines if "Retries need" in ln)
    ]


def test_new_since_leaves_out_web_and_pipeline_records(gfolder, capsys):
    assert remember(claim="Written in a session.") == 0
    assert remember("--origin", "web", claim="Found on a page.") == 0
    assert remember("--origin", "pipeline", claim="Written by a pipeline.") == 0
    capsys.readouterr()
    assert mem.main(["curate", "--new-since", "0"]) == 0
    assert capsys.readouterr().out.strip() == "1"
    assert mem.main(["curate", "--new-since", str(time.time() + 10)]) == 0
    assert capsys.readouterr().out.strip() == "0"
