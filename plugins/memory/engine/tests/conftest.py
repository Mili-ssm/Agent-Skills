import os
import shutil
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "valid"
# Read before any test points HOME at a temp dir: `bin/mem` runs `uv run --script`, and an empty uv cache
# per test costs about 0.35 s per launch plus a network fetch of its dependencies.
UV_CACHE = os.environ.get("UV_CACHE_DIR") or str(
    Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "uv"
)


@pytest.fixture
def hub_root(tmp_path: Path) -> Path:
    root = tmp_path / "hub"
    shutil.copytree(FIXTURE, root)
    shutil.copytree(ENGINE / "templates", root / "templates")
    (root / "mem-store.yaml").write_text(
        "format: 1\n", encoding="utf-8"
    )  # the marker that makes a store writable
    return root


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEM_DATA", str(tmp_path / "mem-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "mem-config"))
    monkeypatch.setenv(
        "XDG_DATA_HOME", str(tmp_path / "mem-share")
    )  # the default store never lands in the real home
    monkeypatch.delenv("MEM_STORE", raising=False)
    monkeypatch.setenv("UV_CACHE_DIR", UV_CACHE)  # the real cache, even where a test sets HOME
    # not the repository the tests run in: its own .memory/ would leak into every command that reads project memories
    monkeypatch.setenv("MEM_PROJECT", str(tmp_path / "mem-project"))
    monkeypatch.delenv("MEM_MEMORIES", raising=False)
    # a session sets MEM_* and the plugin options (user config) in its environment; the tests must not read them
    for name in [n for n in os.environ if n.startswith(("MEM_", "CLAUDE_PLUGIN_OPTION_"))]:
        if name not in {"MEM_DATA", "MEM_PROJECT"}:
            monkeypatch.delenv(name, raising=False)


def usage_log_path() -> Path:
    return Path(os.environ["MEM_DATA"]) / "usage" / "log.jsonl"
