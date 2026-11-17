"""Shared setup for the trial scripts: everything a trial touches lives under `<repo>/target/`.

The sessions get their own config, data and work folders there and never the owner's real store or global
memories; the installed plugin's `bin/` is dropped from PATH so sessions run the `mem` under test."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLUGIN = Path(__file__).resolve().parents[1]
TARGET = REPO / "target" / "mem-trials"


def work_dir(prefix: str) -> Path:
    TARGET.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=TARGET)).resolve()


def make_env(work: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("MEM_STORE", "MEM_MEMORIES", "MEM_PROJECT")}
    env.update(XDG_CONFIG_HOME=str(work / "cfg"), XDG_DATA_HOME=str(work / "xdg-data"), MEM_DATA=str(work / "data"))
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if "/plugins/cache/" not in p)
    (work / "cfg" / "agent-memory").mkdir(parents=True, exist_ok=True)
    (work / "cfg" / "agent-memory" / "forbidden-terms").write_text("")
    return env


def leftover_folders(work: Path) -> list[Path]:
    """The `~/.claude/projects` folders the sessions created for `work` and the projects inside it."""
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str(work.resolve()))
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.name == encoded or p.name.startswith(encoded + "-")]


def clean(work: Path) -> None:
    for leftover in leftover_folders(work):
        shutil.rmtree(leftover, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)


def _real_store() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "agent-memory" / "store"


def self_check(prefix: str) -> int:
    """No model: prove that a session's `mem` sees only the folders under `target/`."""
    real = _real_store()
    before = real.stat().st_mtime_ns if real.exists() else None
    work = work_dir(prefix)
    env = make_env(work)
    project = work / "self-check-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    out = subprocess.run([str(PLUGIN / "bin" / "mem"), "session-index"], cwd=project, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert "Store:" not in out, f"a store was found from the real home:\n{out}"
    assert Path(env["XDG_DATA_HOME"]).resolve().is_relative_to(TARGET.parent), env["XDG_DATA_HOME"]
    assert not any("/plugins/cache/" in p for p in env["PATH"].split(os.pathsep)), "installed plugin on PATH"
    after = real.stat().st_mtime_ns if real.exists() else None
    assert before == after, "the owner's store folder changed"
    clean(work)
    print("self-check passed")
    return 0
