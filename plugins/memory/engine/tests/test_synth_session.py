"""Background sessions run in a sandbox: scoped reads, a `mem` allow-list, no network, body files under the roots."""
import subprocess
from pathlib import Path

import pytest

import mem
import research_checks
import synth_pipeline as sp


def test_run_session_scopes_reads_and_sets_the_sandbox(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(cmd=cmd, env=kwargs["env"])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(sp.subprocess, "run", fake_run)
    store, work = tmp_path / "store", tmp_path / "work"
    store.mkdir()
    work.mkdir()
    env = {"PATH": "/bin"}
    sp.run_session("claude", "haiku", "p", work, tmp_path / "s.json", env, tmp_path / "log", read_roots=[store, work])
    cmd = seen["cmd"]
    assert "Read" not in cmd and "Grep" not in cmd and "Glob" not in cmd
    for tool in ("Read", "Grep", "Glob"):
        assert f"{tool}(/{store}/**)" in cmd
    assert "Bash(mem *)" not in cmd and "Bash(mem show*)" in cmd and "Bash(mem synthesis edit*)" in cmd
    assert not any(c.startswith("Bash(mem import") or c.startswith("Bash(mem fetch") for c in cmd)
    assert seen["env"]["MEM_SANDBOX"] == "1"
    assert seen["env"]["MEM_SANDBOX_ROOTS"].split(":") == [str(store), str(work)]
    assert "MEM_SANDBOX" not in env   # the caller's environment is left alone


def test_sandbox_refuses_network_import_urls_and_outside_body_files(hub_root, tmp_path, monkeypatch, capsys):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir()
    outside.mkdir()
    body = outside / "body.md"
    body.write_text("## Claim\n\nx\n")
    monkeypatch.setenv("MEM_SANDBOX", "1")
    monkeypatch.setenv("MEM_SANDBOX_ROOTS", str(inside))
    monkeypatch.chdir(inside)
    with pytest.raises(research_checks.FetchRefused, match="network access is off"):
        research_checks.fetch_raw("http://example.com/", lambda _: 10)
    assert mem.main(["--root", str(hub_root), "import", str(outside)]) == 2
    assert mem.main(["--root", str(hub_root), "fetch-sources"]) == 2
    assert mem.main(["--root", str(hub_root), "new", "literature", "--url", "http://example.com/x", "--title", "T", "--author", "A", "--year", "2020", "--kind", "paper", "--level", "basic", "--slug", "t",
                     "--topics", "computing"]) == 2
    assert mem.main(["--root", str(hub_root), "new", "knowledge", "--slug", "s", "--claim", "c", "--topics", "biology",
                     "--confidence", "low", "--level", "beginner", "--origin", "research",
                     "--body-file", str(body)]) == 2
    assert "outside the folders" in capsys.readouterr().err
    near = inside / "body.md"
    near.write_text("## Claim\n\nx\n")
    link = inside / "link.md"
    link.symlink_to(body)
    assert mem.main(["--root", str(hub_root), "new", "knowledge", "--slug", "s", "--claim", "c", "--topics", "biology",
                     "--confidence", "low", "--level", "beginner", "--origin", "research",
                     "--body-file", str(link)]) == 2   # a symlink out of the roots is outside
    monkeypatch.delenv("MEM_SANDBOX")
    with pytest.raises(research_checks.FetchError):   # without the sandbox the call goes on (refused later: no host)
        research_checks.fetch_raw("ftp://example.com/", lambda _: 10)
